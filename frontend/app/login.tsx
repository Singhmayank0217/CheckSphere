import { useState } from "react";
import { Pressable, Text, View } from "react-native";
import { useRouter } from "expo-router";

import { loginRequest } from "@/src/api";
import { TextField } from "@/src/components/fields";
import { Banner, Btn, Screen } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { makeStyles, spacing, typography } from "@/src/theme";

export default function Login() {
  const { signIn } = useSession();
  const router = useRouter();
  const styles = useStyles();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const onLogin = async () => {
    if (!identifier.trim() || !password) {
      setError("Enter your Agent ID / email and password.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await loginRequest(identifier.trim(), password);
      await signIn(data);
      if (data.user.must_change_password) {
        router.replace("/change-password");
      } else if (data.user.role === "agent") {
        router.replace("/(agent)/home");
      } else {
        router.replace("/(admin)/dashboard");
      }
    } catch (e: any) {
      setError(e?.message ?? "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Screen testID="login-screen">
      <View style={styles.hero}>
        <Text style={styles.heroTitle}>CheckSphere</Text>
        <Text style={styles.heroSub}>Field Verification Management System</Text>
      </View>
      <View style={styles.card}>
        <Text style={styles.title}>Sign in</Text>
        <Text style={styles.sub}>
          Use the Agent ID / email and temporary password provided by your CheckSphere administrator.
        </Text>
        {error ? <Banner message={error} tone="error" /> : null}
        <TextField
          label="Agent ID / Email / Mobile"
          value={identifier}
          onChange={(v) => setIdentifier(v)}
          testID="login-identifier-input"
          autoCapitalize="none"
        />
        <TextField
          label="Password"
          value={password}
          onChange={(v) => setPassword(v)}
          testID="login-password-input"
        />
        <Btn label="Sign In" onPress={onLogin} loading={loading} testID="login-submit-button" full />
        <Text style={styles.footnote}>
          Accounts are created by the Super Admin. A temporary password is shared separately and must be
          changed at first login.
        </Text>
      </View>
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  hero: { alignItems: "center", marginVertical: spacing.xxl },
  heroTitle: { fontSize: 30, fontWeight: "800", color: colors.brandPrimary, fontFamily: typography.fontFamily },
  heroSub: { color: colors.muted, marginTop: 4 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 20, borderWidth: 1, borderColor: colors.border,
    padding: spacing.xl, maxWidth: 460, width: "100%", alignSelf: "center", gap: spacing.sm,
  },
  title: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, fontFamily: typography.fontFamily },
  sub: { color: colors.muted, fontSize: typography.scale.sm, marginBottom: spacing.sm },
  footnote: { color: colors.muted, fontSize: typography.scale.sm, marginTop: spacing.sm, lineHeight: 18 },
}));
