// Photo evidence slots: in-app camera only, preview + retake. Gallery is never used for visit photos.
import { Pressable, ScrollView, Text, View } from "react-native";
import { Image } from "expo-image";
import { useRouter } from "expo-router";

import { fileUrl } from "@/src/api";
import { makeStyles, radius, spacing, typography, useTheme } from "@/src/theme";

const useStyles = makeStyles((colors) => ({
  slot: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md,
  },
  slotHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  slotLabel: { flex: 1, fontSize: typography.scale.base, fontWeight: "600", color: colors.onSurface },
  req: { fontSize: typography.scale.sm, color: colors.error, fontWeight: "700", marginLeft: spacing.sm },
  opt: { fontSize: typography.scale.sm, color: colors.muted, marginLeft: spacing.sm },
  thumbRow: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  thumb: { width: 96, height: 96, borderRadius: radius.sm, backgroundColor: colors.surfaceTertiary },
  captureBtn: {
    backgroundColor: colors.brandTertiary, borderRadius: radius.md, borderWidth: 1, borderColor: colors.brandPrimary,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, alignItems: "center", minHeight: 44, justifyContent: "center",
  },
  captureText: { color: colors.brandPrimary, fontWeight: "700", fontSize: typography.scale.base },
  done: { color: colors.success, fontSize: typography.scale.sm, fontWeight: "600" },
}));

export type EvidenceItem = {
  id: string;
  slot: string;
  kind: string;
  filename: string;
  captured_at?: string;
  gps?: any;
};

export function PhotoSlots({ caseId, slots, evidence, canEdit, token }: {
  caseId: string; slots: { key: string; label: string; required: boolean }[]; evidence: EvidenceItem[];
  canEdit: boolean; token: string | null;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  return (
    <View>
      {slots.map((slot) => {
        const items = evidence.filter((e) => e.slot === slot.key && e.kind === "photo");
        return (
          <View key={slot.key} style={styles.slot} testID={`photo-slot-${slot.key}`}>
            <View style={styles.slotHeader}>
              <Text style={styles.slotLabel}>{slot.label}</Text>
              {slot.required ? <Text style={styles.req}>REQUIRED</Text> : <Text style={styles.opt}>optional</Text>}
            </View>
            {items.length > 0 ? (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.thumbRow}>
                {items.map((e) => (
                  <Image
                    key={e.id}
                    source={{ uri: fileUrl(e.id, token) }}
                    style={styles.thumb}
                    contentFit="cover"
                    transition={150}
                    recyclingKey={e.id}
                  />
                ))}
              </ScrollView>
            ) : (
              <Text style={{ color: colors.muted, fontSize: typography.scale.sm, marginBottom: spacing.sm }}>
                No photo captured yet.
              </Text>
            )}
            {canEdit ? (
              <Pressable
                style={styles.captureBtn}
                onPress={() => router.push({ pathname: "/camera", params: { caseId, slot: slot.key, label: slot.label } })}
                testID={`photo-capture-${slot.key}`}
              >
                <Text style={styles.captureText}>{items.length > 0 ? "Capture Again (retake)" : "Capture Photo (camera only)"}</Text>
              </Pressable>
            ) : (
              items.length > 0 ? <Text style={styles.done}>✓ Captured via app camera</Text> : null
            )}
          </View>
        );
      })}
    </View>
  );
}
