import { useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";
import { Image } from "expo-image";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api, downloadFile, fileUrl } from "@/src/api";
import { SelectField, TextField } from "@/src/components/fields";
import { MiniMap } from "@/src/components/MiniMap";
import { Banner, Btn, DisplayRow, Empty, ErrorBox, FLAG_LABELS, Loading, PopupModal, StatusPill, showToast } from "@/src/components/ui";
import { usePortalBase } from "@/src/portal/base";
import { DataTable } from "@/src/portal/DataTable";
import { Page, Panel } from "@/src/portal/Page";
import { useSession } from "@/src/session";
import { makeStyles, radius, spacing } from "@/src/theme";

const TABS = ["Overview", "Report", "GPS and Map", "Photos and Documents", "Call Log", "Review and Comments", "Timeline and Audit Log", "Export History"];
type Action = "approve" | "return" | "inconclusive" | "exception" | "escalate";
const fmt = (d?: string) => (d ? new Date(d).toLocaleString() : "—");
const detail = (d: any) => Object.entries(d ?? {}).filter(([, v]) => v !== "" && v != null && !(Array.isArray(v) && !v.length)).map(([k, v]) => `${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(" · ");

export default function CaseDetailPage() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user, token } = useSession();
  const router = useRouter();
  const base = usePortalBase();
  const qc = useQueryClient();
  const styles = useStyles();
  const [tab, setTab] = useState(TABS[0]);
  const [reveal, setReveal] = useState(false);
  const [action, setAction] = useState<Action | null>(null);
  const [comment, setComment] = useState("");
  const [assignOpen, setAssignOpen] = useState(false);
  const [agentId, setAgentId] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [photo, setPhoto] = useState<string | null>(null);

  const caseQ = useQuery({ queryKey: ["case", id], queryFn: () => api<any>(`/cases/${id}`), enabled: !!id });
  const rid = caseQ.data?.latest_report?.id;
  const reviewQ = useQuery({ queryKey: ["review", rid, reveal], queryFn: () => api<any>(`/reports/${rid}${reveal ? "?reveal=1" : ""}`), enabled: !!rid });
  const evQ = useQuery({ queryKey: ["evidence", id], queryFn: () => api<any>(`/cases/${id}/evidence`), enabled: !!id });
  const callQ = useQuery({ queryKey: ["calls", id], queryFn: () => api<any>(`/cases/${id}/call-logs`), enabled: !!id });
  const auditQ = useQuery({ queryKey: ["case-audit", id], queryFn: () => api<any>(`/cases/${id}/audit`), enabled: !!id });
  const agentsQ = useQuery({ queryKey: ["agents"], queryFn: () => api<{ items: any[] }>("/users?role=agent") });
  const tlQ = useQuery({ queryKey: ["timeline", id], queryFn: () => api<any>(`/cases/${id}/timeline`), enabled: !!id });

  const refresh = () => ["case", "review", "admin-cases", "admin-stats", "case-audit", "timeline"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));

  if (caseQ.isLoading) return <Page><Loading label="Loading case…" /></Page>;
  if (caseQ.isError || !caseQ.data) return <Page><ErrorBox message="Case not found or not in your scope." onRetry={() => caseQ.refetch()} /></Page>;

  const c = { ...caseQ.data, ...(reviewQ.data?.case ? { status: reviewQ.data.case.status } : {}) };
  const r = reviewQ.data;
  const report = r?.report;
  const gps = report?.gps?.lat ? report.gps : null;
  const reviewable = ["submitted", "under_review"].includes(c.status) && !!rid;
  const exportable = !!rid && (user?.role === "super_admin" || ["approved", "exported"].includes(c.status));

  const doReview = async () => {
    setBusy(true);
    try {
      await api(`/reports/${rid}/review`, { method: "POST", body: { action, comment } });
      showToast("Decision recorded", "success");
      setAction(null); setComment(""); refresh();
    } catch (e: any) { showToast(e?.message ?? "Action failed", "error"); } finally { setBusy(false); }
  };
  const doAssign = async () => {
    setBusy(true);
    try {
      await api(`/cases/${id}/assign`, { method: "POST", body: { agent_id: agentId, reason } });
      showToast(c.assigned_agent_id ? "Case reassigned" : "Case assigned", "success");
      setAssignOpen(false); setReason(""); refresh();
    } catch (e: any) { showToast(e?.message ?? "Assign failed", "error"); } finally { setBusy(false); }
  };
  const doExport = async (fmtx: "docx" | "pdf") => {
    try { await downloadFile(`/exports/case/${id}/${fmtx}`, `${c.internal_case_id}.${fmtx}`); refresh(); showToast("Export downloaded", "success"); }
    catch (e: any) { showToast(e?.message ?? "Export failed", "error"); }
  };
  const open = (a: Action) => { setAction(a); setComment(""); };
  const evidence = r?.evidence ?? evQ.data?.items ?? [];

  return (
    <Page testID="portal-case-detail">
      <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace(`${base}/cases` as any))} testID="case-back-btn" style={{ marginBottom: spacing.md }}>
        <Text style={styles.back}>‹ Back to cases</Text>
      </Pressable>
      <View style={styles.titleRow}>
        <View style={{ flex: 1, minWidth: 260 }}>
          <Text style={styles.title}>{c.internal_case_id} · {c.applicant_name}</Text>
          <Text style={styles.sub}>{c.client_name} · {c.branch_name ?? "—"} · {c.report_type_name} · Agent: {c.assigned_agent_name ?? "Unassigned"}</Text>
        </View>
        <StatusPill status={c.status} testID="case-detail-status" />
      </View>

      <View style={styles.actions} testID="case-actions">
        <Btn label={c.assigned_agent_id ? "Reassign" : "Assign"} variant="secondary" small onPress={() => { setAgentId(""); setAssignOpen(true); }} testID={c.assigned_agent_id ? "action-reassign" : "action-assign"} />
        <Btn label="Approve" small disabled={!reviewable} onPress={() => open("approve")} testID="action-approve" />
        <Btn label="Return for Correction" variant="secondary" small disabled={!reviewable} onPress={() => open("return")} testID="action-return" />
        <Btn label="Mark Inconclusive" variant="secondary" small disabled={!reviewable} onPress={() => open("inconclusive")} testID="action-inconclusive" />
        <Btn label="Mark Exception" variant="danger" small disabled={!reviewable} onPress={() => open("exception")} testID="action-exception" />
        <Btn label="Escalate" variant="secondary" small disabled={!reviewable || user?.role === "super_admin"} onPress={() => open("escalate")} testID="action-escalate" />
        <Btn label="Export Word" variant="secondary" small disabled={!exportable} onPress={() => doExport("docx")} testID="action-export-docx" />
        <Btn label="Export PDF" variant="secondary" small disabled={!exportable} onPress={() => doExport("pdf")} testID="action-export-pdf" />
      </View>
      {(c.flags ?? []).length > 0 ? <Banner tone="error" message={`Evidence flags for supervisor review (never auto-reject): ${c.flags.map((x: string) => FLAG_LABELS[x] ?? x).join(", ")}`} /> : null}
      {c.escalated ? <Banner tone="warning" message="This case has been escalated to the Super Admin." /> : null}

      <View style={styles.tabs} testID="case-tabs">
        {TABS.map((t) => (
          <Pressable key={t} onPress={() => setTab(t)} style={[styles.tab, tab === t && styles.tabActive]} testID={`tab-${t.split(" ")[0].toLowerCase()}`}>
            <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>{t}</Text>
          </Pressable>
        ))}
      </View>

      {tab === "Overview" ? (
        <View style={styles.grid}>
          <Panel title="Case details" style={styles.col}>
            <DisplayRow label="Internal Case ID" value={c.internal_case_id} />
            <DisplayRow label="Client Case ID" value={c.client_case_id} />
            <DisplayRow label="Applicant" value={c.applicant_name} />
            <DisplayRow label="Co-applicant" value={c.co_applicant_name} />
            <DisplayRow label="Loan / Product" value={c.loan_type} />
            <DisplayRow label="Report Type" value={c.report_type_name} />
            <DisplayRow label="Priority" value={c.priority} />
          </Panel>
          <Panel title="Location and SLA" style={styles.col}>
            <DisplayRow label="Client" value={c.client_name} />
            <DisplayRow label="Branch" value={c.branch_name} />
            <DisplayRow label="Assigned Address" value={c.assigned_address} />
            <DisplayRow label="City / State" value={`${c.city ?? "—"}, ${c.state ?? "—"}`} />
            <DisplayRow label="Created" value={fmt(c.created_at)} />
            <DisplayRow label="Due" value={fmt(c.due_at)} />
            <DisplayRow label="Last Submitted" value={fmt(c.last_submitted_at)} />
            <DisplayRow label="Approved" value={c.approved_at ? `${fmt(c.approved_at)} by ${c.approved_by}` : "—"} />
          </Panel>
        </View>
      ) : null}

      {tab === "Report" ? (!rid ? <Empty title="No report submitted yet" /> : reviewQ.isLoading ? <Loading /> : (
        <View>
          <View style={{ flexDirection: "row", gap: spacing.sm, marginBottom: spacing.md }}>
            <Btn label={reveal ? "Hide Sensitive Numbers" : "Reveal Sensitive Numbers"} variant="secondary" small onPress={() => setReveal(!reveal)} testID="reveal-toggle-btn" />
            <Text style={[styles.sub, { alignSelf: "center" }]}>Version v{report?.version} · {report?.status} · Declaration {report?.declaration ? "accepted" : "missing"}</Text>
          </View>
          <View style={styles.grid}>
            {(r?.config?.sections ?? []).map((s: any, i: number) => (
              <Panel key={i} title={s.title} style={styles.col}>
                {s.fields.map((fd: any) => <DisplayRow key={fd.key} label={fd.label} value={r?.masked_data?.[fd.key]} />)}
              </Panel>
            ))}
          </View>
        </View>
      )) : null}

      {tab === "GPS and Map" ? (
        <View style={styles.grid}>
          <Panel title="Report GPS" style={styles.col}>
            {gps ? <MiniMap lat={gps.lat} lon={gps.lon} accuracy={gps.accuracy} height={300} testID="detail-map" /> : <Empty title="No GPS captured" />}
          </Panel>
          <Panel title="Visit" style={styles.col}>
            <DisplayRow label="Visit started" value={fmt(c.visit?.started_at)} />
            <DisplayRow label="Start location" value={c.visit ? `${c.visit.lat}, ${c.visit.lon} (±${c.visit.accuracy ?? "-"}m)` : "—"} />
            <DisplayRow label="Report GPS" value={gps ? `${gps.lat}, ${gps.lon} (±${gps.accuracy}m)` : "—"} />
            <DisplayRow label="Assigned coordinates" value={c.assigned_lat ? `${c.assigned_lat}, ${c.assigned_lon}` : "Not geocoded"} />
          </Panel>
        </View>
      ) : null}

      {tab === "Photos and Documents" ? (
        evidence.length === 0 ? <Empty title="No photos or documents" /> : (
          <View style={styles.gallery}>
            {evidence.map((e: any) => (
              <Pressable key={e.id} style={styles.evCard} onPress={() => setPhoto(e.id)} testID={`evidence-${e.id}`}>
                <Image source={{ uri: fileUrl(e.id, token) }} style={styles.evImg} contentFit="cover" />
                <Text style={styles.evTitle}>{e.slot}</Text>
                <Text style={styles.sub}>{fmt(e.captured_at)}</Text>
                <Text style={styles.sub}>GPS {e.gps?.lat ?? "—"}, {e.gps?.lon ?? "—"} ±{e.gps?.accuracy ?? "-"}m</Text>
                <Text style={styles.sub}>By {e.uploaded_by_name ?? "—"} · #{(e.sha256 ?? "").slice(0, 10)}</Text>
              </Pressable>
            ))}
          </View>
        )
      ) : null}

      {tab === "Call Log" ? (
        <DataTable testID="call-table" rows={callQ.data?.items ?? []} empty="No call attempts logged." columns={[
          { key: "attempt_at", label: "Date & Time", width: 170, render: (x) => <Text>{fmt(x.attempt_at)}</Text> },
          { key: "phone_number", label: "Number", width: 140 },
          { key: "result", label: "Result", width: 120 },
          { key: "person_met", label: "Person", width: 140 },
          { key: "relationship", label: "Relationship", width: 130 },
          { key: "info_confirmed", label: "Information Confirmed", width: 220 },
          { key: "notes", label: "Notes", width: 220 },
          { key: "agent_name", label: "Agent", width: 130 },
        ]} />
      ) : null}

      {tab === "Review and Comments" ? (
        <DataTable testID="versions-table" rows={r?.versions ?? []} empty="No report versions yet." columns={[
          { key: "version", label: "Version", width: 90, render: (v) => <Text>v{v.version}</Text> },
          { key: "status", label: "Status", width: 140, render: (v) => <StatusPill status={v.status} /> },
          { key: "submitted_by_name", label: "Submitted By", width: 150 },
          { key: "submitted_at", label: "Submitted", width: 170, render: (v) => <Text>{fmt(v.submitted_at)}</Text> },
          { key: "review_comment", label: "Supervisor Comment", width: 360 },
        ]} />
      ) : null}

      {tab === "Timeline and Audit Log" ? (
        <View style={styles.grid}>
          <Panel title="Case timeline" style={styles.col}>
            {(tlQ.data?.items ?? []).map((t: any, i: number) => (
              <View key={i} style={styles.tl} testID={`timeline-${i}`}>
                <Text style={styles.tlTitle}>{t.action.replace(/_/g, " ")}</Text>
                <Text style={styles.sub}>{t.by_name} · {fmt(t.at)}</Text>
                {detail(t.details) ? <Text style={styles.sub}>{detail(t.details)}</Text> : null}
              </View>
            ))}
          </Panel>
          <Panel title="Audit log (views, edits, exports, downloads)" style={styles.col}>
            {(auditQ.data?.items ?? []).slice(0, 80).map((a: any) => (
              <View key={a.id} style={styles.tl}>
                <Text style={styles.tlTitle}>{a.action.replace(/_/g, " ")}</Text>
                <Text style={styles.sub}>{a.user_name} ({a.user_role}) · {fmt(a.created_at)} · IP {a.ip ?? "—"}</Text>
              </View>
            ))}
          </Panel>
        </View>
      ) : null}

      {tab === "Export History" ? (
        <DataTable testID="exports-table" rows={auditQ.data?.exports ?? []} empty="No exports or downloads yet." columns={[
          { key: "created_at", label: "Date & Time", width: 180, render: (a) => <Text>{fmt(a.created_at)}</Text> },
          { key: "action", label: "Action", width: 170, render: (a) => <Text>{a.action === "report_exported" ? `Export (${a.details?.format ?? ""})` : "Evidence download"}</Text> },
          { key: "user_name", label: "User", width: 170 },
          { key: "user_role", label: "Role", width: 120 },
          { key: "details", label: "Details", width: 260, render: (a) => <Text>{detail(a.details)}</Text> },
        ]} />
      ) : null}

      <PopupModal visible={!!action} title={action === "return" ? "Return for Correction" : `Confirm: ${action ?? ""}`} onClose={() => setAction(null)}>
        {action === "return" ? <Banner tone="warning" message="Correction comments are mandatory when returning a report." /> : null}
        <TextField label={action === "return" ? "Correction comments (mandatory)" : "Comments (optional)"} value={comment} onChange={setComment} multiline testID="review-comment-input" />
        <Btn label="Confirm" onPress={doReview} loading={busy} disabled={action === "return" && !comment.trim()} testID="review-confirm-btn" full />
      </PopupModal>

      <PopupModal visible={assignOpen} title={c.assigned_agent_id ? "Reassign case" : "Assign case"} onClose={() => setAssignOpen(false)}>
        <SelectField label="Field agent" value={agentsQ.data?.items.find((a: any) => a.id === agentId)?.name}
          options={(agentsQ.data?.items ?? []).filter((a: any) => !a.disabled).map((a: any) => a.name)}
          onChange={(v) => setAgentId(agentsQ.data?.items.find((a: any) => a.name === v)?.id ?? "")} testID="assign-agent-select" />
        <TextField label="Reason (recorded in timeline)" value={reason} onChange={setReason} testID="assign-reason-input" />
        <Btn label="Confirm" onPress={doAssign} loading={busy} disabled={!agentId} testID="assign-confirm-btn" full />
      </PopupModal>

      <Modal visible={!!photo} transparent animationType="fade" onRequestClose={() => setPhoto(null)}>
        <Pressable style={styles.overlay} onPress={() => setPhoto(null)} testID="photo-modal">
          {photo ? <Image source={{ uri: fileUrl(photo, token) }} style={{ width: "90%", height: "90%" }} contentFit="contain" /> : null}
        </Pressable>
      </Modal>
    </Page>
  );
}

const useStyles = makeStyles((colors) => ({
  back: { color: colors.info, fontWeight: "700", fontSize: 15 },
  titleRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, flexWrap: "wrap", marginBottom: spacing.md },
  title: { fontSize: 24, fontWeight: "800", color: colors.onSurface },
  sub: { color: colors.muted, fontSize: 13, marginTop: 2 },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.lg, padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  tabs: { flexDirection: "row", flexWrap: "wrap", borderBottomWidth: 1, borderBottomColor: colors.border, marginBottom: spacing.lg },
  tab: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 3, borderBottomColor: "transparent" },
  tabActive: { borderBottomColor: colors.brandPrimary },
  tabText: { color: colors.muted, fontWeight: "700", fontSize: 14 },
  tabTextActive: { color: colors.brandPrimary },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.lg },
  col: { flexGrow: 1, flexBasis: 440, minWidth: 0 },
  gallery: { flexDirection: "row", flexWrap: "wrap", gap: spacing.lg },
  evCard: { width: 230, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md },
  evImg: { width: "100%", height: 160, borderRadius: radius.sm, backgroundColor: colors.surfaceTertiary, marginBottom: spacing.sm },
  evTitle: { fontWeight: "800", color: colors.onSurface, textTransform: "capitalize" },
  tl: { paddingVertical: 8, borderTopWidth: 1, borderTopColor: colors.divider },
  tlTitle: { fontWeight: "700", color: colors.onSurface, textTransform: "capitalize", fontSize: 14 },
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.88)", alignItems: "center", justifyContent: "center" },
}));
