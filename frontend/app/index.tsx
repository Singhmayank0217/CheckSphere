// Root "/": agent app shows the animated splash, the web shows a short loader, then the
// role-selection login page (or the user's own portal if already signed in).
import { useCallback, useState } from "react";
import { Platform, Pressable, Text, useWindowDimensions, View } from "react-native";
import { Redirect, useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { AgentSplash } from "@/src/components/AgentSplash";
import { ShieldMark, WebLoader } from "@/src/components/WebLoader";
import { homeFor } from "@/src/navigation";
import { useSession } from "@/src/session";
import { makeStyles, radius, spacing, typography, useTheme } from "@/src/theme";

let introShown = false;

const ROLES = [
  { role: "agent", title: "Agent Login", sub: "Field agents — mobile verification app", icon: "phone-portrait" },
  { role: "supervisor", title: "Supervisor Login", sub: "Review reports and manage your team", icon: "people" },
  { role: "super_admin", title: "Super Admin Login", sub: "Full administration portal", icon: "shield-checkmark" },
] as const;

export default function Index() {
  const { ready, user } = useSession();
  const router = useRouter();
  const styles = useStyles();
  const { colors } = useTheme();
  const [introDone, setIntroDone] = useState(introShown);
  const { width } = useWindowDimensions();
  const wide = width >= 900;
  const finish = useCallback(() => {
    introShown = true;
    setIntroDone(true);
  }, []);

  if (!introDone) {
    return Platform.OS === "web" ? <WebLoader onDone={finish} duration={1100} /> : <AgentSplash onDone={finish} />;
  }
  if (!ready) return <WebLoader />;
  if (user) {
    if (user.must_change_password) return <Redirect href="/change-password" />;
    return <Redirect href={homeFor(user.role) as any} />;
  }
  // The Android app is for field agents only.
  if (Platform.OS !== "web") return <Redirect href="/login?role=agent" />;

  return (
    <View style={[styles.root, { flexDirection: wide ? "row" : "column" }]} testID="role-select-screen">
      <View style={styles.brandPane}>
        <ShieldMark size={72} />
        <Text style={styles.brand}>CheckSphere</Text>
        <Text style={styles.brandMain}>Every Visit. Verified.</Text>
        <Text style={styles.brandSub}>Secure field verification, captured with proof.</Text>
      </View>
      <View style={styles.formPane}>
        <View style={styles.card}>
          <Text style={styles.title}>Sign in</Text>
          <Text style={styles.sub}>Choose how you want to sign in to CheckSphere.</Text>
          {ROLES.map((r) => (
            <Pressable
              key={r.role}
              style={({ hovered, pressed }: any) => [styles.roleBtn, (hovered || pressed) && styles.roleBtnHover]}
              onPress={() => router.push(`/login?role=${r.role}`)}
              testID={`role-select-${r.role}`}
            >
              <View style={styles.roleIcon}><Ionicons name={r.icon as any} size={22} color={colors.brandPrimary} /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.roleTitle}>{r.title}</Text>
                <Text style={styles.roleSub}>{r.sub}</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={colors.muted} />
            </Pressable>
          ))}
          <Text style={styles.foot}>Private system. Accounts are issued by your CheckSphere administrator.</Text>
        </View>
      </View>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  brandPane: {
    flex: 1, minHeight: 280, backgroundColor: colors.brandPrimary, alignItems: "center",
    justifyContent: "center", padding: spacing.xxl,
  },
  brand: { color: "#FFFFFF", fontSize: 36, fontWeight: "800", marginTop: spacing.lg, fontFamily: typography.fontFamily },
  brandMain: { color: "#FFFFFF", fontSize: 20, fontWeight: "600", marginTop: spacing.sm },
  brandSub: { color: "rgba(255,255,255,0.75)", fontSize: 15, marginTop: spacing.xs },
  formPane: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xxl },
  card: { width: "100%", maxWidth: 460, gap: spacing.md },
  title: { fontSize: 28, fontWeight: "800", color: colors.onSurface, fontFamily: typography.fontFamily },
  sub: { color: colors.muted, fontSize: 15, marginBottom: spacing.sm },
  roleBtn: {
    flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.lg, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary, minHeight: 72,
  },
  roleBtnHover: { borderColor: colors.brandPrimary, backgroundColor: colors.brandTertiary },
  roleIcon: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  roleTitle: { fontSize: 17, fontWeight: "700", color: colors.onSurface },
  roleSub: { fontSize: 13, color: colors.muted, marginTop: 2 },
  foot: { color: colors.muted, fontSize: 13, marginTop: spacing.md },
}));
