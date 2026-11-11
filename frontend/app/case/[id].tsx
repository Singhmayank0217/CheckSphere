import { useQuery } from "@tanstack/react-query";
import { Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { MiniMap } from "@/src/components/MiniMap";
import { Banner, BackHeader, Btn, Card, DisplayRow, ErrorBox, FLAG_LABELS, Loading, Screen, SectionTitle, StatusPill } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { makeStyles, spacing } from "@/src/theme";

export default function CaseDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useSession();
  const router = useRouter();
  const styles = useStyles();

  const caseQ = useQuery({
    queryKey: ["case", id],
    queryFn: () => api<any>(`/cases/${id}`),
    enabled: !!id,
  });

  if (caseQ.isLoading) return <Screen><Loading label="Loading verification parameters…" /></Screen>;
  if (caseQ.isError || !caseQ.data) return <Screen><ErrorBox message="Failed to retrieve case details." onRetry={() => caseQ.refetch()} /></Screen>;

  const c = caseQ.data;
  const gps = c.last_gps?.lat ? c.last_gps : c.assigned_lat ? { lat: c.assigned_lat, lon: c.assigned_lon, accuracy: null } : null;
  const canVerify = user?.role === "agent" && ["new", "assigned", "in_progress", "returned"].includes(c.status);

  return (
    <Screen testID="case-detail-screen">
      <BackHeader title="Case Details" testID="case-detail-back-btn" />
      <Card>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <Text style={styles.caseId}>{c.internal_case_id}</Text>
          <StatusPill status={c.status} testID="case-detail-status" />
        </View>
        <DisplayRow label="Applicant" value={c.applicant_name} />
        {c.co_applicant_name ? <DisplayRow label="Co-applicant" value={c.co_applicant_name} /> : null}
        <DisplayRow label="Client" value={c.client_name} />
        <DisplayRow label="Branch" value={c.branch_name} />
        <DisplayRow label="Client Case ID" value={c.client_case_id} />
        <DisplayRow label="Loan / Product" value={c.loan_type} />
        <DisplayRow label="Verification Type" value={c.report_type_name || c.report_type} />
        <DisplayRow label="Priority" value={c.priority} />
        <DisplayRow label="Due" value={c.due_at ? new Date(c.due_at).toLocaleString() : "-"} />
      </Card>

      <Card>
        <SectionTitle>Assigned Address</SectionTitle>
        <Text style={styles.address}>{c.assigned_address}</Text>
        <DisplayRow label="City" value={c.city} />
        <DisplayRow label="State" value={c.state} />
      </Card>

      {(c.flags ?? []).length > 0 ? (
        <Banner tone="warning" message={`Supervisor flags: ${c.flags.map((f: string) => FLAG_LABELS[f] ?? f).join(", ")}`} />
      ) : null}

      {c.status === "returned" && c.latest_report?.review_comment ? (
        <Banner tone="error" message={`Returned for correction: ${c.latest_report.review_comment}`} />
      ) : null}

      {gps ? (
        <Card>
          <SectionTitle>Location</SectionTitle>
          <MiniMap lat={gps.lat} lon={gps.lon} accuracy={gps.accuracy} testID="case-map" />
        </Card>
      ) : null}

      <View style={{ height: 96 }} />
      {canVerify ? (
        <View style={[styles.cta, { paddingBottom: 16 }]}>
          <Btn
            label={c.status === "returned" ? "Correct & Resubmit Report" : c.latest_report?.status === "draft" ? "Continue Verification" : "Start Verification"}
            onPress={() => router.push(`/report/${id}`)}
            testID="start-verification-btn"
            full
          />
        </View>
      ) : (
        <View style={[styles.cta, { paddingBottom: 16 }]}>
          <Btn label="View Report" variant="secondary" onPress={() => router.push(`/report/${id}`)} testID="view-report-btn" full />
        </View>
      )}
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  caseId: { fontSize: 20, fontWeight: "800", color: colors.onSurface, flex: 1, fontFamily: "PlusJakartaSans" },
  address: { color: colors.onSurface, fontSize: 14, lineHeight: 20, marginBottom: 8 },
  cta: { position: "absolute", left: spacing.lg, right: spacing.lg, bottom: 24 },
}));
