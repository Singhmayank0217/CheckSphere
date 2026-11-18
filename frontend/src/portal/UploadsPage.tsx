// Supervisor / Super Admin: cases uploaded by agents (details + PDF). Reviewing a submission never creates or
// approves a verification case by itself; create one with "Create New Case" when appropriate.
import { useState } from "react";
import { Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { API_URL, api } from "@/src/api";
import { TextField } from "@/src/components/fields";
import { Banner, Btn, DisplayRow, PopupModal, showToast } from "@/src/components/ui";
import { DataTable } from "@/src/portal/DataTable";
import { Page } from "@/src/portal/Page";
import { PageHeader } from "@/src/portal/Shell";
import { useSession } from "@/src/session";
import { fmtIST } from "@/src/utils/geo";
import { makeStyles, spacing } from "@/src/theme";

export default function UploadsPage() {
  const qc = useQueryClient();
  const { token } = useSession();
  const styles = useStyles();
  const q = useQuery({ queryKey: ["case-uploads"], queryFn: () => api<any>("/case-uploads") });
  const [sel, setSel] = useState<any>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const closed = sel && ["accepted", "rejected"].includes(sel.status);

  const act = async (action: string) => {
    setBusy(true);
    try {
      const updated = await api<any>(`/case-uploads/${sel.id}/action`, { method: "POST", body: { action, comment } });
      showToast(`Submission ${updated.status_label.toLowerCase()}`, "success");
      qc.invalidateQueries({ queryKey: ["case-uploads"] });
      setSel(null);
    } catch (e: any) {
      showToast(e?.message ?? "Failed", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Page testID="portal-uploads">
      <PageHeader title="Uploaded Cases" subtitle="New case details and PDFs submitted by field agents" />
      <DataTable testID="uploads-table" rows={q.data?.items ?? []} loading={q.isLoading} onRowPress={(r) => { setSel(r); setComment(""); }}
        empty="No uploaded cases." columns={[
          { key: "submitted_at", label: "Submitted", width: 190, render: (r) => <Text>{fmtIST(r.submitted_at)}</Text> },
          { key: "submitted_by_name", label: "Agent", width: 150, render: (r) => <Text>{r.submitted_by_name}{r.submitted_by_agent_id ? ` (${r.submitted_by_agent_id})` : ""}</Text> },
          { key: "state", label: "State", width: 140 },
          { key: "branch_name", label: "Branch", width: 150 },
          { key: "applicant_name", label: "Applicant", width: 160 },
          { key: "co_applicant_name", label: "Co-applicant", width: 150 },
          { key: "co_applicant2_name", label: "2nd Co-applicant", width: 150 },
          { key: "status", label: "Status / Actions", width: 190, render: (r) => <Btn label={`${r.status_label} · Review`} small variant="secondary" onPress={() => { setSel(r); setComment(""); }} testID={`review-upload-${r.id}`} /> },
        ]} />
      <PopupModal wide visible={!!sel} title={`Uploaded case — ${sel?.status_label ?? ""}`} onClose={() => setSel(null)}>
        <View style={{ maxHeight: 540 }}>
          <DisplayRow label="Agent" value={`${sel?.submitted_by_name ?? ""}${sel?.submitted_by_agent_id ? ` (${sel.submitted_by_agent_id})` : ""}`} />
          <DisplayRow label="Submitted" value={fmtIST(sel?.submitted_at)} />
          <DisplayRow label="State" value={sel?.state} />
          <DisplayRow label="Branch Name" value={sel?.branch_name} />
          <DisplayRow label="Applicant Name" value={sel?.applicant_name} />
          <DisplayRow label="Co-applicant Name" value={sel?.co_applicant_name} />
          <DisplayRow label="Second Co-applicant Name" value={sel?.co_applicant2_name || "—"} />
          <DisplayRow label="Requirements" value={sel?.requirements || "—"} />
          {sel?.pdf?.available ? (
            <Text style={styles.link} testID="upload-open-pdf"
              onPress={() => typeof window !== "undefined" && window.open(`${API_URL}/api/case-uploads/${sel.id}/pdf?token=${token}`, "_blank")}>
              Open PDF: {sel.pdf.filename}
            </Text>
          ) : <Text style={styles.meta}>PDF not available</Text>}
          {(sel?.comments ?? []).map((c: any, i: number) => <Text key={i} style={styles.meta}>{c.by} ({c.action}): {c.text}</Text>)}
          {!closed ? (
            <>
              <TextField label="Comment / reason (required to reject or ask for clarification)" value={comment} onChange={setComment} multiline testID="upload-comment-input" />
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
                <Btn label="Mark Under Review" small variant="secondary" loading={busy} onPress={() => act("review")} testID="upload-review-btn" />
                <Btn label="Accept" small loading={busy} onPress={() => act("accept")} testID="upload-accept-btn" />
                <Btn label="Request Clarification" small variant="secondary" loading={busy} onPress={() => act("clarify")} testID="upload-clarify-btn" />
                <Btn label="Reject" small variant="danger" loading={busy} onPress={() => act("reject")} testID="upload-reject-btn" />
              </View>
              <Text style={styles.meta}>Accepting records the decision only; it does not create or approve a verification case.</Text>
            </>
          ) : <Banner tone="info" message={`This submission is ${sel?.status_label?.toLowerCase()}${sel?.reviewed_by_name ? ` by ${sel.reviewed_by_name}` : ""}.`} />}
        </View>
      </PopupModal>
    </Page>
  );
}

const useStyles = makeStyles((colors) => ({
  meta: { color: colors.muted, marginTop: spacing.sm },
  link: { color: colors.info, fontWeight: "700", marginVertical: spacing.sm },
}));
