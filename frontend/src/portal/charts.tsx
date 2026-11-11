// Lightweight View-based charts for the desktop dashboard.
import { Text, View } from "react-native";

import { makeStyles, radius, spacing } from "@/src/theme";

export function ColumnChart({ data, height = 160, testID }: { data: { label: string; value: number }[]; height?: number; testID?: string }) {
  const styles = useStyles();
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <View testID={testID}>
      <View style={[styles.colArea, { height }]}>
        {data.map((d) => (
          <View key={d.label} style={styles.colWrap}>
            <Text style={styles.colVal}>{d.value || ""}</Text>
            <View style={[styles.col, { height: Math.max(2, (d.value / max) * (height - 22)) }]} />
          </View>
        ))}
      </View>
      <View style={styles.colLabels}>
        {data.map((d) => <Text key={d.label} style={styles.colLabel} numberOfLines={1}>{d.label}</Text>)}
      </View>
    </View>
  );
}

export function HBarChart({ data, unit = "", tone = "brand", testID }: {
  data: { label: string; value: number; note?: string }[]; unit?: string; tone?: "brand" | "info" | "warning"; testID?: string;
}) {
  const styles = useStyles();
  const max = Math.max(1, ...data.map((d) => d.value));
  const fill = tone === "info" ? styles.fillInfo : tone === "warning" ? styles.fillWarning : styles.fillBrand;
  if (data.length === 0) return <Text style={styles.empty}>No data for the selected filters.</Text>;
  return (
    <View style={{ gap: spacing.sm }} testID={testID}>
      {data.map((d) => (
        <View key={d.label} style={styles.hRow}>
          <Text style={styles.hLabel} numberOfLines={1}>{d.label}</Text>
          <View style={styles.track}><View style={[styles.fill, fill, { width: `${(d.value / max) * 100}%` }]} /></View>
          <Text style={styles.hVal} numberOfLines={1}>{d.value}{unit}{d.note ? ` · ${d.note}` : ""}</Text>
        </View>
      ))}
    </View>
  );
}

export function StackedBar({ parts, testID }: { parts: { label: string; value: number; color: string }[]; testID?: string }) {
  const styles = useStyles();
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  return (
    <View testID={testID}>
      <View style={styles.stack}>
        {parts.filter((p) => p.value > 0).map((p) => <View key={p.label} style={{ flex: p.value / total, backgroundColor: p.color }} />)}
      </View>
      <View style={styles.legend}>
        {parts.map((p) => (
          <View key={p.label} style={styles.legendItem}>
            <View style={[styles.dot, { backgroundColor: p.color }]} />
            <Text style={styles.legendText}>{p.label} ({p.value})</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  colArea: { flexDirection: "row", alignItems: "flex-end", gap: 6, borderBottomWidth: 1, borderBottomColor: colors.border },
  colWrap: { flex: 1, alignItems: "center", justifyContent: "flex-end" },
  col: { width: "70%", backgroundColor: colors.brandSecondary, borderTopLeftRadius: 4, borderTopRightRadius: 4 },
  colVal: { fontSize: 11, color: colors.muted, marginBottom: 2 },
  colLabels: { flexDirection: "row", gap: 6, marginTop: 4 },
  colLabel: { flex: 1, fontSize: 11, color: colors.muted, textAlign: "center" },
  hRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  hLabel: { width: 170, fontSize: 14, color: colors.onSurface, fontWeight: "600" },
  track: { flex: 1, height: 12, borderRadius: 6, backgroundColor: colors.surfaceTertiary, overflow: "hidden" },
  fill: { height: 12, borderRadius: 6 },
  fillBrand: { backgroundColor: colors.brandSecondary },
  fillInfo: { backgroundColor: colors.info },
  fillWarning: { backgroundColor: colors.warning },
  hVal: { width: 190, fontSize: 13, color: colors.muted },
  empty: { color: colors.muted, fontSize: 14 },
  stack: { flexDirection: "row", height: 18, borderRadius: radius.pill, overflow: "hidden", backgroundColor: colors.surfaceTertiary },
  legend: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginTop: spacing.md },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 6 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  legendText: { fontSize: 13, color: colors.onSurfaceSecondary },
}));
