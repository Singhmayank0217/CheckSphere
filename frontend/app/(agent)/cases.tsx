import { useEffect, useState } from "react";
import { FlatList, Pressable, ScrollView, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useGlobalSearchParams } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Empty, ErrorBox, Loading, PriorityPill, Screen, StatusPill } from "@/src/components/ui";
import { TextField } from "@/src/components/fields";
import { AgentTopBar } from "@/src/components/AgentTopBar";
import { makeStyles, radius, spacing, typography } from "@/src/theme";

const FILTERS = [
  { key: "all", label: "All", qs: "" },
  { key: "assigned", label: "Assigned", qs: "&status=assigned,in_progress" },
  { key: "today", label: "Due Today", qs: "&due=today" },
  { key: "overdue", label: "Overdue", qs: "&due=overdue" },
  { key: "returned", label: "Returned", qs: "&status=returned" },
  { key: "submitted", label: "Submitted", qs: "&status=submitted,under_review,approved,exported" },
] as const;

export default function AgentCases() {
  const router = useRouter();
  const params = useGlobalSearchParams<{ filter?: string }>();
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  const [filter, setFilter] = useState<string>("all");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (params.filter && FILTERS.some((f) => f.key === params.filter)) {
      setFilter(params.filter);
    }
  }, [params.filter]);

  const active = FILTERS.find((f) => f.key === filter) ?? FILTERS[0];
  const casesQ = useQuery({
    queryKey: ["agent-cases", filter, query],
    queryFn: () => api<{ items: any[]; total: number }>(`/cases?limit=100${active.qs}${query ? `&q=${encodeURIComponent(query)}` : ""}`),
  });

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]} testID="agent-cases-screen">
      <View style={styles.header}>
        <AgentTopBar title="My Cases" />
        <TextField
          label="Search"
          value={q}
          onChange={setQ}
          placeholder="Applicant, case ID…"
          testID="cases-search-input"
        />
        <Pressable
          style={styles.searchBtn}
          onPress={() => setQuery(q)}
          testID="cases-search-button"
        >
          <Text style={styles.searchBtnText}>Search</Text>
        </Pressable>
      </View>

      <View style={styles.chipRow}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipContent}>
          {FILTERS.map((f) => (
            <Pressable
              key={f.key}
              onPress={() => setFilter(f.key)}
              style={[styles.chip, filter === f.key && styles.chipActive]}
              testID={`cases-filter-${f.key}`}
            >
              <Text style={[styles.chipText, filter === f.key && styles.chipTextActive]}>{f.label}</Text>
            </Pressable>
          ))}
        </ScrollView>
      </View>

      {casesQ.isLoading || (casesQ.isFetching && !casesQ.isFetchedAfterMount) ? (
        <Loading label="Fetching case queue…" />
      ) : casesQ.isError ? (
        <ErrorBox message="Unable to load case records." onRetry={() => casesQ.refetch()} />
      ) : (casesQ.data?.items ?? []).length === 0 ? (
        <Empty title="No cases" message="No cases match the selected filter criteria." />
      ) : (
        <FlatList
          data={casesQ.data?.items ?? []}
          keyExtractor={(c) => c.id}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.md }}
          renderItem={({ item }) => (
            <Pressable style={styles.card} onPress={() => router.push(`/case/${item.id}`)} testID={`case-card-${item.internal_case_id}`}>
              <View style={{ flex: 1, gap: 3 }}>
                <Text style={styles.applicant}>{item.applicant_name}</Text>
                <Text style={styles.meta}>{item.internal_case_id} · Client Case: {item.client_case_id}</Text>
                <Text style={styles.meta}>{item.client_name} · {item.report_type_name || item.report_type}</Text>
                <Text style={styles.address} numberOfLines={2}>{item.assigned_address}</Text>
              </View>
              <View style={styles.right}>
                <StatusPill status={item.status} testID={`case-status-${item.internal_case_id}`} />
                <PriorityPill priority={item.priority} />
                <Text style={styles.due}>{item.due_at ? `Due ${new Date(item.due_at).toLocaleDateString()}` : "—"}</Text>
              </View>
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.surface, paddingTop: 16 },
  header: { paddingHorizontal: spacing.lg, paddingTop: spacing.lg },
  title: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, fontFamily: typography.fontFamily, marginBottom: spacing.md },
  searchBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md, alignItems: "center",
    paddingVertical: spacing.sm, marginBottom: spacing.sm, minHeight: 40, justifyContent: "center",
  },
  searchBtnText: { color: colors.onBrandPrimary, fontWeight: "700" },
  chipRow: { height: 56, justifyContent: "center" },
  chipContent: { paddingHorizontal: spacing.lg, gap: spacing.sm, alignItems: "center" },
  chip: {
    flexShrink: 0, height: 36, paddingHorizontal: spacing.md, borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary, justifyContent: "center",
  },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipText: { color: colors.onSurfaceSecondary, fontSize: typography.scale.sm, fontWeight: "600" },
  chipTextActive: { color: colors.onBrandPrimary },
  card: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, marginBottom: spacing.sm, flexDirection: "row", gap: spacing.sm,
  },
  applicant: { color: colors.onSurface, fontWeight: "700", fontSize: typography.scale.lg },
  meta: { color: colors.muted, fontSize: typography.scale.sm },
  address: { color: colors.onSurfaceTertiary, fontSize: typography.scale.sm, marginTop: 2 },
  right: { alignItems: "flex-end", gap: 6, justifyContent: "space-between" },
  due: { color: colors.muted, fontSize: typography.scale.sm },
}));
