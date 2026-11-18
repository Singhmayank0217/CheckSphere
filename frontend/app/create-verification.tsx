// Agent "Create New Verification".
// Step 1: choose the Request Type (the SAME dropdown and options as Allocate New Verification).
// Step 2: the SAME assigned-case verification form (app/report/[caseId].tsx, ReportScreen) opens for that type.
// Choosing or changing the Request Type does NOT create a case. "Continue" only opens a private draft workspace
// (no Internal Case ID, not visible in any case list) so photos/GPS/draft saves have a home. The backend creates the
// case and generates its unique Internal Case ID only when the agent presses the final "Submit Report".
import { useState } from "react";
import { Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { SelectField } from "@/src/components/fields";
import { BackHeader, Banner, Btn, Card, showToast } from "@/src/components/ui";
import { RoleGate } from "@/src/portal/RoleGate";
import { fmtIST } from "@/src/utils/geo";
import { makeStyles, spacing } from "@/src/theme";
import { TYPES } from "./request-new";

const newKey = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

function CreateVerificationScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const qc = useQueryClient();
  const styles = useStyles();
  const [requestType, setRequestType] = useState("");
  const [busy, setBusy] = useState(false);
  const [draftKey] = useState(newKey); // one key per visit: a double tap / retry reopens the same draft
  const draftsQ = useQuery({ queryKey: ["agent-drafts"], queryFn: () => api<{ items: any[] }>("/agent/verification-drafts") });
  const drafts = draftsQ.data?.items ?? [];

  const start = async () => {
    if (!requestType) {
      showToast("Choose a request type", "error");
      return;
    }
    if (busy) return;
    setBusy(true);
    try {
      const c = await api<any>("/cases/agent-create", { method: "POST", body: { request_type: requestType, draft_key: draftKey } });
      qc.invalidateQueries({ queryKey: ["agent-drafts"] });
      showToast("Complete the form — the case is created when you press Submit", "success");
      router.replace(`/report/${c.id}`);
    } catch (e: any) {
      showToast(e?.message ?? "Could not open the verification form", "error");
    } finally {
      setBusy(false);
    }
  };

  const discard = async (id: string) => {
    try {
      await api(`/cases/${id}/discard`, { method: "POST" });
      qc.invalidateQueries({ queryKey: ["agent-drafts"] });
      showToast("Draft discarded", "success");
    } catch (e: any) {
      showToast(e?.message ?? "Could not discard the draft", "error");
    }
  };

  return (
    <View style={[styles.root, { paddingTop: insets.top + spacing.sm, paddingHorizontal: spacing.lg }]} testID="create-verification-screen">
      <BackHeader title="Create New Verification" testID="create-verification-back-btn" />
      <Banner tone="info" message="Choose the request type to open the full verification form. No case is created until you complete the form and press Submit Report." />
      <Card>
        <SelectField label="Request type *" value={requestType} options={TYPES} onChange={setRequestType} testID="req-type-select" />
        <Text style={styles.help}>You will fill in the applicant details, visit details, findings, five photos and GPS exactly as for an assigned case. The Internal Case ID is generated automatically on submission.</Text>
        <Btn label="Continue to Verification Form" onPress={start} loading={busy} disabled={!requestType || busy} testID="create-verification-start-btn" full />
      </Card>
      {drafts.length ? (
        <Card>
          <Text style={styles.heading}>Unfinished verifications (not submitted)</Text>
          {drafts.map((d) => (
            <View key={d.id} style={styles.draftRow} testID={`draft-${d.id}`}>
              <Text style={styles.draftTitle}>{d.request_type}{d.applicant_name ? ` · ${d.applicant_name}` : ""}</Text>
              <Text style={styles.help}>Started {fmtIST(d.created_at)} · {d.photo_count ?? 0} photo(s)</Text>
              <View style={styles.draftActions}>
                <Btn label="Resume" small onPress={() => router.push(`/report/${d.id}`)} testID={`draft-resume-${d.id}`} />
                <Btn label="Discard" small variant="secondary" onPress={() => discard(d.id)} testID={`draft-discard-${d.id}`} />
              </View>
            </View>
          ))}
        </Card>
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  help: { color: colors.muted, fontSize: 13, marginBottom: spacing.md },
  heading: { color: colors.onSurface, fontWeight: "800", fontSize: 15, marginBottom: spacing.sm },
  draftRow: { borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: spacing.sm, marginTop: spacing.xs },
  draftTitle: { color: colors.onSurface, fontWeight: "700" },
  draftActions: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.sm },
}));

export default function CreateVerification() {
  return <RoleGate role="agent"><CreateVerificationScreen /></RoleGate>;
}
