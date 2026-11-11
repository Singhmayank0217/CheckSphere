// Agent hamburger menu: closed by default, closes on select, close button and tap-outside.
import { useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Ionicons from "@react-native-vector-icons/ionicons";

import { useSession } from "@/src/session";
import { makeStyles, spacing, useTheme } from "@/src/theme";

const ITEMS = [
  { label: "Home", icon: "home-outline", to: "/home" },
  { label: "My Assigned Cases", icon: "list-outline", to: "/cases?filter=assigned" },
  { label: "Request New Verification", icon: "add-circle-outline", to: "/request-new" },
  { label: "Drafts / In Progress", icon: "document-outline", to: "/cases?filter=assigned" },
  { label: "Returned for Correction", icon: "return-down-back-outline", to: "/cases?filter=returned" },
  { label: "Submitted Cases", icon: "checkmark-done-outline", to: "/cases?filter=submitted" },
  { label: "Notifications", icon: "notifications-outline", to: "/notifications" },
  { label: "Profile", icon: "person-outline", to: "/profile" },
  { label: "Help", icon: "help-circle-outline", to: "help" },
];

export function AgentMenuButton() {
  const [open, setOpen] = useState(false);
  const [help, setHelp] = useState(false);
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { signOut } = useSession();
  const { colors } = useTheme();
  const styles = useStyles();
  const go = (to: string) => {
    setOpen(false);
    if (to === "help") setHelp(true);
    else router.push(to as any);
  };
  return (
    <>
      <Pressable onPress={() => setOpen(true)} hitSlop={10} style={styles.btn} testID="agent-menu-btn">
        <Ionicons name="menu" size={26} color={colors.onSurface} />
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.overlay} onPress={() => setOpen(false)} testID="agent-menu-overlay">
          <Pressable style={[styles.drawer, { paddingTop: insets.top + spacing.md, paddingBottom: insets.bottom + spacing.md }]} onPress={() => {}} testID="agent-menu-drawer">
            <View style={styles.head}>
              <Text style={styles.brand}>CheckSphere</Text>
              <Pressable onPress={() => setOpen(false)} hitSlop={10} testID="agent-menu-close-btn"><Ionicons name="close" size={26} color={colors.onSurface} /></Pressable>
            </View>
            {ITEMS.map((i) => (
              <Pressable key={i.label} style={styles.item} onPress={() => go(i.to)} testID={`menu-${i.label.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
                <Ionicons name={i.icon as any} size={21} color={colors.brandPrimary} />
                <Text style={styles.itemText}>{i.label}</Text>
              </Pressable>
            ))}
            <Pressable style={[styles.item, { marginTop: "auto" }]} onPress={async () => { setOpen(false); await signOut(); router.replace("/login?role=agent"); }} testID="menu-sign-out">
              <Ionicons name="log-out-outline" size={21} color={colors.error} />
              <Text style={[styles.itemText, { color: colors.error }]}>Sign Out</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>
      <Modal visible={help} transparent animationType="fade" onRequestClose={() => setHelp(false)}>
        <Pressable style={[styles.overlay, { justifyContent: "center", padding: spacing.xl }]} onPress={() => setHelp(false)}>
          <View style={styles.help} testID="help-modal">
            <Text style={styles.brand}>Help</Text>
            <Text style={styles.helpText}>• Start the visit at the location so GPS is captured.{"\n"}• Photos must be taken with the in-app camera.{"\n"}• Write factual observations only.{"\n"}• Drafts save encrypted on the phone and sync automatically.{"\n"}• Use Request New Verification to raise a case; your supervisor allocates it.{"\n"}• Contact your supervisor for account or allocation issues.</Text>
          </View>
        </Pressable>
      </Modal>
    </>
  );
}

const useStyles = makeStyles((colors) => ({
  btn: { width: 44, height: 44, alignItems: "center", justifyContent: "center", marginLeft: -8 },
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)" },
  drawer: { width: "80%", maxWidth: 320, height: "100%", backgroundColor: colors.surfaceSecondary, paddingHorizontal: spacing.lg },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.lg },
  brand: { fontSize: 20, fontWeight: "800", color: colors.brandPrimary },
  item: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 48 },
  itemText: { fontSize: 16, color: colors.onSurface, fontWeight: "600", flexShrink: 1 },
  help: { backgroundColor: colors.surfaceSecondary, borderRadius: 16, padding: spacing.xl, gap: spacing.md },
  helpText: { fontSize: 15, lineHeight: 24, color: colors.onSurface },
}));
