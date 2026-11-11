import { useState } from "react";
import { Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/src/api";
import { SelectField, TextField } from "@/src/components/fields";
import { Banner, Btn, DisplayRow, PopupModal, showToast } from "@/src/components/ui";
import { DataTable } from "@/src/portal/DataTable";
import { Page, Panel } from "@/src/portal/Page";
import { PageHeader } from "@/src/portal/Shell";
import { spacing } from "@/src/theme";

const fmt = (d?: string) => (d ? new Date(d).toLocaleString() : "—");

export function SecurityPage() {
  const qc = useQueryClient();
  const sessQ = useQuery({ queryKey: ["all-sessions"], queryFn: () => api<any>("/sessions") });
  const incQ = useQuery({ queryKey: ["incidents"], queryFn: () => api<any>("/incidents") });
  const [inc, setInc] = useState({ title: "", severity: "Medium", description: "" });
  const act = async (fn: () => Promise<any>, msg: string) => {
    try { await fn(); showToast(msg, "success"); qc.invalidateQueries({ queryKey: ["all-sessions"] }); qc.invalidateQueries({ queryKey: ["incidents"] }); }
    catch (e: any) { showToast(e?.message ?? "Failed", "error"); }
  };
  return (
    <Page testID="portal-security">
      <PageHeader title="Security and Sessions" subtitle="Active logins across all users, remote logout, and the incident / breach log" />
      <Panel title={`Active sessions (${sessQ.data?.items?.length ?? 0})`}>
        <DataTable testID="sessions-table" rows={sessQ.data?.items ?? []} loading={sessQ.isLoading} empty="No active sessions." columns={[
          { key: "user_name", label: "User", width: 170 },
          { key: "user_role", label: "Role", width: 120 },
          { key: "device_model", label: "Device", width: 170, render: (s) => <Text>{s.device_model || "Unknown"}{"\n"}{String(s.device_id ?? "").slice(0, 12)}</Text> },
          { key: "ip", label: "IP", width: 130 },
          { key: "created_at", label: "Signed In", width: 170, render: (s) => <Text>{fmt(s.created_at)}</Text> },
          { key: "last_seen_at", label: "Last Seen", width: 170, render: (s) => <Text>{fmt(s.last_seen_at)}</Text> },
          { key: "actions", label: "", width: 120, render: (s) => <Btn label="Log out" variant="danger" small onPress={() => act(() => api(`/auth/sessions/${s.id}/revoke`, { method: "POST" }), "Session revoked")} testID={`revoke-${s.id}`} /> },
        ]} />
      </Panel>
      <Panel title="Incident / breach log">
        <View style={{ flexDirection: "row", gap: spacing.md, flexWrap: "wrap", alignItems: "flex-end" }}>
          <View style={{ flexBasis: 280, flexGrow: 1 }}><TextField label="Title" value={inc.title} onChange={(v) => setInc({ ...inc, title: v })} testID="incident-title-input" /></View>
          <View style={{ flexBasis: 160 }}><SelectField label="Severity" value={inc.severity} options={["Low", "Medium", "High", "Critical"]} onChange={(v) => setInc({ ...inc, severity: v })} testID="incident-severity-select" /></View>
          <View style={{ flexBasis: 360, flexGrow: 2 }}><TextField label="Description" value={inc.description} onChange={(v) => setInc({ ...inc, description: v })} testID="incident-desc-input" /></View>
          <View style={{ marginBottom: spacing.md }}><Btn label="Log Incident" disabled={!inc.title} testID="incident-submit-btn" onPress={() => act(async () => { await api("/incidents", { method: "POST", body: inc }); setInc({ title: "", severity: "Medium", description: "" }); }, "Incident logged")} /></View>
        </View>
        <DataTable testID="incidents-table" rows={incQ.data?.items ?? []} empty="No incidents recorded." columns={[
          { key: "created_at", label: "Reported", width: 170, render: (i) => <Text>{fmt(i.created_at)}</Text> },
          { key: "title", label: "Title", width: 220 },
          { key: "severity", label: "Severity", width: 100 },
          { key: "description", label: "Description", width: 300 },
          { key: "reported_by", label: "By", width: 140 },
          { key: "status", label: "Status", width: 160, render: (i) => i.status === "Open" ? <Btn label="Close" variant="secondary" small onPress={() => act(() => api(`/incidents/${i.id}/close`, { method: "POST" }), "Incident closed")} testID={`close-incident-${i.id}`} /> : <Text>Closed {fmt(i.closed_at)}</Text> },
        ]} />
      </Panel>
    </Page>
  );
}

export function BackupPage() {
  const qc = useQueryClient();
  const bQ = useQuery({ queryKey: ["backups"], queryFn: () => api<any>("/backups") });
  const rQ = useQuery({ queryKey: ["retention"], queryFn: () => api<any>("/retention/preview") });
  const sQ = useQuery({ queryKey: ["settings"], queryFn: () => api<any>("/settings") });
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const run = async (fn: () => Promise<any>, msg: string) => {
    setBusy(true);
    try { await fn(); showToast(msg, "success"); qc.invalidateQueries({ queryKey: ["backups"] }); qc.invalidateQueries({ queryKey: ["retention"] }); }
    catch (e: any) { showToast(e?.message ?? "Failed", "error"); } finally { setBusy(false); }
  };
  return (
    <Page testID="portal-backup">
      <PageHeader title="Backup and Retention" subtitle="Daily automatic backups to private storage and secure deletion after the retention period" />
      <Panel title="Backups" right={<Btn label="Run Backup Now" small loading={busy} onPress={() => run(() => api("/backups/run", { method: "POST" }), "Backup completed")} testID="backup-run-btn" />}>
        <Text style={{ color: "#73706A", marginBottom: spacing.md }}>An automatic backup runs every 24 hours. Password hashes are excluded.</Text>
        <DataTable testID="backups-table" rows={bQ.data?.items ?? []} loading={bQ.isLoading} empty="No backups yet." columns={[
          { key: "created_at", label: "Created", width: 190, render: (b) => <Text>{fmt(b.created_at)}</Text> },
          { key: "trigger", label: "Trigger", width: 110 },
          { key: "size", label: "Size", width: 110, render: (b) => <Text>{Math.round(b.size / 1024)} KB</Text> },
          { key: "counts", label: "Records", width: 360, render: (b) => <Text numberOfLines={2}>{Object.entries(b.counts ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}</Text> },
        ]} />
      </Panel>
      <Panel title="Document retention">
        <DisplayRow label="Retention period" value={`${sQ.data?.retention_days ?? "—"} days (change in Settings)`} />
        <DisplayRow label="Cutoff date" value={fmt(rQ.data?.cutoff)} />
        <DisplayRow label="Closed cases eligible for purge" value={rQ.data?.eligible_cases ?? 0} />
        <View style={{ height: spacing.md }} />
        <Btn label="Run Secure Deletion" variant="danger" disabled={!rQ.data?.eligible_cases} onPress={() => setConfirm(true)} testID="retention-run-btn" />
        {(rQ.data?.last_runs ?? []).map((r: any) => <DisplayRow key={r.id} label={fmt(r.created_at)} value={`${r.cases} cases · ${r.evidence} evidence files purged by ${r.by}`} />)}
      </Panel>
      <PopupModal visible={confirm} title="Confirm secure deletion" onClose={() => setConfirm(false)}>
        <Banner tone="error" message="Evidence files for closed cases older than the retention period will be permanently removed. Case records and the audit trail are kept." />
        <Btn label="Delete Evidence Permanently" variant="danger" loading={busy} full testID="retention-confirm-btn" onPress={async () => { await run(() => api("/retention/run", { method: "POST" }), "Retention purge completed"); setConfirm(false); }} />
      </PopupModal>
    </Page>
  );
}
