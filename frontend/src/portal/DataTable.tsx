// Desktop data table: sortable headers, row press, pagination; horizontal scroll only inside the table.
import type { ReactNode } from "react";
import { ActivityIndicator, Pressable, ScrollView, Text, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";

import { makeStyles, radius, spacing } from "@/src/theme";

export type Column<T> = { key: string; label: string; width: number; sortable?: boolean; render?: (row: T) => ReactNode };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = any;

export function DataTable<T extends Row = Row>({
  columns, rows, sort, order, onSort, onRowPress, page, total, limit, onPage, loading, testID = "data-table", empty = "No records found.",
}: {
  columns: Column<T>[]; rows: T[]; sort?: string; order?: "asc" | "desc"; onSort?: (key: string) => void;
  onRowPress?: (row: T) => void; page?: number; total?: number; limit?: number; onPage?: (p: number) => void;
  loading?: boolean; testID?: string; empty?: string;
}) {
  const styles = useStyles();
  const minWidth = columns.reduce((a, c) => a + c.width, 0);
  const pages = total && limit ? Math.max(1, Math.ceil(total / limit)) : 1;
  return (
    <View style={styles.wrap} testID={testID}>
      <ScrollView horizontal showsHorizontalScrollIndicator contentContainerStyle={{ flexGrow: 1 }}>
        <View style={{ minWidth, flexGrow: 1 }}>
          <View style={styles.headRow}>
            {columns.map((c) => (
              <Pressable
                key={c.key}
                disabled={!c.sortable || !onSort}
                onPress={() => onSort?.(c.key)}
                style={[styles.cell, { flexBasis: c.width, flexGrow: 1 }]}
                testID={`th-${c.key}`}
              >
                <Text style={styles.headText} numberOfLines={1}>{c.label}</Text>
                {c.sortable && sort === c.key ? (
                  <Ionicons name={order === "asc" ? "arrow-up" : "arrow-down"} size={13} color={styles.headText.color as string} />
                ) : null}
              </Pressable>
            ))}
          </View>
          {loading ? (
            <View style={styles.state}><ActivityIndicator /></View>
          ) : rows.length === 0 ? (
            <View style={styles.state}><Text style={styles.emptyText}>{empty}</Text></View>
          ) : (
            rows.map((r, i) => (
              <Pressable
                key={(r as any).id}
                onPress={() => onRowPress?.(r)}
                disabled={!onRowPress}
                style={({ hovered }: any) => [styles.row, i % 2 === 1 && styles.rowAlt, hovered && onRowPress && styles.rowHover]}
                testID={`row-${(r as any).id}`}
              >
                {columns.map((c) => (
                  <View key={c.key} style={[styles.cell, { flexBasis: c.width, flexGrow: 1 }]}>
                    {c.render ? c.render(r) : <Text style={styles.cellText} numberOfLines={2}>{String((r as any)[c.key] ?? "—")}</Text>}
                  </View>
                ))}
              </Pressable>
            ))
          )}
        </View>
      </ScrollView>
      {onPage ? (
        <View style={styles.footer}>
          <Text style={styles.footText}>{total ?? 0} records · Page {page} of {pages}</Text>
          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            <Pressable disabled={(page ?? 1) <= 1} onPress={() => onPage((page ?? 1) - 1)} style={[styles.pageBtn, (page ?? 1) <= 1 && styles.disabled]} testID={`${testID}-prev`}>
              <Ionicons name="chevron-back" size={16} color={styles.footText.color as string} />
            </Pressable>
            <Pressable disabled={(page ?? 1) >= pages} onPress={() => onPage((page ?? 1) + 1)} style={[styles.pageBtn, (page ?? 1) >= pages && styles.disabled]} testID={`${testID}-next`}>
              <Ionicons name="chevron-forward" size={16} color={styles.footText.color as string} />
            </Pressable>
          </View>
        </View>
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  wrap: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  headRow: { flexDirection: "row", backgroundColor: colors.surfaceTertiary, borderBottomWidth: 1, borderBottomColor: colors.border },
  headText: { color: colors.onSurfaceTertiary, fontWeight: "700", fontSize: 13, textTransform: "uppercase", letterSpacing: 0.4 },
  cell: { paddingHorizontal: spacing.md, paddingVertical: 12, flexDirection: "row", alignItems: "center", gap: 4, minWidth: 0 },
  row: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.divider, minHeight: 52 },
  rowAlt: { backgroundColor: colors.surface },
  rowHover: { backgroundColor: colors.brandTertiary },
  cellText: { color: colors.onSurface, fontSize: 14 },
  state: { padding: spacing.xxl, alignItems: "center" },
  emptyText: { color: colors.muted, fontSize: 15 },
  footer: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.md, borderTopWidth: 1, borderTopColor: colors.border },
  footText: { color: colors.onSurfaceTertiary, fontSize: 14 },
  pageBtn: { width: 36, height: 36, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  disabled: { opacity: 0.4 },
}));
