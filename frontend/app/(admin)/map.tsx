import { useState } from "react";
import { FlatList, Pressable, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { MiniMap } from "@/src/components/MiniMap";
import { Banner, Empty, FLAG_LABELS, Loading, Screen, SectionTitle, StatusPill } from "@/src/components/ui";
import { SelectField } from "@/src/components/fields";
import { makeStyles, radius, spacing, typography } from "@/src/theme";

export default function MapFlags() {
  const router = useRouter();
  const styles = useStyles();
  const [flaggedOnly, setFlaggedOnly] = useState(true);
  const [status, setStatus] = useState("");
  const [city, setCity] = useState("");
  const [stateName, setStateName] = useState("");

  const mapQ = useQuery({
    queryKey: ["map", flaggedOnly, status, city, stateName],
    queryFn: () => {
      const p = new URLSearchParams();
      if (flaggedOnly) p.set("flagged", "1");
      if (status) p.set("status", status);
      if (city) p.set("city", city);
      if (stateName) p.set("state", stateName);
      const s = p.toString();
      return api<{ items: any[] }>(`/dashboard/map${s ? `?${s}` : ""}`);
    },
  });
  const regionsQ = useQuery({ queryKey: ["regions"], queryFn: () => api<any>("/regions") });

  return (
    <Screen testID="admin-map-screen">
      <Text style={styles.title}>Map View & Exception Flags</Text>
      <Banner
        tone="info"
        message="Flags never auto-reject a report — flagged cases are highlighted here and in review for supervisor attention."
      />
      <View style={{ flexDirection: "row", gap: spacing.md, flexWrap: "wrap" }}>
        <View style={{ flex: 1, minWidth: 160 }}>
          <SelectField
            label="Flagged Cases"
            value={flaggedOnly ? "Flagged only" : "All cases"}
            options={["Flagged only", "All cases"]}
            onChange={(v) => setFlaggedOnly(v === "Flagged only")}
            testID="map-flagged-select"
          />
        </View>
        <View style={{ flex: 1, minWidth: 160 }}>
          <SelectField label="State" value={stateName} options={["", ...(regionsQ.data?.states ?? [])]}
            onChange={(v) => setStateName(v)} testID="map-state-select" />
        </View>
        <View style={{ flex: 1, minWidth: 160 }}>
          <SelectField label="City" value={city} options={["", ...(regionsQ.data?.cities ?? [])]}
            onChange={(v) => setCity(v)} testID="map-city-select" />
        </View>
      </View>

      {mapQ.isLoading ? (
        <Loading label="Loading case locations…" />
      ) : mapQ.isError ? (
        <Empty title="Map data unavailable" message="Try again." />
      ) : (mapQ.data?.items ?? []).length === 0 ? (
        <Empty title="No located cases" message="No cases with GPS or assigned coordinates match the filters." />
      ) : (
        <FlatList
          data={mapQ.data?.items ?? []}
          keyExtractor={(c: any) => c.id}
          contentContainerStyle={{ paddingBottom: spacing.xl, gap: spacing.sm }}
          renderItem={({ item: c }: any) => (
            <Pressable style={styles.card} onPress={() => router.push(`/cases/${c.id}`)} testID={`map-case-${c.internal_case_id}`}>
              <View style={styles.cardHead}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.caseName}>{c.applicant_name} · {c.internal_case_id}</Text>
                  <Text style={styles.meta}>{c.report_type}</Text>
                </View>
                <StatusPill status={c.status} testID={`map-status-${c.internal_case_id}`} />
              </View>
              <MiniMap lat={c.lat} lon={c.lon} accuracy={c.accuracy} height={170} testID={`map-preview-${c.internal_case_id}`} />
              {(c.flags ?? []).length > 0 ? (
                <View style={styles.flags}>
                  {c.flags.map((f: string) => (
                    <View key={f} style={styles.flagChip}>
                      <Text style={styles.flagText}>⚑ {FLAG_LABELS[f] ?? f}</Text>
                    </View>
                  ))}
                </View>
              ) : null}
            </Pressable>
          )}
        />
      )}
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  title: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.md, fontFamily: typography.fontFamily },
  card: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md, gap: spacing.sm,
  },
  cardHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: spacing.sm },
  caseName: { color: colors.onSurface, fontWeight: "700" },
  meta: { color: colors.muted, fontSize: typography.scale.sm },
  flags: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  flagChip: { backgroundColor: colors.warning, borderRadius: radius.pill, paddingHorizontal: spacing.sm, paddingVertical: 2 },
  flagText: { color: colors.onWarning, fontSize: typography.scale.sm, fontWeight: "700" },
}));
