import { useEffect } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { useRouter } from "expo-router";

import { makeStyles, typography } from "@/src/theme";
import { useSession } from "@/src/session";

export default function Index() {
  const { ready, user } = useSession();
  const router = useRouter();
  const styles = useStyles();

  useEffect(() => {
    if (!ready) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (user.must_change_password) {
      router.replace("/change-password");
      return;
    }
    if (user.role === "agent") {
      router.replace("/(agent)/home");
    } else {
      router.replace("/(admin)/dashboard");
    }
  }, [ready, user, router]);

  return (
    <View style={styles.container} testID="splash">
      <Text style={styles.logo}>CheckSphere</Text>
      <Text style={styles.tagline}>Field Verification Management</Text>
      <ActivityIndicator style={{ marginTop: 24 }} />
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  container: { flex: 1, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  logo: { fontSize: 32, fontWeight: "800", color: colors.onBrandPrimary, fontFamily: typography.fontFamily },
  tagline: { color: colors.onBrandPrimary, opacity: 0.8, marginTop: 6 },
}));
