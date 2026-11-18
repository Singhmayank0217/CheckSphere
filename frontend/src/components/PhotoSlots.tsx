// Photo evidence slots: in-app camera only, preview + retake. Gallery is never used for visit photos.
// A slot counts as completed only when the server holds an uploaded photo for it; photos still waiting
// in the phone's upload queue are shown separately and are NOT counted.
import { Pressable, ScrollView, Text, View } from "react-native";
import { Image } from "expo-image";
import { useRouter } from "expo-router";

import { fileUrl } from "@/src/api";
import { fmtIST } from "@/src/utils/geo";
import type { PendingUpload } from "@/src/utils/pendingUploads";
import { makeStyles, radius, spacing, typography, useTheme } from "@/src/theme";

const useStyles = makeStyles((colors) => ({
  slot: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md,
  },
  slotHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  slotLabel: { flex: 1, fontSize: typography.scale.base, fontWeight: "600", color: colors.onSurface },
  req: { fontSize: typography.scale.sm, color: colors.error, fontWeight: "700", marginLeft: spacing.sm },
  ok: { fontSize: typography.scale.sm, color: colors.success, fontWeight: "700", marginLeft: spacing.sm },
  opt: { fontSize: typography.scale.sm, color: colors.muted, marginLeft: spacing.sm },
  thumbRow: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  thumb: { width: 96, height: 96, borderRadius: radius.sm, backgroundColor: colors.surfaceTertiary },
  captureBtn: {
    backgroundColor: colors.brandTertiary, borderRadius: radius.md, borderWidth: 1, borderColor: colors.brandPrimary,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, alignItems: "center", minHeight: 44, justifyContent: "center",
    marginTop: spacing.sm,
  },
  captureText: { color: colors.brandPrimary, fontWeight: "700", fontSize: typography.scale.base },
  done: { color: colors.success, fontSize: typography.scale.sm, fontWeight: "600" },
  meta: { color: colors.muted, fontSize: typography.scale.sm, marginTop: 4 },
  summary: { borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  summaryText: { fontWeight: "800", fontSize: typography.scale.base },
  pendingBox: { borderRadius: radius.sm, borderWidth: 1, borderColor: colors.warning, padding: spacing.sm, marginTop: spacing.sm },
  pendingText: { color: colors.onSurface, fontSize: typography.scale.sm },
  linkRow: { flexDirection: "row", gap: spacing.lg, marginTop: 4 },
  link: { color: colors.brandPrimary, fontWeight: "700", fontSize: typography.scale.sm },
}));

export type EvidenceItem = {
  id: string;
  slot: string;
  kind: string;
  filename: string;
  captured_at?: string;
  gps?: any;
  distance_m?: number | null;
  flags?: string[];
};

type Slot = { key: string; label: string; required: boolean; camera?: "front" | "back" };

export function photoCompletion(slots: Slot[], evidence: EvidenceItem[]) {
  const required = slots.filter((s) => s.required);
  const have = new Set(evidence.filter((e) => e.kind === "photo").map((e) => e.slot));
  const missing = required.filter((s) => !have.has(s.key));
  return { total: required.length, done: required.length - missing.length, missing };
}

export function PhotoSlots({ caseId, slots, evidence, canEdit, token, pending = [], onRetry, onDiscard }: {
  caseId: string; slots: Slot[]; evidence: EvidenceItem[]; canEdit: boolean; token: string | null;
  pending?: PendingUpload[]; onRetry?: (uploadId: string) => void; onDiscard?: (uploadId: string) => void;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const { total, done, missing } = photoCompletion(slots, evidence);
  const complete = total > 0 && done === total;
  return (
    <View>
      {total > 0 ? (
        <View style={[styles.summary, { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: complete ? colors.success : colors.border }]} testID="photo-completion">
          <Text style={[styles.summaryText, { color: complete ? colors.success : colors.onSurface }]}>
            {done} of {total} required photographs completed
          </Text>
          {missing.length ? (
            <Text style={styles.meta}>Missing: {missing.map((m) => m.label).join(" · ")}</Text>
          ) : null}
          {pending.length ? (
            <Text style={styles.meta}>{pending.length} photo(s) saved on this phone and waiting to upload — not yet counted.</Text>
          ) : null}
        </View>
      ) : null}
      {slots.map((slot) => {
        const items = evidence.filter((e) => e.slot === slot.key && e.kind === "photo");
        const waiting = pending.filter((p) => p.slot === slot.key);
        return (
          <View key={slot.key} style={styles.slot} testID={`photo-slot-${slot.key}`}>
            <View style={styles.slotHeader}>
              <Text style={styles.slotLabel}>{slot.label}</Text>
              {items.length > 0 ? <Text style={styles.ok}>✓ DONE</Text> : slot.required ? <Text style={styles.req}>REQUIRED</Text> : <Text style={styles.opt}>optional</Text>}
            </View>
            {items.length > 0 ? (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.thumbRow}>
                {items.map((e) => (
                  <View key={e.id}>
                    <Image source={{ uri: fileUrl(e.id, token) }} style={styles.thumb} contentFit="cover" transition={150} recyclingKey={e.id} />
                    <Text style={styles.meta}>{fmtIST(e.captured_at)}</Text>
                    <Text style={styles.meta}>
                      {e.gps?.lat != null ? `GPS ±${Math.round(e.gps.accuracy ?? 0)} m` : "No GPS"}
                      {e.distance_m != null ? ` · ${Math.round(e.distance_m)} m away` : ""}
                    </Text>
                  </View>
                ))}
              </ScrollView>
            ) : waiting.length === 0 ? (
              <Text style={{ color: colors.muted, fontSize: typography.scale.sm, marginBottom: spacing.sm }}>No photo captured yet.</Text>
            ) : null}
            {waiting.map((p) => (
              <View key={p.uploadId} style={styles.pendingBox} testID={`pending-upload-${slot.key}`}>
                <Text style={styles.pendingText}>
                  {p.state === "failed" ? "Upload refused: " : "Waiting to upload: "}captured {fmtIST(p.meta.capturedAt)}
                </Text>
                {p.lastError ? <Text style={styles.meta}>{p.lastError}</Text> : null}
                {canEdit ? (
                  <View style={styles.linkRow}>
                    <Pressable onPress={() => onRetry?.(p.uploadId)} testID={`pending-retry-${slot.key}`}><Text style={styles.link}>Retry now</Text></Pressable>
                    {p.state === "failed" ? (
                      <Pressable onPress={() => onDiscard?.(p.uploadId)} testID={`pending-discard-${slot.key}`}><Text style={styles.link}>Discard</Text></Pressable>
                    ) : null}
                  </View>
                ) : null}
              </View>
            ))}
            {canEdit ? (
              <Pressable
                style={styles.captureBtn}
                onPress={() => router.push({ pathname: "/camera", params: { caseId, slot: slot.key, label: slot.label, camera: slot.camera ?? "back" } })}
                testID={`photo-capture-${slot.key}`}
              >
                <Text style={styles.captureText}>
                  {items.length > 0 ? "Capture Again (retake)" : slot.camera === "front" ? "Take Selfie (front camera)" : "Capture Photo (camera only)"}
                </Text>
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
