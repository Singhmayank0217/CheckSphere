import { useState } from "react";
import { FlatList, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/src/api";
import { TextField } from "@/src/components/fields";
import { Btn, Empty, Loading, Screen } from "@/src/components/ui";
import { makeStyles, radius, spacing, typography } from "@/src/theme";

export default function AuditLog() {
  const styles = useStyles();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);

  const auditQ = useQuery({
    queryKey: ["audit", query, action, page],
    queryFn: () => {
      const p = new URLSearchParams({ page: String(page), limit: "50" });
      if (query) p.set("q", query);
      if (action) p.set("action", action);
      return api<any>(`/audit?${p.toString()}`);
    },
  });

  const items = auditQ.data?.items ?? [];

  return (
    <Screen testID="admin-audit-screen">
      <Text style={styles.title}>Immutable Audit Log</Text>
      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        <View style={{ flex: 1 }}>
          <TextField label="Search user / action / ID" value={q} onChange={setQ} testID="audit-search-input" />
        </View>
        <View style={{ justifyContent: "flex-end", paddingBottom: spacing.md }}>
          <Btn label="Filter" onPress={() => { setQuery(q); setPage(1); }} testID="audit-filter-btn" small />
        </View>
      </View>
      <View style={styles.quickRow}>
        {["login", "report_submitted", "report_approve", "report_exported", "sensitive_revealed", "session_revoked"].map((a) => (
          <Btn key={a} label={a.replace(/_/g, " ")} variant="ghost" small onPress={() => { setAction(a); setPage(1); }} testID={`audit-quick-${a}`} />
        ))}
        <Btn label="clear" variant="ghost" small onPress={() => setAction("")} testID="audit-clear-filter-btn" />
      </View>

      {auditQ.isLoading ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty title="No audit entries" message="Try different filters." />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(a: any) => a.id}
          contentContainerStyle={{ paddingBottom: spacing.xl }}
          renderItem={({ item: a }: any) => (
            <View style={styles.row} testID={`audit-row-${a.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.action}>{(a.action ?? "").replace(/_/g, " ")}</Text>
                <Text style={styles.meta}>{a.user_name} ({a.user_role}) · {a.entity} {a.entity_id ? `#${a.entity_id.slice(0, 8)}` : ""}</Text>
                {Object.keys(a.details ?? {}).length > 0 ? (
                  <Text style={styles.meta} numberOfLines={2}>{JSON.stringify(a.details)}</Text>
                ) : null}
              </View>
              <Text style={styles.time}>{a.created_at ? new Date(a.created_at).toLocaleString() : ""}</Text>
            </View>
          )}
        />
      )}

      <View style={{ flexDirection: "row", justifyContent: "center", gap: spacing.md, paddingVertical: spacing.sm }}>
        <Btn label="Prev" variant="secondary" small disabled={page <= 1} onPress={() => setPage((p) => Math.max(1, p - 1))} testID="audit-prev-btn" />
        <Text style={{ alignSelf: "center", color: "#73706A" }}>Page {page} · {auditQ.data?.total ?? 0} entries</Text>
        <Btn label="Next" variant="secondary" small disabled={page * 50 >= (auditQ.data?.total ?? 0)} onPress={() => setPage((p) => p + 1)} testID="audit-next-btn" />
      </View>
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  title: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.md, fontFamily: typography.fontFamily },
  quickRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginBottom: spacing.sm },
  row: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    padding: spacing.md, marginBottom: spacing.sm, flexDirection: "row", gap: spacing.md,
  },
  action: { color: colors.onSurface, fontWeight: "700", fontSize: typography.scale.sm, textTransform: "capitalize" },
  meta: { color: colors.muted, fontSize: typography.scale.sm },
  time: { color: colors.muted, fontSize: typography.scale.sm, flexShrink: 0 },
}));
