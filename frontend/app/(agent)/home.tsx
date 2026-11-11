import { useCallback, useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useNetInfo } from "@react-native-community/netinfo";

import { api } from "@/src/api";
import { pendingCount, syncAllDrafts } from "@/src/utils/drafts";
import { Banner, Btn, Card, Empty, ErrorBox, KpiCard, Loading, Screen, SectionTitle, StatusPill, showToast } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { makeStyles, spacing, typography } from "@/src/theme";

function CaseRow({ c, onPress, testID }: { c: any; onPress: () => void; testID?: string }) {
  const styles = useStyles();
  const overdue = c.due_at && new Date(c.due_at).getTime() < Date.now() && ["new", "assigned", "in_progress", "returned"].includes(c.status);
  return (
    <Pressable onPress={onPress} testID={testID}>
      <View style={[styles.caseRow, overdue && styles.caseRowOverdue]}>
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={styles.caseName} numberOfLines={1}>
            {c.applicant_name} · {c.internal_case_id}
          </Text>
          <Text style={styles.caseMeta} numberOfLines={1}>
            {c.client_name} · {c.report_type_name || c.report_type}
          </Text>
        </View>
        <View style={{ alignItems: "flex-end", gap: 4 }}>
          <StatusPill status={c.status} testID={`case-status-${c.internal_case_id}`} />
          <Text style={overdue ? styles.overdueText : styles.caseMeta}>
            {c.due_at ? `Due ${new Date(c.due_at).toLocaleDateString()}` : "No due date"}
          </Text>
        </View>
      </View>
    </Pressable>
  );
}

export default function AgentHome() {
  const { user } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const netInfo = useNetInfo();
  const styles = useStyles();
  const [pending, setPending] = useState(0);
  const [syncing, setSyncing] = useState(false);

  const casesQ = useQuery({
    queryKey: ["agent-cases"],
    queryFn: () => api<{ items: any[]; total: number }>("/cases?limit=100"),
  });

  const refreshPending = useCallback(async () => {
    setPending(await pendingCount());
  }, []);

  useEffect(() => {
    refreshPending();
  }, [refreshPending, casesQ.dataUpdatedAt]);

  const items = casesQ.data?.items ?? [];
  const active = items.filter((c) => ["assigned", "in_progress", "returned"].includes(c.status));
  const dueToday = active.filter((c) => c.due_at && new Date(c.due_at).toDateString() === new Date().toDateString());
  const overdue = active.filter((c) => c.due_at && new Date(c.due_at).getTime() < Date.now());
  const returned = items.filter((c) => c.status === "returned");
  const submitted = items.filter((c) => ["submitted", "under_review", "approved", "exported"].includes(c.status));
  const needsAttention = [...overdue, ...dueToday, ...returned].filter(
    (v, i, a) => a.findIndex((x) => x.id === v.id) === i,
  ).slice(0, 8);

  const onSync = async () => {
    setSyncing(true);
    try {
      const n = await syncAllDrafts();
      await refreshPending();
      queryClient.invalidateQueries({ queryKey: ["agent-cases"] });
      showToast(n > 0 ? `${n} offline draft${n > 1 ? "s" : ""} synced` : "All drafts already synced", "success");
    } catch {
      showToast("Sync failed — will retry when online", "error");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <Screen>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View>
          <Text style={styles.hello}>Hello, {user?.name?.split(" ")[0] ?? "Agent"}</Text>
          <Text style={styles.agentId}>Agent ID: {user?.agent_id ?? "-"}</Text>
        </View>
        <View style={[styles.syncBadge, pending > 0 ? styles.syncPending : styles.syncOk]} testID="sync-badge">
          <Text style={pending > 0 ? styles.syncPendingText : styles.syncOkText}>
            {netInfo.isConnected === false ? "Offline" : pending > 0 ? `${pending} pending sync` : "All synced"}
          </Text>
        </View>
      </View>

      {pending > 0 ? (
        <View style={{ marginTop: spacing.md }}>
          <Banner
            tone="warning"
            message={`${pending} encrypted offline draft${pending > 1 ? "s" : ""} on this device waiting to sync.`}
          />
          <Btn label="Sync Now" onPress={onSync} loading={syncing} testID="sync-now-btn" small />
        </View>
      ) : null}

      <View style={{ flexDirection: "row", flexWrap: "wrap", marginHorizontal: -spacing.xs, marginTop: spacing.md }}>
        <KpiCard label="Active Cases" value={active.length} testID="kpi-active" />
        <KpiCard label="Due Today" value={dueToday.length} tone="warning" testID="kpi-due-today" />
        <KpiCard label="Overdue" value={overdue.length} tone="error" testID="kpi-overdue" />
        <KpiCard label="Returned" value={returned.length} tone="warning" testID="kpi-returned" />
        <KpiCard label="Pending Sync" value={pending} tone={pending > 0 ? "warning" : "success"} testID="kpi-pending-sync" />
        <KpiCard label="Submitted" value={submitted.length} tone="success" testID="kpi-submitted" />
      </View>

      <SectionTitle>Needs attention</SectionTitle>
      {casesQ.isLoading ? (
        <Loading label="Loading assigned cases…" />
      ) : casesQ.isError ? (
        <ErrorBox message="Failed to sync cases. Check your connection." onRetry={() => casesQ.refetch()} />
      ) : needsAttention.length === 0 ? (
        <Empty title="All clear" message="No overdue, due-today or returned cases right now." />
      ) : (
        <View>
          {needsAttention.map((c) => (
            <CaseRow key={c.id} c={c} testID={`attention-case-${c.internal_case_id}`} onPress={() => router.push(`/case/${c.id}`)} />
          ))}
        </View>
      )}
      <View style={{ height: spacing.xl }} />
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  hello: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, fontFamily: typography.fontFamily },
  agentId: { color: colors.muted, marginTop: 2 },
  syncBadge: { borderRadius: 999, paddingHorizontal: spacing.md, paddingVertical: 6 },
  syncOk: { backgroundColor: colors.brandTertiary },
  syncPending: { backgroundColor: colors.warning },
  syncOkText: { color: colors.brandPrimary, fontWeight: "700", fontSize: typography.scale.sm },
  syncPendingText: { color: colors.onWarning, fontWeight: "700", fontSize: typography.scale.sm },
  caseRow: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: 12,
    padding: spacing.md, marginBottom: spacing.sm, flexDirection: "row", gap: spacing.sm,
  },
  caseRowOverdue: { borderColor: colors.error, borderLeftWidth: 4, borderLeftColor: colors.error },
  caseName: { color: colors.onSurface, fontWeight: "700", fontSize: typography.scale.base },
  caseMeta: { color: colors.muted, fontSize: typography.scale.sm },
  overdueText: { color: colors.error, fontSize: typography.scale.sm, fontWeight: "700" },
}));
