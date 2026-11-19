// Shows CheckSphere alerts in the phone's notification centre (local notifications).
// Alerts appear while the app is open or running in the background; native only.
//
// Remote pushes (new case assigned / case reassigned) carry the id of the matching in-app notification. One id is
// shown on the phone at most once, whichever arrives first (remote push or local alert), so an open app never shows
// the same assignment twice. A queued push does NOT suppress the local alert: the local alert waits a short grace
// period for the push and is then shown anyway unless the push is actually in the notification tray, so the agent
// is still alerted when remote delivery fails.
//
// Privacy: the phone (including the lock screen) only ever shows the notification title and a generic line, never
// case or applicant details.
import { Platform } from "react-native";
import * as Notifications from "expo-notifications";

import { isPushRegistered } from "@/src/utils/push";
import { storage } from "@/src/utils/storage";

const SEEN_KEY = "phone_alert_seen_ids";
const SEEN_MAX = 300;
const PUSH_GRACE_MS = 90 * 1000; // how long a local alert waits for a queued remote push before showing anyway
export const GENERIC_ALERT_BODY = "Open CheckSphere to view the details.";

// ---- one shared "already shown on this phone" list (read-modify-write serialised)
let seenChain: Promise<unknown> = Promise.resolve();
function withSeen<T>(fn: (seen: Set<string>, first: boolean) => Promise<T> | T): Promise<T> {
  const run = seenChain.then(async () => {
    const raw = await storage.getItem<string | null>(SEEN_KEY, null);
    let list: string[] | null = null;
    const value: unknown = raw;
    if (Array.isArray(value)) list = value as string[]; // older app builds stored the array itself
    else if (typeof value === "string") {
      try {
        const parsed = JSON.parse(value);
        list = Array.isArray(parsed) ? parsed : [];
      } catch {
        list = [];
      }
    }
    const seen = new Set<string>(list ?? []);
    const result = await fn(seen, list === null);
    await storage.setItem(SEEN_KEY, JSON.stringify([...seen].slice(-SEEN_MAX)));
    return result;
  });
  seenChain = run.catch(() => null);
  return run;
}

/** Mark in-app notification ids as already shown on this phone. Returns the ids that were not seen before. */
export function markPhoneAlertsSeen(ids: (string | null | undefined)[]): Promise<string[]> {
  const clean = ids.filter((i): i is string => typeof i === "string" && i.length > 0);
  if (!clean.length) return Promise.resolve([]);
  return withSeen((seen) => {
    const fresh = clean.filter((i) => !seen.has(i));
    fresh.forEach((i) => seen.add(i));
    return fresh;
  });
}

const notificationIdOf = (n: Notifications.Notification) => {
  const v = n.request.content.data?.notification_id;
  return typeof v === "string" ? v : null;
};
const isRemotePush = (n: Notifications.Notification) => (n.request.trigger as any)?.type === "push";

const SHOW = { shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: true };
const HIDE = { shouldShowBanner: false, shouldShowList: false, shouldPlaySound: false, shouldSetBadge: false };

if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    // Called for notifications arriving while the app is in the foreground. A remote push whose in-app notification
    // was already shown as a local alert is hidden; otherwise it is shown and the local alert will not repeat it.
    handleNotification: async (n) => {
      const id = isRemotePush(n) ? notificationIdOf(n) : null;
      if (!id) return SHOW;
      const fresh = await markPhoneAlertsSeen([id]);
      return fresh.length ? SHOW : HIDE;
    },
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

type InAppItem = {
  id: string;
  title: string;
  body?: string;
  case_id?: string | null;
  acknowledged_at?: string | null;
  created_at?: string | null;
  push_queued?: boolean;
};

// ids of in-app notifications whose remote push is currently in this phone's notification tray
async function pushesInTray(): Promise<string[]> {
  try {
    const presented = await Notifications.getPresentedNotificationsAsync();
    return presented.filter(isRemotePush).map(notificationIdOf).filter((i): i is string => !!i);
  } catch {
    return [];
  }
}

// Show each new (unacknowledged, not yet shown) in-app notification in the phone's notification centre.
export async function showNewPhoneAlerts(items: InAppItem[]) {
  if (Platform.OS === "web" || !items.length) return;
  await markPhoneAlertsSeen(await pushesInTray()); // a delivered push already alerted the agent
  const registered = await isPushRegistered();
  const now = Date.now();
  const waitingForPush = (n: InAppItem) => {
    if (!registered || !n.push_queued || !n.created_at) return false;
    const t = Date.parse(n.created_at);
    return Number.isFinite(t) && now - t < PUSH_GRACE_MS;
  };
  const fresh = await withSeen((seen, first) => {
    const candidates = items.filter((n) => !seen.has(n.id) && !n.acknowledged_at);
    // remember everything except items still waiting for their remote push (they are re-checked on the next poll)
    items.forEach((n) => {
      if (first || !candidates.includes(n) || !waitingForPush(n)) seen.add(n.id);
    });
    // On the very first run only remember existing items, so old alerts don't flood the phone.
    return first ? [] : candidates.filter((n) => !waitingForPush(n));
  });
  if (!fresh.length || (await getAlertPermission()) !== "granted") return;
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("alerts", { name: "Case alerts", importance: Notifications.AndroidImportance.HIGH });
  }
  for (const n of fresh.slice(0, 5)) {
    await Notifications.scheduleNotificationAsync({
      content: { title: n.title, body: GENERIC_ALERT_BODY, data: { case_id: n.case_id ?? null, notification_id: n.id } },
      trigger: Platform.OS === "android" ? ({ channelId: "alerts" } as any) : null,
    });
  }
}
