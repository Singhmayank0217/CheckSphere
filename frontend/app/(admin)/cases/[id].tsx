import { useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { Image } from "expo-image";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api, downloadFile, fileUrl } from "@/src/api";
import { MiniMap } from "@/src/components/MiniMap";
import { TextField } from "@/src/components/fields";
import { BackHeader, Banner, Btn, Card, DisplayRow, Empty, ErrorBox, FLAG_LABELS, Loading, PopupModal, Screen, SectionTitle, StatusPill, showToast } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { makeStyles, radius, spacing, typography } from "@/src/theme";

const ACTION_LABELS: Record<string, string> = {
  report_approve: "Report approved", report_return: "Returned for correction", report_inconclusive: "Marked inconclusive",
  report_exception: "Marked mismatch/exception", report_escalate: "Escalated", escalated_to_super_admin: "Escalated to Super Admin",
};

function detailText(d: Record<string, any>) {
  return Object.entries(d)
    .filter(([, v]) => v !== "" && v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0))
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(", ") : String(v)}`)
    .join(" · ");
}

function TimelineList({ items }: { items: any[] }) {
  const styles = useStyles();
  return (
    <View>
      {items.map((t, i) => (
        <View key={i} style={styles.tlRow} testID={`timeline-${t.action}-${i}`}>
          <View style={styles.tlDot} />
          <View style={{ flex: 1 }}>
            <Text style={styles.tlAction}>{ACTION_LABELS[t.action] ?? (t.action ?? "").replace(/_/g, " ")}</Text>
            <Text style={styles.tlMeta}>{t.by_name} · {t.at ? new Date(t.at).toLocaleString() : ""}</Text>
            {t.details && detailText(t.details) ? (
              <Text style={styles.tlMeta}>{detailText(t.details)}</Text>
            ) : null}
          </View>
        </View>
      ))}
    </View>
  );
}

export default function CaseReview() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user, token } = useSession();
  const queryClient = useQueryClient();
  const styles = useStyles();
  const [reveal, setReveal] = useState(false);
  const [action, setAction] = useState<null | "return" | "approve" | "inconclusive" | "exception" | "escalate">(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [photo, setPhoto] = useState<string | null>(null);

  const caseQ = useQuery({ queryKey: ["case", id], queryFn: () => api<any>(`/cases/${id}`), enabled: !!id });
  const reportId = caseQ.data?.latest_report?.id;
  const reviewQ = useQuery({
    queryKey: ["review", reportId, reveal],
    queryFn: () => api<any>(`/reports/${reportId}${reveal ? "?reveal=1" : ""}`),
    enabled: !!reportId,
  });

  const doAction = async () => {
    if (!reportId || !action) return;
    setBusy(true);
    try {
      await api(`/reports/${reportId}/review`, { method: "POST", body: { action, comment } });
      queryClient.invalidateQueries({ queryKey: ["review"] });
      queryClient.invalidateQueries({ queryKey: ["case", id] });
      queryClient.invalidateQueries({ queryKey: ["admin-cases"] });
      showToast(`Report ${action === "return" ? "returned for correction" : action + (action.endsWith("e") ? "d" : "ed")}`, "success");
      setAction(null);
      setComment("");
    } catch (e: any) {
      showToast(e?.message ?? "Action failed", "error");
    } finally {
      setBusy(false);
    }
  };

  if (caseQ.isLoading) return <Screen><Loading label="Loading case…" /></Screen>;
  if (caseQ.isError || !caseQ.data) return <Screen><ErrorBox message="Failed to retrieve case." onRetry={() => caseQ.refetch()} /></Screen>;

  const c = { ...caseQ.data, ...(reviewQ.data?.case ? { status: reviewQ.data.case.status } : {}) };
  const r = reviewQ.data;
  const report = r?.report;
  const gps = report?.gps?.lat ? report.gps : null;
  const canExport = c.status === "approved" || c.status === "exported";

  return (
    <Screen testID="case-review-screen">
      <BackHeader title="Case Review" testID="review-back-btn" />
      <Card>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: spacing.sm }}>
          <View style={{ flex: 1, minWidth: 200 }}>
            <Text style={styles.title}>{c.internal_case_id}</Text>
            <Text style={styles.meta}>{c.applicant_name} · {c.client_name} · {c.branch_name ?? "-"}</Text>
          </View>
          <StatusPill status={c.status} testID="review-case-status" />
        </View>
        <DisplayRow label="Client Case ID" value={c.client_case_id} />
        <DisplayRow label="Verification Type" value={c.report_type_name || c.report_type} />
        <DisplayRow label="Assigned Address" value={c.assigned_address} />
        <DisplayRow label="Due" value={c.due_at ? new Date(c.due_at).toLocaleString() : "-"} />
        <DisplayRow label="Agent" value={c.assigned_agent_name} />
      </Card>

      {(c.flags ?? []).length > 0 ? (
        <Banner tone="error" message={`Exception flags for review (flags never auto-reject a report): ${c.flags.map((f: string) => FLAG_LABELS[f] ?? f).join(", ")}`} />
      ) : null}

      {!report ? (
        <Empty title="No report yet" message="The agent has not submitted a report for this case." />
      ) : reviewQ.isLoading ? (
        <Loading label="Loading report…" />
      ) : (
        <>
          {r?.masked ? (
            <View style={styles.revealRow}>
              <Btn label={reveal ? "Hide Sensitive Numbers" : "Reveal Sensitive Numbers"} variant="secondary" small onPress={() => setReveal(!reveal)} testID="reveal-toggle-btn" />
            </View>
          ) : null}

          {(r?.config?.sections ?? []).map((section: any, si: number) => (
            <Card key={si}>
              <SectionTitle>{section.title}</SectionTitle>
              {section.fields.map((f: any) => (
                <DisplayRow key={f.key} label={f.label} value={r?.masked_data?.[f.key]} />
              ))}
            </Card>
          ))}

          <Card>
            <SectionTitle>Report & Visit Evidence</SectionTitle>
            <DisplayRow label="Report Version" value={`v${report.version} · ${report.status}`} />
            <DisplayRow label="Submitted By" value={`${report.submitted_by_name ?? "-"} · ${report.submitted_at ? new Date(report.submitted_at).toLocaleString() : "-"}`} />
            <DisplayRow label="Declaration" value={report.declaration ? "Accepted by agent" : "Missing"} />
            <DisplayRow label="Offline Sync" value={report.offline_synced ? "Synced from offline draft" : "Live"} />
          </Card>

          {gps ? (
            <Card>
              <SectionTitle>GPS Location</SectionTitle>
              <MiniMap lat={gps.lat} lon={gps.lon} accuracy={gps.accuracy} height={200} testID="review-map" />
            </Card>
          ) : (
            <Banner tone="warning" message="No GPS coordinates captured with this report." />
          )}

          {(r?.evidence ?? []).length > 0 ? (
            <Card>
              <SectionTitle>Photographs & Documents ({r.evidence.length})</SectionTitle>
              <View style={styles.gallery}>
                {r.evidence.map((e: any) => (
                  <Pressable key={e.id} onPress={() => setPhoto(e.id)} testID={`evidence-thumb-${e.slot}`}>
                    <Image source={{ uri: fileUrl(e.id, token) }} style={styles.thumb} contentFit="cover" transition={150} />
                    <Text style={styles.thumbLabel}>{e.slot}</Text>
                  </Pressable>
                ))}              </View>
            </Card>
          ) : (
            <Banner tone="warning" message="No photographs or supporting documents attached to this report." />
          )}

          {(r?.call_logs ?? []).length > 0 ? (
            <Card>
              <SectionTitle>Call Attempt Log</SectionTitle>
              {r.call_logs.map((cl: any) => (
                <DisplayRow key={cl.id} label={cl.phone_number}
                  value={`${cl.result} · ${new Date(cl.attempt_at).toLocaleString()}${cl.person_met ? ` · ${cl.person_met}` : ""}`} />
              ))}
            </Card>
          ) : null}

          {report.review_comment ? (
            <Banner tone="warning" message={`Last review comment: ${report.review_comment}`} />
          ) : null}

          <Card>
            <SectionTitle>Report Versions</SectionTitle>
            {(r?.versions ?? []).map((v: any) => (
              <DisplayRow key={v.id} label={`v${v.version} · ${v.status}`}
                value={`${v.submitted_by_name ?? "-"} ${v.submitted_at ? new Date(v.submitted_at).toLocaleString() : ""}`} />
            ))}
          </Card>

          <Card>
            <SectionTitle>Case Timeline</SectionTitle>
            <TimelineList items={r?.timeline ?? []} />
          </Card>

          {(c.status === "submitted" || c.status === "under_review" || c.status === "returned") && user?.role !== "agent" ? (
            <Card>
              <SectionTitle>Supervisor Decision</SectionTitle>
              <View style={styles.actionRow}>
                <Btn label="Approve" onPress={() => { setAction("approve"); setComment(""); }} testID="review-approve-btn" />
                <Btn label="Return for Correction" variant="secondary" onPress={() => { setAction("return"); setComment(""); }} testID="review-return-btn" />
              </View>
              <View style={styles.actionRow}>
                <Btn label="Mark Inconclusive" variant="secondary" onPress={() => { setAction("inconclusive"); setComment(""); }} testID="review-inconclusive-btn" />
                <Btn label="Mark Mismatch/Exception" variant="danger" onPress={() => { setAction("exception"); setComment(""); }} testID="review-exception-btn" />
              </View>
              <View style={styles.actionRow}>
                <Btn label="Escalate to Super Admin" variant="ghost" onPress={() => { setAction("escalate"); setComment(""); }} testID="review-escalate-btn" />
              </View>
            </Card>
          ) : null}

          {canExport ? (
            <Card>
              <SectionTitle>Exports (approved report)</SectionTitle>
              <View style={styles.actionRow}>
                <Btn label="Word (.docx)" variant="secondary" onPress={async () => {
                  try { await downloadFile(`/exports/case/${id}/docx`, `${c.internal_case_id}.docx`); } catch (e: any) { showToast(e.message, "error"); }
                }} testID="export-docx-btn" />
                <Btn label="PDF" variant="secondary" onPress={async () => {
                  try { await downloadFile(`/exports/case/${id}/pdf`, `${c.internal_case_id}.pdf`); } catch (e: any) { showToast(e.message, "error"); }
                }} testID="export-pdf-btn" />
              </View>
            </Card>
          ) : null}
        </>
      )}

      <View style={{ height: spacing.xl }} />

      <PopupModal visible={!!action} title={action === "return" ? "Return for Correction" : action ? `Confirm: ${action}` : ""} onClose={() => setAction(null)}>
        {action === "return" ? (
          <Banner tone="warning" message="Correction comments are mandatory when returning a report to the agent." />
        ) : null}
        <TextField label={action === "return" ? "Correction Comments (mandatory)" : "Comments (optional)"} value={comment} onChange={setComment} multiline testID="review-comment-input" />
        <Btn
          label={action === "return" ? "Return Report" : "Confirm"}
          onPress={doAction}
          loading={busy}
          disabled={action === "return" && !comment.trim()}
          testID="review-confirm-btn"
          full
        />
      </PopupModal>

      <Modal visible={!!photo} transparent animationType="fade" onRequestClose={() => setPhoto(null)}>
        <Pressable style={styles.photoOverlay} onPress={() => setPhoto(null)} testID="photo-modal">
          {photo ? <Image source={{ uri: fileUrl(photo, token) }} style={styles.photoFull} contentFit="contain" /> : null}
        </Pressable>
      </Modal>
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  title: { fontSize: typography.scale.xl, fontWeight: "800", color: colors.onSurface, fontFamily: typography.fontFamily },
  meta: { color: colors.muted, fontSize: typography.scale.sm, marginTop: 2 },
  revealRow: { marginBottom: spacing.md },
  gallery: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  thumb: { width: 110, height: 110, borderRadius: radius.sm, backgroundColor: colors.surfaceTertiary },
  thumbLabel: { fontSize: typography.scale.sm, color: colors.muted, marginTop: 2, textTransform: "capitalize" },
  actionRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm, flexWrap: "wrap" },
  tlRow: { flexDirection: "row", gap: spacing.sm, paddingVertical: spacing.xs, alignItems: "flex-start" },
  tlDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.brandSecondary, marginTop: 4 },
  tlAction: { color: colors.onSurface, fontWeight: "700", fontSize: typography.scale.sm, textTransform: "capitalize" },
  tlMeta: { color: colors.muted, fontSize: typography.scale.sm },
  photoOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.9)", alignItems: "center", justifyContent: "center", padding: spacing.xl },
  photoFull: { width: "100%", height: "90%" },
}));
