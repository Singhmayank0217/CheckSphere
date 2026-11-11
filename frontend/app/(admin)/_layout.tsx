import { Stack, useRouter, useSegments } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Ionicons from "@react-native-vector-icons/ionicons";

import { useSession } from "@/src/session";
import { makeStyles, radius, spacing, typography } from "@/src/theme";

const NAV = [
  { key: "dashboard", path: "/(admin)/dashboard", label: "Dashboard", icon: "grid" },
  { key: "cases", path: "/(admin)/cases", label: "Cases", icon: "folder" },
  { key: "cases-new", path: "/(admin)/cases-new", label: "New / Import", icon: "add-circle" },
  { key: "users", path: "/(admin)/users", label: "Users", icon: "people" },
  { key: "master", path: "/(admin)/master", label: "Master Data", icon: "settings" },
  { key: "map", path: "/(admin)/map", label: "Map & Flags", icon: "map" },
  { key: "audit", path: "/(admin)/audit", label: "Audit Log", icon: "shield" },
  { key: "mis", path: "/(admin)/mis", label: "MIS & Exports", icon: "download" },
];

export default function AdminLayout() {
  const { user, signOut } = useSession();
  const segments = useSegments();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const styles = useStyles();
  const current = segments[segments.length - 1];

  if (!user || user.role === "agent") {
    return (
      <View style={[styles.root, { justifyContent: "center", alignItems: "center" }]} testID="admin-guard">
        <Text style={{ color: "#73706A" }}>Sign in with an administrator account.</Text>
      </View>
    );
  }

  return (
    <View style={[styles.root, { paddingTop: insets.top, paddingBottom: insets.bottom }]}>
      <View style={styles.sidebar} testID="admin-sidebar">
        <Text style={styles.brand}>CheckSphere</Text>
        <Text style={styles.brandSub}>{user.role === "super_admin" ? "Super Admin" : "Supervisor"} Console</Text>
        <View style={{ marginTop: spacing.lg, gap: 2 }}>
          {NAV.map((n) => {
            const active = current === n.key;
            return (
              <Pressable
                key={n.key}
                onPress={() => router.push(n.path as any)}
                style={[styles.navItem, active && styles.navItemActive]}
                testID={`nav-${n.key}`}
              >
                <Ionicons name={n.icon as any} size={18} color={active ? "#FFFFFF" : "rgba(255,255,255,0.72)"} />
                <Text style={[styles.navText, active && styles.navTextActive]}>{n.label}</Text>
              </Pressable>
            );
          })}
        </View>
        <View style={{ marginTop: "auto", marginBottom: spacing.lg, paddingHorizontal: spacing.sm, gap: spacing.sm }}>
          <Text style={styles.userText}>{user.name}</Text>
          <Pressable onPress={signOut} testID="admin-signout-btn">
            <Text style={styles.signOut}>Sign out</Text>
          </Pressable>
        </View>
      </View>
      <View style={{ flex: 1 }}>
        <Stack screenOptions={{ headerShown: false }} />
      </View>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, flexDirection: "row", backgroundColor: colors.surface },
  sidebar: {
    width: 224, backgroundColor: colors.brandPrimary, paddingTop: spacing.xl, paddingHorizontal: spacing.md,
  },
  brand: {
    color: colors.onBrandPrimary, fontSize: typography.scale.xl, fontWeight: "800",
    paddingHorizontal: spacing.sm, fontFamily: typography.fontFamily,
  },
  brandSub: { color: colors.onBrandPrimary, opacity: 0.7, fontSize: typography.scale.sm, paddingHorizontal: spacing.sm, marginTop: 2 },
  navItem: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm, borderRadius: radius.sm,
  },
  navItemActive: { backgroundColor: colors.brandSecondary },
  navText: { color: "rgba(255,255,255,0.85)", fontSize: typography.scale.base, fontWeight: "600" },
  navTextActive: { color: "#FFFFFF", fontWeight: "800" },
  userText: { color: "rgba(255,255,255,0.85)", fontSize: typography.scale.sm, fontWeight: "700" },
  signOut: { color: colors.onBrandPrimary, fontSize: typography.scale.sm, fontWeight: "700", textDecorationLine: "underline" },
}));
