import { useState } from "react";
import { useRouter } from "expo-router";
import { Text, View } from "react-native";

import { api } from "@/src/api";
import { TextField } from "@/src/components/fields";
import { Banner, Btn, Screen } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { makeStyles, spacing, typography } from "@/src/theme";

export default function ChangePassword() {
  const { user, refresh, signOut } = useSession();
  const router = useRouter();
  const styles = useStyles();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const onSubmit = async () => {
    setError("");
    if (next.length < 8) {
      setError("New password must be at least 8 characters.");
      return;
    }
    if (next !== confirm) {
      setError("New password and confirmation do not match.");
      return;
    }
    setLoading(true);
    try {
      await api("/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } });
      await refresh();
      if (user?.role === "agent") {
        router.replace("/(agent)/home");
      } else {
        router.replace("/(admin)/dashboard");
      }
    } catch (e: any) {
      setError(e?.message ?? "Could not change password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Screen testID="change-password-screen">
      <View style={styles.card}>
        <Text style={styles.title}>Change your password</Text>
        <Banner
          tone="warning"
          message="For security, you must set a new password before you can continue. The temporary password shared by your administrator will stop working."
        />
        {error ? <Banner message={error} tone="error" /> : null}
        <TextField label="Current password" value={current} onChange={setCurrent} testID="change-current-input" />
        <TextField label="New password" value={next} onChange={setNext} testID="change-new-input" />
        <TextField label="Confirm new password" value={confirm} onChange={setConfirm} testID="change-confirm-input" />
        <Btn label="Set New Password" onPress={onSubmit} loading={loading} testID="change-submit-button" full />
      </View>
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 20, borderWidth: 1, borderColor: colors.border,
    padding: spacing.xl, maxWidth: 460, width: "100%", alignSelf: "center", gap: spacing.sm, marginTop: spacing.xxl,
  },
  title: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, fontFamily: typography.fontFamily },
}));
