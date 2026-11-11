import { useState } from "react";
import { Text, View } from "react-native";
import * as DocumentPicker from "expo-document-picker";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api } from "@/src/api";
import { SelectField, SwitchRow, TextField } from "@/src/components/fields";
import { BackHeader, Banner, Btn, Card, SectionTitle, StatusPill, showToast } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { uploadForm } from "@/src/utils/upload";
import { RoleGate } from "@/src/portal/RoleGate";
import { makeStyles, spacing } from "@/src/theme";

const TYPES = ["Residence Verification", "Office Verification", "Business Verification", "Telephone Verification", "Income Verification", "KYC Verification", "Seller Verification", "Other"];
const LABELS: Record<string, string> = { draft: "Draft", sent_for_allocation: "Sent for Allocation", under_review: "Under Review", clarification: "Clarification Requested", assigned: "Assigned", rejected: "Rejected", cancelled: "Cancelled", duplicate: "Duplicate" };
const EMPTY: Record<string, string> = { request_type: "", applicant_name: "", co_applicant_name: "", seller_name: "", primary_phone: "", alt_phone: "", client_name: "", branch_name: "", bank_state: "", full_address: "", pincode: "", verification_state: "", city: "", notes: "", priority: "Normal", supervisor_id: "" };

function RequestNewScreen() {
  const insets = useSafeAreaInsets();
  const { token } = useSession();
  const qc = useQueryClient();
  const styles = useStyles();
  const [d, setD] = useState({ ...EMPTY });
  const [decl, setDecl] = useState(false);
  const [doc, setDoc] = useState<any>(null);
  const [errs, setErrs] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [draftId, setDraftId] = useState<string | null>(null);
  const listQ = useQuery({ queryKey: ["my-requests"], queryFn: () => api<any>("/requests") });
  const supQ = useQuery({ queryKey: ["request-supervisors"], queryFn: () => api<any>("/requests/supervisors") });
  const sups: any[] = supQ.data?.items ?? [];
  const set = (k: string) => (v: string) => setD((p) => ({ ...p, [k]: v }));

  const pick = async () => {
    const r = await DocumentPicker.getDocumentAsync({ type: ["image/*", "application/pdf"], copyToCacheDirectory: true });
    if (!r.canceled && r.assets?.[0]) setDoc(r.assets[0]);
  };
  const submit = async () => {
    const e: string[] = [];
    if (!d.request_type) e.push("Choose a request type");
    if (!d.applicant_name && !d.co_applicant_name && !d.seller_name) e.push("Enter at least one of Applicant, Co-applicant or Seller name");
    if (!d.primary_phone) e.push("Primary contact number is required");
    if (!d.branch_name) e.push("Branch name is required");
    if (!d.full_address) e.push("Full address is required");
    if (!/^\d{6}$/.test(d.pincode)) e.push("Pincode must be 6 digits");
    if (!doc) e.push("Supporting document upload is mandatory");
    if (!d.supervisor_id) e.push("Choose the supervisor to send this request to");
    if (!decl) e.push("Accept the agent declaration");
    setErrs(e);
    if (e.length) { showToast(e[0], "error"); return; }
    setBusy(true);
    try {
      let id = draftId;
      if (!id) {
        const r = await api<any>("/requests", { method: "POST", body: { data: d, declaration: decl } });
        id = r.id as string;
        setDraftId(id);
      }
      if (!doc.uploaded) {
        const up = await uploadForm(`${API_URL}/api/requests/${id}/document`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          files: { file: { uri: doc.uri, name: doc.name ?? "document", mimeType: doc.mimeType ?? "application/octet-stream" } },
        });
        if (!up.ok) throw new Error("Document upload failed — please try again");
        setDoc({ ...doc, uploaded: true });
      }
      await api(`/requests/${id}/submit`, { method: "POST", body: { data: d, declaration: decl } });
      showToast("Request sent for allocation", "success");
      setD({ ...EMPTY }); setDoc(null); setDecl(false); setDraftId(null);
      qc.invalidateQueries({ queryKey: ["my-requests"] });
    } catch (x: any) {
      const p = x?.data?.problems ?? [x?.message ?? "Submission failed"];
      setErrs(p);
      showToast(p[0], "error");
    } finally { setBusy(false); }
  };

  return (
    <View style={styles.root} testID="request-new-screen">
      <KeyboardAwareScrollView bottomOffset={24} keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: spacing.lg, paddingTop: insets.top + spacing.sm, paddingBottom: insets.bottom + 48 }}>
        <BackHeader title="Request New Verification" testID="request-back-btn" />
        <Banner tone="info" message="Your request goes to a Supervisor for review and allocation. It becomes an active case only after approval." />
        {errs.length ? <View style={styles.err} testID="request-errors"><Text style={styles.errText}>Please fix {errs.length} issue{errs.length > 1 ? "s" : ""} listed above the Submit button.</Text></View> : null}
        <Card>
          <SelectField label="Request type *" value={d.request_type} options={TYPES} onChange={set("request_type")} testID="req-type-select" />
          <TextField label="Applicant Name" value={d.applicant_name} onChange={set("applicant_name")} autoCapitalize="words" testID="req-applicant" />
          <TextField label="Co-applicant Name" value={d.co_applicant_name} onChange={set("co_applicant_name")} autoCapitalize="words" testID="req-coapplicant" />
          <TextField label="Seller Name" value={d.seller_name} onChange={set("seller_name")} autoCapitalize="words" testID="req-seller" />
          <TextField label="Primary Contact Number *" value={d.primary_phone} onChange={set("primary_phone")} keyboardType="phone-pad" testID="req-phone" />
          <TextField label="Alternate Phone Number" value={d.alt_phone} onChange={set("alt_phone")} keyboardType="phone-pad" testID="req-alt-phone" />
          <TextField label="Client / Bank Name" value={d.client_name} onChange={set("client_name")} autoCapitalize="words" testID="req-client" />
          <TextField label="Branch Name *" value={d.branch_name} onChange={set("branch_name")} autoCapitalize="words" testID="req-branch" />
          <TextField label="Bank State" value={d.bank_state} onChange={set("bank_state")} autoCapitalize="words" testID="req-bank-state" />
          <TextField label="Full Address *" value={d.full_address} onChange={set("full_address")} multiline autoCapitalize="sentences" testID="req-address" />
          <TextField label="Pincode *" value={d.pincode} onChange={set("pincode")} keyboardType="numeric" testID="req-pincode" />
          <TextField label="State of Verification" value={d.verification_state} onChange={set("verification_state")} autoCapitalize="words" testID="req-ver-state" />
          <TextField label="City / District" value={d.city} onChange={set("city")} autoCapitalize="words" testID="req-city" />
          <TextField label="Reason / Notes for Verification" value={d.notes} onChange={set("notes")} multiline autoCapitalize="sentences" testID="req-notes" />
          <SelectField label="Priority" value={d.priority} options={["Normal", "Urgent"]} onChange={set("priority")} testID="req-priority-select" />
          <SelectField label="Send to Supervisor *" value={sups.find((s) => s.id === d.supervisor_id)?.name} options={sups.map((s) => s.name)} onChange={(v) => set("supervisor_id")(sups.find((s) => s.name === v)?.id ?? "")} testID="req-supervisor-select" />
          <Btn label={doc ? `Document: ${doc.name}` : "Upload Supporting Document *"} variant="secondary" onPress={pick} testID="req-doc-btn" full />
          <View style={{ height: spacing.md }} />
          <SwitchRow label="I confirm these details are from an authorised source and are factual." value={decl} onChange={setDecl} testID="req-declaration" />
          {errs.length ? <View style={styles.err} testID="request-errors-bottom">{errs.map((e) => <Text key={e} style={styles.errText}>• {e}</Text>)}</View> : null}
          <Btn label="Submit Request" onPress={submit} loading={busy} testID="req-submit-btn" full />
        </Card>
        <SectionTitle>My Requests</SectionTitle>
        {(listQ.data?.items ?? []).map((r: any) => (
          <Card key={r.id} testID={`my-request-${r.id}`}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", gap: spacing.sm }}>
              <Text style={styles.name} numberOfLines={2}>{r.request_type} · {r.applicant_name || r.co_applicant_name || r.seller_name}</Text>
                <StatusPill status={r.status === "assigned" ? "approved" : ["rejected", "duplicate", "cancelled"].includes(r.status) ? "exception" : r.status === "clarification" ? "returned" : "submitted"} testID={`req-status-${r.id}`} />
            </View>
            <Text style={styles.meta} testID={`req-status-label-${r.id}`}>{LABELS[r.status] ?? r.status}{r.supervisor_name ? ` · Supervisor: ${r.supervisor_name}` : ""} · {new Date(r.created_at).toLocaleString()}{r.internal_case_id ? ` · ${r.internal_case_id} → ${r.assigned_agent_name}` : ""}</Text>
            {["sent_for_allocation", "under_review"].includes(r.status) ? <Text style={styles.pending}>Pending supervisor approval</Text> : null}
            {(r.comments ?? []).map((c: any, i: number) => <Text key={i} style={styles.comment}>{c.by}: {c.text}</Text>)}
          </Card>
        ))}
      </KeyboardAwareScrollView>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  err: { backgroundColor: colors.error, borderRadius: 12, padding: spacing.md, marginBottom: spacing.md },
  errText: { color: colors.onError, fontSize: 14, lineHeight: 20 },
  name: { flex: 1, fontWeight: "700", color: colors.onSurface, fontSize: 15 },
  meta: { color: colors.muted, fontSize: 13, marginTop: 4 },
  comment: { color: colors.warning, fontSize: 13, marginTop: 4 },
  pending: { color: colors.warning, fontSize: 13, fontWeight: "700", marginTop: 4 },
}));

export default function RequestNew() {
  return <RoleGate role="agent"><RequestNewScreen /></RoleGate>;
}
