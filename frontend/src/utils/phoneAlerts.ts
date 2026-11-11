// Shows CheckSphere alerts in the phone's notification centre (local notifications).
// Alerts appear while the app is open or running in the background; native only.
import { Platform } from "react-native";
import * as Notifications from "expo-notifications";

import { storage } from "@/src/utils/storage";

const SEEN_KEY = "phone_alert_seen_ids";

if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: true }),
  });
}

export type AlertPermission = "granted" | "undetermined" | "denied" | "blocked" | "unsupported";

export async function getAlertPermission(): Promise<AlertPermission> {
  if (Platform.OS === "web") return "unsupported";
  const p = await Notifications.getPermissionsAsync();
  if (p.granted) return "granted";
  if (p.status === "undetermined") return "undetermined";
  return p.canAskAgain ? "denied" : "blocked";
}

export async function requestAlertPermission(): Promise<AlertPermission> {
  if (Platform.OS === "web") return "unsupported";
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("alerts", { name: "Case alerts", importance: Notifications.AndroidImportance.HIGH });
  }
  const p = await Notifications.requestPermissionsAsync();
  if (p.granted) return "granted";
  return p.canAskAgain ? "denied" : "blocked";
}

// Push each new (unacknowledged, not yet shown) in-app notification to the phone's notification centre.
export async function showNewPhoneAlerts(items: { id: string; title: string; body: string; case_id?: string | null; acknowledged_at?: string | null }[]) {
  if (Platform.OS === "web" || !items.length) return;
  const raw = await storage.getItem<string[] | null>(SEEN_KEY, null);
  const first = raw === null;
  const seen = new Set<string>(raw ?? []);
  const fresh = items.filter((n) => !seen.has(n.id) && !n.acknowledged_at);
  items.forEach((n) => seen.add(n.id));
  await storage.setItem(SEEN_KEY, [...seen].slice(-300));
  // On the very first run only remember existing items, so old alerts don't flood the phone.
  if (first || !fresh.length || (await getAlertPermission()) !== "granted") return;
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("alerts", { name: "Case alerts", importance: Notifications.AndroidImportance.HIGH });
  }
  for (const n of fresh.slice(0, 5)) {
    await Notifications.scheduleNotificationAsync({
      content: { title: n.title, body: n.body, data: { case_id: n.case_id ?? null } },
      trigger: Platform.OS === "android" ? { channelId: "alerts" } as any : null,
    });
  }
}
