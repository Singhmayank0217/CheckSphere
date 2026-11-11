// Shared UI primitives for CheckSphere.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ActivityIndicator, Modal, Platform, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { makeStyles, spacing, radius, typography, useTheme } from "@/src/theme";

// ---------------------------------------------------------------- Toast
type ToastItem = { key: number; message: string; tone: "info" | "success" | "error" };
let toastListener: ((t: ToastItem) => void) | null = null;

export function showToast(message: string, tone: ToastItem["tone"] = "info") {
  toastListener?.({ key: Date.now(), message, tone });
}

export function ToastHost() {
  const [toast, setToast] = useState<ToastItem | null>(null);
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  useEffect(() => {
    toastListener = setToast;
    return () => {
      toastListener = null;
    };
  }, []);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(id);
  }, [toast]);
  if (!toast) return null;
  const toneStyle =
    toast.tone === "success" ? styles.toastSuccess : toast.tone === "error" ? styles.toastError : styles.toastInfo;
  return (
    <View pointerEvents="none" style={[styles.toast, toneStyle, { bottom: insets.bottom + 24 }]} testID="toast">
      <Text style={styles.toastText}>{toast.message}</Text>
    </View>
  );
}

// ---------------------------------------------------------------- Screen
export function Screen({ children, scroll = true, pad = true, testID }: {
  children: ReactNode; scroll?: boolean; pad?: boolean; testID?: string;
}) {
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  return (
    <View style={[styles.screen, { paddingTop: insets.top, paddingBottom: insets.bottom }]} testID={testID}>
      {scroll ? (
        <ScrollView contentContainerStyle={[pad && { padding: spacing.lg }]} showsVerticalScrollIndicator={false}>
          {children}
        </ScrollView>
      ) : (
        <View style={[{ flex: 1 }, pad && { padding: spacing.lg }]}>{children}</View>
      )}
    </View>
  );
}

// ---------------------------------------------------------------- Card / rows
export function Card({ children, style, testID }: { children: ReactNode; style?: any; testID?: string }) {
  const styles = useStyles();
  return <View style={[styles.card, style]} testID={testID}>{children}</View>;
}

export function DisplayRow({ label, value, mono = false }: { label: string; value: ReactNode; mono?: boolean }) {
  const styles = useStyles();
  return (
    <View style={styles.displayRow}>
      <Text style={styles.displayLabel}>{label}</Text>
      <Text style={[styles.displayValue, mono && styles.mono]} numberOfLines={3}>
        {value === null || value === undefined || value === "" ? "-" : String(value)}
      </Text>
    </View>
  );
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  const styles = useStyles();
  return (
    <View style={styles.sectionTitleRow}>
      <Text style={styles.sectionTitle}>{children}</Text>
      {action}
    </View>
  );
}

// ---------------------------------------------------------------- Status pill
const STATUS_TONES: Record<string, "success" | "info" | "warning" | "error" | "brand" | "muted"> = {
  approved: "success", exported: "success", new: "info", assigned: "brand", in_progress: "warning",
  submitted: "info", under_review: "info", returned: "warning", inconclusive: "muted",
  exception: "error", draft: "muted", superseded: "muted",
};

export const STATUS_LABELS: Record<string, string> = {
  new: "New", assigned: "Assigned", in_progress: "In Progress", submitted: "Submitted",
  under_review: "Under Review", returned: "Returned", approved: "Approved", inconclusive: "Inconclusive",
  exception: "Mismatch/Exception", exported: "Exported", draft: "Draft", superseded: "Superseded",
};

export const FLAG_LABELS: Record<string, string> = {
  missing_gps: "Missing GPS", low_gps_accuracy: "Low GPS accuracy",
  far_from_assigned_address: "Far from assigned address", duplicate_photo_cross_case: "Duplicate photo across cases",
  same_evidence_reused: "Same evidence photo reused", impossible_travel: "Impossible travel",
  late_submission: "Late submission vs SLA", incomplete_evidence: "Incomplete evidence",
  multiple_same_place_time: "Multiple reports, same place/time", no_visit_started: "Visit not started at location",
};

export function StatusPill({ status, testID }: { status: string; testID?: string }) {
  const styles = useStyles();
  const tone = STATUS_TONES[status] ?? "muted";
  const bg = tone === "success" ? styles.pillSuccess : tone === "info" ? styles.pillInfo : tone === "warning"
    ? styles.pillWarning : tone === "error" ? styles.pillError : tone === "brand" ? styles.pillBrand : styles.pillMuted;
  return (
    <View style={[styles.pill, bg]} testID={testID ?? `status-pill-${status}`}>
      <Text style={[styles.pillText, tone === "muted" && styles.pillMutedText]}>{STATUS_LABELS[status] ?? status}</Text>
    </View>
  );
}

export function PriorityPill({ priority }: { priority: string }) {
  const styles = useStyles();
  const tone = priority === "High" ? styles.pillError : priority === "Low" ? styles.pillMuted : styles.pillWarning;
  return (
    <View style={[styles.pill, tone]} testID={`priority-pill-${priority.toLowerCase()}`}>
      <Text style={[styles.pillText, priority === "Low" && styles.pillMutedText]}>{priority}</Text>
    </View>
  );
}

// ---------------------------------------------------------------- Button
export function Btn({ label, onPress, variant = "primary", loading, disabled, testID, small, full }: {
  label: string; onPress: () => void; variant?: "primary" | "secondary" | "danger" | "ghost";
  loading?: boolean; disabled?: boolean; testID?: string; small?: boolean; full?: boolean;
}) {
  const styles = useStyles();
  const style = variant === "primary" ? styles.btnPrimary : variant === "danger" ? styles.btnDanger
    : variant === "ghost" ? styles.btnGhost : styles.btnSecondary;
  const text = variant === "primary" ? styles.btnPrimaryText : variant === "danger" ? styles.btnDangerText
    : variant === "ghost" ? styles.btnGhostText : styles.btnSecondaryText;
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.btn, style, small && styles.btnSmall, full && { width: "100%" },
        (disabled || loading) && styles.btnDisabled, pressed && styles.btnPressed,
      ]}
      testID={testID}
    >
      {loading ? (
        <ActivityIndicator size="small" color={variant === "primary" || variant === "danger" ? "#FFFFFF" : undefined} />
      ) : (
        <Text style={[text, small && styles.btnSmallText]}>{label}</Text>
      )}
    </Pressable>
  );
}

// ---------------------------------------------------------------- KPI
export function KpiCard({ label, value, tone = "brand", onPress, testID }: {
  label: string; value: string | number; tone?: "brand" | "success" | "warning" | "error" | "info"; onPress?: () => void; testID?: string;
}) {
  const styles = useStyles();
  const bar = tone === "success" ? styles.kpiSuccess : tone === "warning" ? styles.kpiWarning
    : tone === "error" ? styles.kpiError : tone === "info" ? styles.kpiInfo : styles.kpiBrand;
  const content = (
    <View style={[styles.kpi, bar]}>
      <Text style={styles.kpiValue}>{value}</Text>
      <Text style={styles.kpiLabel}>{label}</Text>
    </View>
  );
  if (onPress) {
    return <Pressable onPress={onPress} testID={testID} style={styles.kpiWrap}>{content}</Pressable>;
  }
  return <View testID={testID} style={styles.kpiWrap}>{content}</View>;
}

// ---------------------------------------------------------------- Back header
export function BackHeader({ title, testID = "back-btn" }: { title?: string; testID?: string }) {
  const styles = useStyles();
  const router = useRouter();
  return (
    <View style={styles.backRow}>
      <Pressable
        onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))}
        hitSlop={12}
        style={styles.backBtn}
        testID={testID}
      >
        <Ionicons name="chevron-back" size={22} color={styles.backText.color as string} />
        <Text style={styles.backText}>Back</Text>
      </Pressable>
      {title ? <Text style={styles.backTitle} numberOfLines={1}>{title}</Text> : null}
    </View>
  );
}

// ---------------------------------------------------------------- States
export function Loading({ label = "Loading…" }: { label?: string }) {
  const styles = useStyles();
  return (
    <View style={styles.stateBox} testID="loading-state">
      <ActivityIndicator size="large" />
      <Text style={styles.stateText}>{label}</Text>
    </View>
  );
}

export function Empty({ title, message }: { title: string; message?: string }) {
  const styles = useStyles();
  return (
    <View style={styles.stateBox} testID="empty-state">
      <Text style={styles.emptyTitle}>{title}</Text>
      {message ? <Text style={styles.stateText}>{message}</Text> : null}
    </View>
  );
}

export function ErrorBox({ message, onRetry, testID = "error-box" }: { message: string; onRetry?: () => void; testID?: string }) {
  const styles = useStyles();
  return (
    <View style={styles.errorBox} testID={testID}>
      <Text style={styles.errorText}>{message}</Text>
      {onRetry ? (
        <Btn label="Retry" variant="secondary" small onPress={onRetry} testID="error-retry-btn" />
      ) : null}
    </View>
  );
}

export function Banner({ message, tone = "info" }: { message: string; tone?: "info" | "warning" | "error" | "success" }) {
  const styles = useStyles();
  const style = tone === "error" ? styles.bannerError : tone === "warning" ? styles.bannerWarning
    : tone === "success" ? styles.bannerSuccess : styles.bannerInfo;
  return (
    <View style={[styles.banner, style]} testID={`banner-${tone}`}>
      <Text style={tone === "info" ? styles.bannerInfoText : styles.bannerText}>{message}</Text>
    </View>
  );
}

// ---------------------------------------------------------------- Modal
export function PopupModal({ visible, title, onClose, children, wide }: {
  visible: boolean; title: string; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  const styles = useStyles();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.modalOverlay} onPress={onClose}>
        <Pressable style={[styles.modalCard, wide && { maxWidth: 720, width: "92%" }]} onPress={() => {}}>
          <Text style={styles.modalTitle} testID="modal-title">{title}</Text>
          {children}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

// ---------------------------------------------------------------- styles
const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.surface },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.md,
  },
  displayRow: {
    flexDirection: "row", justifyContent: "space-between", gap: spacing.md,
    paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  displayLabel: { color: colors.muted, fontSize: typography.scale.sm, flexShrink: 0, width: "38%" },
  displayValue: { color: colors.onSurface, fontSize: typography.scale.base, fontWeight: "500", flex: 1, flexShrink: 1, minWidth: 0, textAlign: "right", ...(Platform.OS === "web" ? ({ wordBreak: "break-word" } as any) : {}) },
  mono: { fontFamily: "monospace" },
  sectionTitleRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginTop: spacing.md, marginBottom: spacing.sm,
  },
  sectionTitle: { fontSize: typography.scale.lg, fontWeight: "700", color: colors.onSurface, fontFamily: typography.fontFamily },

  pill: { borderRadius: radius.pill, paddingHorizontal: spacing.md, paddingVertical: 3, alignSelf: "flex-start" },
  pillText: { color: colors.onBrandPrimary, fontSize: typography.scale.sm, fontWeight: "600" },
  pillSuccess: { backgroundColor: colors.success }, pillInfo: { backgroundColor: colors.info },
  pillWarning: { backgroundColor: colors.warning }, pillError: { backgroundColor: colors.error },
  pillBrand: { backgroundColor: colors.brandSecondary }, pillMuted: { backgroundColor: colors.surfaceTertiary },
  pillMutedText: { color: colors.onSurfaceTertiary },

  btn: {
    borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    alignItems: "center", justifyContent: "center", minHeight: 44,
  },
  btnSmall: { minHeight: 36, paddingHorizontal: spacing.md, paddingVertical: 6 },
  btnSmallText: { fontSize: typography.scale.sm },
  btnPressed: { opacity: 0.85 },
  btnDisabled: { opacity: 0.5 },
  btnPrimary: { backgroundColor: colors.brandPrimary },
  btnPrimaryText: { color: colors.onBrandPrimary, fontWeight: "700", fontSize: typography.scale.base },
  btnSecondary: { backgroundColor: colors.brandTertiary, borderWidth: 1, borderColor: colors.brandPrimary },
  btnSecondaryText: { color: colors.brandPrimary, fontWeight: "700", fontSize: typography.scale.base },
  btnDanger: { backgroundColor: colors.error },
  btnDangerText: { color: colors.onError, fontWeight: "700", fontSize: typography.scale.base },
  btnGhost: { backgroundColor: "transparent" },
  btnGhostText: { color: colors.info, fontWeight: "600", fontSize: typography.scale.base },

  kpi: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    borderLeftWidth: 4, padding: spacing.lg, flex: 1,
  },
  kpiWrap: { flexGrow: 1, flexBasis: 140, margin: spacing.xs },
  backRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.md, minHeight: 44 },
  backBtn: { flexDirection: "row", alignItems: "center", minHeight: 44, paddingRight: spacing.sm },
  backText: { color: colors.brandPrimary, fontSize: typography.scale.lg, fontWeight: "700" },
  backTitle: { flex: 1, color: colors.onSurface, fontSize: typography.scale.lg, fontWeight: "700" },
  kpiBrand: { borderLeftColor: colors.brandPrimary }, kpiSuccess: { borderLeftColor: colors.success },
  kpiWarning: { borderLeftColor: colors.warning }, kpiError: { borderLeftColor: colors.error },
  kpiInfo: { borderLeftColor: colors.info },
  kpiValue: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, fontFamily: typography.fontFamily },
  kpiLabel: { fontSize: typography.scale.sm, color: colors.muted, marginTop: 2 },

  stateBox: { alignItems: "center", justifyContent: "center", padding: spacing.xxl, gap: spacing.sm },
  emptyTitle: { fontSize: typography.scale.lg, fontWeight: "700", color: colors.onSurface },
  stateText: { color: colors.muted, textAlign: "center", fontSize: typography.scale.base },
  errorBox: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, borderWidth: 1, borderColor: colors.error,
    padding: spacing.lg, gap: spacing.sm, alignItems: "flex-start",
  },
  errorText: { color: colors.error, fontWeight: "600" },

  banner: { borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  bannerInfo: { backgroundColor: colors.brandTertiary }, bannerWarning: { backgroundColor: colors.warning },
  bannerError: { backgroundColor: colors.error }, bannerSuccess: { backgroundColor: colors.success },
  bannerText: { color: colors.onError, fontSize: typography.scale.sm, fontWeight: "600" },
  bannerInfoText: { color: colors.onBrandTertiary, fontSize: typography.scale.sm, fontWeight: "600" },

  toast: {
    position: "absolute", alignSelf: "center", maxWidth: 420, borderRadius: radius.md,
    paddingVertical: spacing.md, paddingHorizontal: spacing.lg, shadowColor: "#000", shadowOpacity: 0.2, shadowRadius: 8, elevation: 6,
  },
  toastInfo: { backgroundColor: colors.surfaceInverse }, toastSuccess: { backgroundColor: colors.success },
  toastError: { backgroundColor: colors.error },
  toastText: { color: colors.onSurfaceInverse, textAlign: "center", fontSize: typography.scale.base },

  modalOverlay: {
    flex: 1, backgroundColor: "rgba(26,26,24,0.5)", alignItems: "center", justifyContent: "center", padding: spacing.lg,
  },
  modalCard: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xl,
    width: "100%", maxWidth: 480, maxHeight: "85%",
  },
  modalTitle: { fontSize: typography.scale.xl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.md, fontFamily: typography.fontFamily },
}));
