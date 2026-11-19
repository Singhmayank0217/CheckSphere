// Remote push notifications for agents (Android): register this phone's Expo push token with the backend after
// login, re-register when the token changes, and unregister before logout. The backend only pushes two events
// (new case assigned / case reassigned) with fixed, non-personal text. Never throws: push is best effort, and the
// in-app notifications keep working without it.
import { Platform } from "react-native";
import Constants from "expo-constants";
import * as Notifications from "expo-notifications";

import { api, getDeviceId } from "@/src/api";
import { storage } from "@/src/utils/storage";

export const PUSH_CHANNEL = "assignments"; // must match backend/push_service.py CHANNEL_ID
const REG_KEY = "push_registration"; // JSON {token, userId} of the token registered for the signed-in agent

type Registration = { token: string; userId: string };

async function readRegistration(): Promise<Registration | null> {
  const raw = await storage.getItem<string | null>(REG_KEY, null);
  if (!raw) return null;
  try {
    const r = JSON.parse(raw);
    return r && typeof r.token === "string" && typeof r.userId === "string" ? r : null;
  } catch {
    return null;
  }
}

/** True when this phone currently has a push token registered for a signed-in agent. */
export async function isPushRegistered(): Promise<boolean> {
  return (await readRegistration()) !== null;
}

function projectId(): string | undefined {
  return (Constants.expoConfig?.extra as any)?.eas?.projectId ?? (Constants as any).easConfig?.projectId;
}

export async function ensurePushChannel() {
  if (Platform.OS !== "android") return;
  await Notifications.setNotificationChannelAsync(PUSH_CHANNEL, {
    name: "Case assignments",
    importance: Notifications.AndroidImportance.HIGH,
  });
}

export type PushResult = "registered" | "skipped" | "denied" | "failed";

// Loop guard. On Android, every getDevicePushTokenAsync() call (also made inside getExpoPushTokenAsync) emits the
// "push token changed" event, even when the token did not change. The token listener below must therefore ignore
// tokens this module fetched itself, or registering would trigger itself forever. Registrations are also
// single-flight: concurrent callers share the one in progress.
let knownDeviceToken: string | null = null;
let inFlight: { userId: string; promise: Promise<PushResult> } | null = null;

/** Register this phone for assignment pushes. Agents on Android only; safe to call repeatedly. */
export function registerForPush(user: { id: string; role: string } | null): Promise<PushResult> {
  if (Platform.OS !== "android" || !user || user.role !== "agent") return Promise.resolve("skipped");
  if (inFlight && inFlight.userId === user.id) return inFlight.promise;
  const promise = doRegister(user).finally(() => {
    if (inFlight?.promise === promise) inFlight = null;
  });
  inFlight = { userId: user.id, promise };
  return promise;
}

async function doRegister(user: { id: string; role: string }): Promise<PushResult> {
  const pid = projectId();
  if (!pid) return "failed";
  try {
    await ensurePushChannel();
    let perm = await Notifications.getPermissionsAsync();
    if (!perm.granted && perm.canAskAgain) perm = await Notifications.requestPermissionsAsync();
    if (!perm.granted) return "denied";
    const device = await Notifications.getDevicePushTokenAsync();
    knownDeviceToken = typeof device.data === "string" ? device.data : null;
    // pass the device token in, so the Expo token lookup does not fetch (and emit) it a second time
    const token = (await Notifications.getExpoPushTokenAsync({ projectId: pid, devicePushToken: device })).data;
    const previous = await readRegistration();
    await api("/push/register", {
      method: "POST",
      body: {
        token,
        device_id: await getDeviceId(),
        platform: "android",
        app_variant: Constants.expoConfig?.android?.package ?? null,
      },
    });
    if (previous && previous.token !== token) {
      await api("/push/unregister", { method: "POST", body: { token: previous.token } }).catch(() => null);
    }
    await storage.setItem(REG_KEY, JSON.stringify({ token, userId: user.id }));
    return "registered";
  } catch {
    return "failed";
  }
}

/** Remove this phone's token from the backend (call while the session is still valid, before /auth/logout). */
export async function unregisterPush(): Promise<void> {
  const reg = await readRegistration();
  await storage.removeItem(REG_KEY);
  inFlight = null;
  if (!reg) return;
  try {
    await api("/push/unregister", { method: "POST", body: { token: reg.token } });
  } catch {
    // the session may already be revoked; the backend never pushes to a revoked session anyway
  }
}

/** Re-register when Android rotates the device (FCM) token. Returns an unsubscribe function. */
export function onPushTokenChange(user: { id: string; role: string } | null): () => void {
  if (Platform.OS !== "android" || !user || user.role !== "agent") return () => {};
  const sub = Notifications.addPushTokenListener((device) => {
    // Ignore the event our own token fetch just emitted (same token), and any event while a registration runs.
    if (inFlight || (typeof device?.data === "string" && device.data === knownDeviceToken)) return;
    registerForPush(user).catch(() => null);
  });
  return () => sub.remove();
}
