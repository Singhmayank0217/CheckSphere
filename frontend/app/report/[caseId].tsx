import { useCallback, useEffect, useState } from "react";
import { Linking, Pressable, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView, KeyboardStickyView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as NetInfo from "@react-native-community/netinfo";

import { api } from "@/src/api";
import { SelectField, SwitchRow, TextField } from "@/src/components/fields";
import { MiniMap } from "@/src/components/MiniMap";
import { PhotoSlots } from "@/src/components/PhotoSlots";
import { Banner, BackHeader, Btn, Card, DisplayRow, ErrorBox, FLAG_LABELS, Loading, Screen, SectionTitle, StatusPill, showToast } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { getGps } from "@/src/utils/geo";
import { markDraftSynced, readLocalDraft, saveLocalDraft } from "@/src/utils/drafts";
import { makeStyles, radius, spacing, typography } from "@/src/theme";

const PHONE_RESULTS = ["Confirmed", "Busy", "No Response", "Switched Off", "Call Later", "Invalid Number", "Refused", "Other"];

export default function ReportScreen() {
  const { caseId } = useLocalSearchParams<{ caseId: string }>();
  const { user, token } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const netInfo = NetInfo.useNetInfo();

  const ctxQ = useQuery({
    queryKey: ["report", caseId],
    queryFn: () => api<any>(`/reports/case/${caseId}`),
    enabled: !!caseId,
  });

  const [data, setData] = useState<Record<string, any>>({});
  const [gps, setGps] = useState<any>(null);
  const [gpsError, setGpsError] = useState<string | null>(null);
  const [gpsBusy, setGpsBusy] = useState(false);
  const [declaration, setDeclaration] = useState(false);
  const [problems, setProblems] = useState<string[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [restored, setRestored] = useState(false);
  const [call, setCall] = useState<any>({ phone_number: "", result: "", person_met: "", relationship: "", info_confirmed: "", notes: "" });
  const [savingCall, setSavingCall] = useState(false);

  const caseData = ctxQ.data?.case;
  const config = ctxQ.data?.config;
  const report = ctxQ.data?.report;
  const canEdit = !!ctxQ.data?.can_edit;
  const isAgent = user?.role === "agent";

  const setField = useCallback((key: string, v: any) => {
    setData((prev) => ({ ...prev, [key]: v }));
  }, []);

  const captureGps = useCallback(async () => {
    setGpsBusy(true);
    setGpsError(null);
    const r = await getGps();
    setGpsBusy(false);
    if (r.ok) {
      setGps({ lat: r.lat, lon: r.lon, accuracy: r.accuracy });
      if (config?.requires_gps && caseData && !caseData.visit) {
        try {
          await api(`/cases/${caseId}/visit-start`, { method: "POST", body: { lat: r.lat, lon: r.lon, accuracy: r.accuracy } });
          queryClient.invalidateQueries({ queryKey: ["report", caseId] });
          queryClient.invalidateQueries({ queryKey: ["case", caseId] });
        } catch {
          // non-blocking
        }
      }
    } else {
      setGpsError(r.message);
    }
  }, [caseData, caseId, config, queryClient]);

  // Initialise form data: prefill < server draft < local unsynced draft
  useEffect(() => {
    if (!ctxQ.data || !caseData) return;
    (async () => {
      const prefill: Record<string, any> = {
        client_name: caseData.client_name ?? "",
        branch_name: caseData.branch_name ?? "",
        internal_case_id: caseData.internal_case_id ?? "",
        client_case_id: caseData.client_case_id ?? "",
        applicant_name: caseData.applicant_name ?? "",
        co_applicant_name: caseData.co_applicant_name ?? "",
        agent_name: `${user?.name ?? ""} (${user?.agent_id ?? "staff"})`,
        visit_datetime: new Date().toLocaleString(),
      };
      const serverDraft = report && report.status === "draft" ? report : null;
      let base = { ...prefill, ...(serverDraft?.data ?? {}) };
      let dec = !!serverDraft?.declaration;
      let g = serverDraft?.gps?.lat ? serverDraft.gps : null;
      const local = await readLocalDraft(caseId!);
      if (local && !local.synced) {
        base = { ...base, ...local.data };
        dec = local.declaration;
        if (local.gps?.lat) g = local.gps;
        setRestored(true);
      }
      setData(base);
      setDeclaration(dec);
      if (g) setGps(g);
      if (!g && config?.requires_gps) await captureGps();
    })();
  }, [ctxQ.data, caseData, report, config, caseId, user, captureGps]);

  if (ctxQ.isLoading) return <Screen><Loading label="Initializing verification form…" /></Screen>;
  if (ctxQ.isError || !ctxQ.data) return <Screen><ErrorBox message="Failed to load the verification form." onRetry={() => ctxQ.refetch()} /></Screen>;

  const evidence = ctxQ.data.evidence ?? [];
  const callLogs = ctxQ.data.call_logs ?? [];
  const online = netInfo.isConnected !== false;

  const saveDraft = async () => {
    if (!canEdit) return;
    setSaving(true);
    try {
      await saveLocalDraft(caseId!, { data, gps: gps ?? {}, declaration });
      if (online) {
        await api(`/reports/case/${caseId}/draft`, {
          method: "PUT",
          body: { data, gps: gps ?? {}, declaration, offline_synced: false },
        });
        await markDraftSynced(caseId!);
        queryClient.invalidateQueries({ queryKey: ["report", caseId] });
        queryClient.invalidateQueries({ queryKey: ["case", caseId] });
        queryClient.invalidateQueries({ queryKey: ["agent-cases"] });
        showToast("Draft saved and synced", "success");
      } else {
        showToast("Draft saved offline (encrypted) — will auto-sync", "success");
      }
      setProblems(null);
    } catch (e: any) {
      showToast(e?.message ?? "Could not save draft", "error");
    } finally {
      setSaving(false);
    }
  };

  const onSubmit = async () => {
    if (!canEdit) return;
    setSubmitting(true);
    setProblems(null);
    try {
      await saveLocalDraft(caseId!, { data, gps: gps ?? {}, declaration });
      if (online) {
        await api(`/reports/case/${caseId}/submit`, {
          method: "POST",
          body: { data, gps: gps ?? {}, declaration, offline_synced: false },
        });
        await markDraftSynced(caseId!);
        queryClient.invalidateQueries({ queryKey: ["report", caseId] });
        queryClient.invalidateQueries({ queryKey: ["case", caseId] });
        queryClient.invalidateQueries({ queryKey: ["agent-cases"] });
        showToast("Report submitted for review", "success");
        router.replace("/(agent)/cases");
      } else {
        showToast("No internet — draft saved offline. It will sync automatically.", "error");
      }
    } catch (e: any) {
      if (e?.status === 422 && e?.data) {
        const d = e.data;
        const list = [
          ...(d.missing_fields ?? []).map((f: string) => `Missing required field: ${f}`),
          ...(d.problems ?? []),
          ...Object.entries(d.blocked_words ?? {}).map(
            ([k, v]) => `Remove restricted word(s) [${(v as string[]).join(", ")}] from "${k}"`,
          ),
        ];
        setProblems(list.length ? list : ["Submission blocked"]);
      } else {
        showToast(e?.message ?? "Submission failed", "error");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const addCallLog = async () => {
    if (!call.phone_number || !call.result) {
      showToast("Phone number and result are required", "error");
      return;
    }
    setSavingCall(true);
    try {
      await api(`/cases/${caseId}/call-logs`, { method: "POST", body: call });
      setCall({ phone_number: "", result: "", person_met: "", relationship: "", info_confirmed: "", notes: "" });
      queryClient.invalidateQueries({ queryKey: ["report", caseId] });
      showToast("Call attempt logged", "success");
    } catch (e: any) {
      showToast(e?.message ?? "Could not log call", "error");
    } finally {
      setSavingCall(false);
    }
  };

  const editable = canEdit;

  return (
    <View style={styles.root} testID="report-screen">
      <KeyboardAwareScrollView bottomOffset={72} contentContainerStyle={{ paddingTop: insets.top + spacing.lg, paddingHorizontal: spacing.lg, paddingBottom: 160 }}>
        <BackHeader testID="report-back-btn" />
        <View style={styles.header}>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>{config?.name ?? "Verification Report"}</Text>
            <Text style={styles.subtitle}>{caseData?.internal_case_id} · {caseData?.applicant_name}</Text>
          </View>
          <StatusPill status={caseData?.status} testID="report-case-status" />
        </View>

        {caseData?.status === "returned" && report?.review_comment ? (
          <Banner tone="error" message={`Supervisor correction comments: ${report.review_comment}`} />
        ) : null}
        {caseData && !["new", "assigned", "in_progress", "returned"].includes(caseData.status) && caseData.status !== "returned" ? (
          <Banner tone="info" message={`Report is ${caseData.status.replace("_", " ")} and locked for editing. It will reopen if the supervisor returns it.`} />
        ) : null}
        {restored ? <Banner tone="warning" message="Restored an unsynced offline draft from this device." /> : null}
        {!online ? <Banner tone="warning" message="You are offline. Drafts are saved encrypted on this device and sync automatically." /> : null}
        {(caseData?.flags ?? []).length > 0 ? (
          <Banner tone="warning" message={`Supervisor review flags: ${caseData.flags.map((f: string) => FLAG_LABELS[f] ?? f).join(", ")}`} />
        ) : null}
        {problems ? (
          <View style={styles.problemBox} testID="submission-problems">
            <Text style={styles.problemTitle}>Submission blocked — complete the following:</Text>
            {problems.map((p, i) => (
              <Text key={i} style={styles.problemItem}>• {p}</Text>
            ))}
          </View>
        ) : null}

        {config?.requires_gps ? (
          <Card>
            <SectionTitle action={
              <Btn label={gps ? "Refresh GPS" : "Capture GPS"} variant="secondary" small onPress={captureGps} loading={gpsBusy} testID="capture-gps-btn" />
            }>
              GPS Evidence
            </SectionTitle>
            {gps ? (
              <View>
                <MiniMap lat={gps.lat} lon={gps.lon} accuracy={gps.accuracy} height={150} testID="gps-map" />
                <Text style={styles.gpsStamp}>
                  {caseData?.visit ? `Visit started ${new Date(caseData.visit.started_at).toLocaleString()}` : "Visit start not recorded"}
                </Text>
              </View>
            ) : (
              <Text style={styles.gpsStamp}>{gpsError ?? "GPS will be captured automatically."}</Text>
            )}
            {gpsError ? (
              <Btn label="Open Settings" variant="secondary" small onPress={() => Linking.openSettings()} testID="gps-open-settings-btn" />
            ) : null}
          </Card>
        ) : null}

        {(config?.sections ?? []).map((section: any, si: number) => (
          <Card key={si}>
            <SectionTitle>{section.title}</SectionTitle>
            {section.fields.map((f: any) => {
              if (!editable) {
                return <DisplayRow key={f.key} label={f.label} value={ctxQ.data.masked_data?.[f.key] ?? data[f.key]} />;
              }
              if (f.type === "select") {
                return (
                  <SelectField
                    key={f.key}
                    label={f.label}
                    value={data[f.key]}
                    options={f.options ?? []}
                    onChange={(v) => setField(f.key, v)}
                    testID={`field-${f.key}`}
                  />
                );
              }
              return (
                <TextField
                  key={f.key}
                  label={f.label}
                  value={data[f.key]}
                  onChange={(v) => setField(f.key, v)}
                  required={f.required}
                  multiline={f.type === "textarea"}
                  keyboardType={f.type === "number" ? "numeric" : "default"}
                  autoCapitalize={f.type === "textarea" || f.type === "text" ? "sentences" : "none"}
                  testID={`field-${f.key}`}
                />
              );
            })}
          </Card>
        ))}

        <Card>
          <SectionTitle>Photo Evidence (in-app camera only)</SectionTitle>
          <PhotoSlots caseId={caseId!} slots={config?.photo_slots ?? []} evidence={evidence} canEdit={editable} token={token} />
        </Card>

        {config?.category === "telephone" ? (
          <Card>
            <SectionTitle>Call Attempt Log ({callLogs.length})</SectionTitle>
            {callLogs.map((cl: any) => (
              <View key={cl.id} style={styles.callRow} testID={`call-log-${cl.id}`}>
                <Text style={styles.callPhone}>{cl.phone_number}</Text>
                <Text style={styles.callMeta}>{cl.result} · {new Date(cl.attempt_at).toLocaleString()}</Text>
                {cl.person_met ? <Text style={styles.callMeta}>Person: {cl.person_met} ({cl.relationship ?? "-"})</Text> : null}
                {cl.notes ? <Text style={styles.callMeta}>{cl.notes}</Text> : null}
              </View>
            ))}
            {editable ? (
              <View>
                <TextField label="Phone Number Dialled" value={call.phone_number} onChange={(v) => setCall({ ...call, phone_number: v })} keyboardType="phone-pad" testID="call-phone-input" />
                <SelectField label="Result" value={call.result} options={PHONE_RESULTS} onChange={(v) => setCall({ ...call, result: v })} testID="call-result-select" />
                <TextField label="Person Spoken To" value={call.person_met} onChange={(v) => setCall({ ...call, person_met: v })} testID="call-person-input" />
                <TextField label="Relationship / Designation" value={call.relationship} onChange={(v) => setCall({ ...call, relationship: v })} testID="call-relationship-input" />
                <TextField label="Information Confirmed" value={call.info_confirmed} onChange={(v) => setCall({ ...call, info_confirmed: v })} multiline testID="call-info-input" />
                <TextField label="Factual Notes" value={call.notes} onChange={(v) => setCall({ ...call, notes: v })} multiline testID="call-notes-input" />
                <Btn label="Log Call Attempt" variant="secondary" onPress={addCallLog} loading={savingCall} testID="call-log-submit-btn" />
              </View>
            ) : null}
          </Card>
        ) : null}

        <Card>
          <SectionTitle>Agent Declaration</SectionTitle>
          <Text style={styles.declarationText}>
            &ldquo;I confirm that this report records my actual observations and authorised verification results.
            I have not added unsupported opinions or conclusions.&rdquo;
          </Text>
          {editable ? (
            <SwitchRow label="I accept this declaration" value={declaration} onChange={setDeclaration} testID="declaration-switch" />
          ) : (
            <DisplayRow label="Declaration" value={report?.declaration ? "Accepted" : "Pending"} />
          )}
        </Card>

        <Text style={styles.disclaimer}>
          This report records field observations and authorised verification results only. It does not assess
          creditworthiness, title, income adequacy, document authenticity, or loan eligibility.
        </Text>
      </KeyboardAwareScrollView>

      {editable ? (
        <KeyboardStickyView style={[styles.footer, { bottom: insets.bottom }]}>
          <Btn label="Save Draft" variant="secondary" onPress={saveDraft} loading={saving} testID="save-draft-btn" />
          <Btn label="Submit Report" onPress={onSubmit} loading={submitting} testID="submit-report-btn" />
        </KeyboardStickyView>
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.md, gap: spacing.sm },
  title: { fontSize: typography.scale.xl, fontWeight: "800", color: colors.onSurface, flexShrink: 1, fontFamily: typography.fontFamily },
  subtitle: { color: colors.muted, marginTop: 2 },
  problemBox: { backgroundColor: colors.error, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  problemTitle: { color: colors.onError, fontWeight: "700", marginBottom: 6 },
  problemItem: { color: colors.onError, fontSize: typography.scale.sm, lineHeight: 18 },
  gpsStamp: { color: colors.muted, fontSize: typography.scale.sm, marginTop: spacing.sm },
  callRow: { borderBottomWidth: 1, borderBottomColor: colors.divider, paddingVertical: spacing.sm, gap: 2 },
  callPhone: { color: colors.onSurface, fontWeight: "700" },
  callMeta: { color: colors.muted, fontSize: typography.scale.sm },
  declarationText: { color: colors.onSurfaceSecondary, fontSize: typography.scale.sm, lineHeight: 20, marginBottom: spacing.sm },
  disclaimer: { color: colors.muted, fontSize: typography.scale.sm, textAlign: "center", lineHeight: 18, paddingVertical: spacing.lg },
  footer: {
    position: "absolute", left: 0, right: 0, flexDirection: "row", gap: spacing.sm,
    padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderTopWidth: 1, borderTopColor: colors.border,
  },
}));
