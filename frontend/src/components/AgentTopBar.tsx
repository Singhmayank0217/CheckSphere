// Agent app top bar: hamburger menu, screen title and notification bell with unread count.
import { useEffect } from "react";
import { Platform, Pressable, Text, View } from "react-native";
import * as Notifications from "expo-notifications";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api } from "@/src/api";
import { AgentMenuButton } from "@/src/components/AgentMenu";
import { showNewPhoneAlerts } from "@/src/utils/phoneAlerts";
import { makeStyles, spacing, typography, useTheme } from "@/src/theme";

export function useAgentNotifications() {
  const router = useRouter();
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => api<any>("/notifications"), refetchInterval: 30000 });
  useEffect(() => {
    if (q.data?.items) showNewPhoneAlerts(q.data.items).catch(() => null);
  }, [q.data]);
  useEffect(() => {
    if (Platform.OS === "web") return;
    const sub = Notifications.addNotificationResponseReceivedListener((r) => {
      const caseId = r.notification.request.content.data?.case_id as string | undefined;
      router.push(caseId ? `/case/${caseId}` : "/notifications");
    });
    return () => sub.remove();
  }, [router]);
  return q;
}

export function AgentTopBar({ title }: { title: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const q = useAgentNotifications();
  const unread = q.data?.unread ?? 0;
  return (
    <View style={styles.bar} testID="agent-top-bar">
      <AgentMenuButton />
      <Text style={styles.title} numberOfLines={1}>{title}</Text>
      <Pressable onPress={() => router.push("/notifications")} hitSlop={8} style={styles.bell} testID="agent-bell-btn">
        <Ionicons name="notifications-outline" size={24} color={colors.onSurface} />
        {unread > 0 ? (
          <View style={styles.badge} testID="agent-bell-badge"><Text style={styles.badgeText}>{unread > 99 ? "99+" : unread}</Text></View>
        ) : null}
      </Pressable>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  bar: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 52, marginBottom: spacing.sm },
  title: { flex: 1, fontSize: typography.scale.xl, fontWeight: "800", color: colors.onSurface, fontFamily: typography.fontFamily },
  bell: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  badge: { position: "absolute", top: 4, right: 2, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: colors.error, alignItems: "center", justifyContent: "center", paddingHorizontal: 4 },
  badgeText: { color: colors.onError, fontSize: 11, fontWeight: "800" },
}));
