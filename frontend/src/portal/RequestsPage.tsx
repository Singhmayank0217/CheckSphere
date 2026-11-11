import { useState } from "react";
import { Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { API_URL, api } from "@/src/api";
import { SelectField, TextField } from "@/src/components/fields";
import { Banner, Btn, PopupModal, showToast } from "@/src/components/ui";
import { DataTable } from "@/src/portal/DataTable";
import { Page } from "@/src/portal/Page";
import { PageHeader } from "@/src/portal/Shell";
import { useSession } from "@/src/session";
import { makeStyles, spacing } from "@/src/theme";

const EDIT = ["applicant_name", "co_applicant_name", "seller_name", "primary_phone", "alt_phone", "client_name", "branch_name", "bank_state", "full_address", "pincode", "verification_state", "city", "notes"];
const LABEL: Record<string, string> = { sent_for_allocation: "Sent for Allocation", under_review: "Under Review", clarification: "Clarification", assigned: "Assigned", rejected: "Rejected", cancelled: "Cancelled", duplicate: "Duplicate" };

export default function RequestsPage() {
  const qc = useQueryClient();
  const { token } = useSession();
  const styles = useStyles();
  const q = useQuery({ queryKey: ["case-requests"], queryFn: () => api<any>("/requests") });
  const agentsQ = useQuery({ queryKey: ["agents"], queryFn: () => api<any>("/users?role=agent") });
  const [sel, setSel] = useState<any>(null);
  const [form, setForm] = useState<any>({});
  const [comment, setComment] = useState("");
  const [agentId, setAgentId] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const open = (r: any) => { setSel(r); setForm(Object.fromEntries(EDIT.map((k) => [k, r[k] ?? ""]))); setComment(""); setAgentId(""); setDue(""); };
  const act = async (action: string, extra: any = {}) => {
    setBusy(true);
    try {
      await api(`/requests/${sel.id}/action`, { method: "POST", body: { action, comment, ...extra } });
      showToast(action === "approve" ? "Request approved and case allocated" : action === "edit" ? "Corrections saved" : "Request updated", "success"); qc.invalidateQueries({ queryKey: ["case-requests"] }); qc.invalidateQueries({ queryKey: ["admin-cases"] });
      if (action !== "edit") setSel(null);
    } catch (e: any) { showToast(e?.data?.problems?.join("; ") ?? e?.message ?? "Failed", "error"); } finally { setBusy(false); }
  };
  const closed = sel && ["assigned", "rejected", "cancelled", "duplicate"].includes(sel.status);
  return (
    <Page testID="portal-requests">
      <PageHeader title="Case Requests" subtitle="Verification requests raised by field agents, awaiting review and allocation" />
      <DataTable testID="requests-table" rows={q.data?.items ?? []} loading={q.isLoading} onRowPress={open} empty="No case requests." columns={[
        { key: "submitted_at", label: "Submitted", width: 160, render: (r) => <Text>{r.submitted_at ? new Date(r.submitted_at).toLocaleString() : "—"}</Text> },
        { key: "requested_by_name", label: "Submitted By", width: 140 },
        { key: "supervisor_name", label: "Sent To Supervisor", width: 150 },
        { key: "request_type", label: "Verification Type", width: 170 },
        { key: "name", label: "Applicant / Co-app / Seller", width: 190, render: (r) => <Text>{[r.applicant_name, r.co_applicant_name, r.seller_name].filter(Boolean).join(" / ")}</Text> },
        { key: "primary_phone", label: "Contact", width: 130 },
        { key: "client_name", label: "Client / Bank", width: 150 },
        { key: "branch_name", label: "Branch", width: 140 },
        { key: "bank_state", label: "Bank State", width: 120 },
        { key: "full_address", label: "Full Address", width: 220 },
        { key: "pincode", label: "Pincode", width: 90 },
        { key: "verification_state", label: "State of Verification", width: 150 },
        { key: "priority", label: "Priority", width: 90, render: (r) => <Text>{r.priority === "Urgent" ? "High" : "Medium"}</Text> },
        { key: "assigned_agent_name", label: "Assigned Agent", width: 140 },
        { key: "status", label: "Status / Actions", width: 160, render: (r) => <Btn label={`${LABEL[r.status] ?? r.status} · Review`} small variant="secondary" onPress={() => open(r)} testID={`review-request-${r.id}`} /> },
      ]} />
      <PopupModal wide visible={!!sel} title={`${sel?.request_type ?? ""} — ${LABEL[sel?.status] ?? ""}`} onClose={() => setSel(null)}>
        <View style={{ maxHeight: 520 }}>
          <Text style={styles.meta}>By {sel?.requested_by_name}{sel?.supervisor_name ? ` · sent to ${sel.supervisor_name}` : ""} · {(sel?.documents ?? []).map((d: any) => d.filename).join(", ")}</Text>
          {(sel?.documents ?? []).map((d: any) => (
            <Text key={d.id} style={styles.link} onPress={() => typeof window !== "undefined" && window.open(`${API_URL}/api/requests/${sel.id}/document/${d.id}?token=${token}`, "_blank")} testID={`request-doc-${d.id}`}>Open document: {d.filename}</Text>
          ))}
          <View style={{ flexDirection: "row", flexWrap: "wrap", columnGap: spacing.md }}>
            {EDIT.map((k) => <View key={k} style={{ flexBasis: 200, flexGrow: 1 }}><TextField label={k.replace(/_/g, " ")} value={form[k]} onChange={(v) => setForm({ ...form, [k]: v })} editable={!closed} testID={`req-edit-${k}`} /></View>)}
          </View>
          {!closed ? (
            <>
              <Btn label="Save Corrections" variant="secondary" small loading={busy} onPress={() => act("edit", { data: form })} testID="req-save-edit-btn" />
              <View style={{ flexDirection: "row", gap: spacing.md, flexWrap: "wrap", marginTop: spacing.md }}>
                <View style={{ flexBasis: 220, flexGrow: 1 }}>
                  <SelectField label="Allocate to agent *" value={agentsQ.data?.items.find((a: any) => a.id === agentId)?.name} options={(agentsQ.data?.items ?? []).filter((a: any) => !a.disabled).map((a: any) => `${a.name}${a.id === sel?.requested_by ? " (requester)" : ""}`)} onChange={(v) => setAgentId(agentsQ.data?.items.find((a: any) => a.name === v.replace(" (requester)", ""))?.id ?? "")} testID="req-agent-select" />
                </View>
                <View style={{ flexBasis: 200, flexGrow: 1 }}><TextField label="SLA due (YYYY-MM-DDTHH:MM, blank = 48h)" value={due} onChange={setDue} testID="req-due-input" /></View>
              </View>
              <TextField label="Comment / reason (required for reject & clarification)" value={comment} onChange={setComment} multiline testID="req-comment-input" />
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
                <Btn label="Approve & Allocate" small loading={busy} disabled={!agentId} onPress={() => act("approve", { agent_id: agentId, due_at: due || null, data: form })} testID="req-approve-btn" />
                <Btn label="Request Clarification" small variant="secondary" onPress={() => act("clarify")} testID="req-clarify-btn" />
                <Btn label="Reject" small variant="danger" onPress={() => act("reject")} testID="req-reject-btn" />
                <Btn label="Mark Duplicate" small variant="secondary" onPress={() => act("duplicate")} testID="req-duplicate-btn" />
                <Btn label="Escalate to Super Admin" small variant="ghost" onPress={() => act("escalate")} testID="req-escalate-btn" />
              </View>
            </>
          ) : <Banner tone="info" message={sel?.internal_case_id ? `Converted to ${sel.internal_case_id}, allocated to ${sel.assigned_agent_name} by ${sel.approved_by}.` : "This request is closed."} />}
        </View>
      </PopupModal>
    </Page>
  );
}

const useStyles = makeStyles((colors) => ({
  meta: { color: colors.muted, marginBottom: spacing.sm },
  link: { color: colors.info, fontWeight: "700", marginBottom: spacing.sm },
}));
