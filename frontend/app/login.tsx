import { useState } from "react";
import { Platform, Pressable, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";

import { loginRequest } from "@/src/api";
import { TextField } from "@/src/components/fields";
import { Banner, Btn, Screen } from "@/src/components/ui";
import { ShieldMark } from "@/src/components/WebLoader";
import { homeFor, ROLE_LABEL, type Role } from "@/src/navigation";
import { useSession } from "@/src/session";
import { makeStyles, spacing, typography } from "@/src/theme";

export default function Login() {
  const params = useLocalSearchParams<{ role?: string }>();
  const role: Role = Platform.OS !== "web" ? "agent"
    : (["agent", "supervisor", "super_admin"].includes(params.role ?? "") ? (params.role as Role) : "agent");
  const { signIn } = useSession();
  const router = useRouter();
  const styles = useStyles();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const onLogin = async () => {
    if (!identifier.trim() || !password) {
      setError(role === "agent" ? "Enter your Agent ID / mobile and password." : "Enter your email and password.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await loginRequest(identifier.trim(), password, role);
      await signIn(data);
      router.replace(data.user.must_change_password ? "/change-password" : (homeFor(data.user.role) as any));
    } catch (e: any) {
      setError(e?.message ?? "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Screen testID="login-screen">
      <View style={styles.hero}>
        <View style={styles.logo}><ShieldMark size={44} /></View>
        <Text style={styles.heroTitle}>CheckSphere</Text>
        <Text style={styles.heroSub}>{ROLE_LABEL[role]} sign in</Text>
      </View>
      <View style={styles.card}>
        <Text style={styles.title} testID="login-title">{role === "agent" ? "Agent Login" : role === "supervisor" ? "Supervisor Login" : "Super Admin Login"}</Text>
        <Text style={styles.sub}>
          {role === "agent"
            ? "Use the Agent ID / mobile and temporary password provided by your administrator."
            : "Use the email address and password issued by your CheckSphere administrator."}
        </Text>
        {error ? <Banner message={error} tone="error" /> : null}
        <TextField
          label={role === "agent" ? "Agent ID / Mobile / Email" : "Email"}
          value={identifier}
          onChange={setIdentifier}
          testID="login-identifier-input"
          keyboardType={role === "agent" ? "default" : "email-address"}
        />
        <TextField label="Password" value={password} onChange={setPassword} testID="login-password-input" secure />
        <Btn label="Sign In" onPress={onLogin} loading={loading} testID="login-submit-button" full />
        {Platform.OS === "web" ? (
          <Pressable onPress={() => router.replace("/")} testID="login-change-role-link" style={{ alignSelf: "center", padding: spacing.sm }}>
            <Text style={styles.link}>Choose a different login type</Text>
          </Pressable>
        ) : null}
        <Text style={styles.footnote}>
          Accounts are created by the Super Admin. A temporary password must be changed at first login.
        </Text>
      </View>
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  hero: { alignItems: "center", marginTop: spacing.xxl, marginBottom: spacing.xl },
  logo: { width: 72, height: 72, borderRadius: 20, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  heroTitle: { fontSize: 30, fontWeight: "800", color: colors.brandPrimary, fontFamily: typography.fontFamily, marginTop: spacing.md },
  heroSub: { color: colors.muted, marginTop: 4, fontSize: 15 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 20, borderWidth: 1, borderColor: colors.border,
    padding: spacing.xl, maxWidth: 460, width: "100%", alignSelf: "center", gap: spacing.sm,
  },
  title: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, fontFamily: typography.fontFamily },
  sub: { color: colors.muted, fontSize: 14, marginBottom: spacing.sm },
  link: { color: colors.info, fontWeight: "700", fontSize: 14 },
  footnote: { color: colors.muted, fontSize: typography.scale.sm, marginTop: spacing.sm, lineHeight: 18 },
}));
