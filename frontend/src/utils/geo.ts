// GPS capture via expo-location. Coordinates always come from the device's location services;
// the app never lets the agent type or edit them.
import { Linking, Platform } from "react-native";
import * as Location from "expo-location";

export type GpsStatus = "ok" | "poor_accuracy" | "denied" | "services_disabled" | "unavailable" | "timeout";

export type GpsFix = {
  ok: true;
  status: "ok" | "poor_accuracy";
  lat: number;
  lon: number;
  accuracy: number;
  mocked: boolean;
  fixAt: string; // ISO time the position was obtained
};
export type GpsFailure = {
  ok: false;
  status: "denied" | "services_disabled" | "unavailable" | "timeout";
  reason: GpsFailure["status"]; // kept for existing callers
  canAskAgain: boolean;
  message: string;
};
export type GpsResult = GpsFix | GpsFailure;

export const GPS_HELP: Record<GpsStatus, string> = {
  ok: "Location captured from this phone's GPS.",
  poor_accuracy: "GPS accuracy is poor. Move outdoors or near a window and tap Retry GPS. If you continue, the photo is flagged for supervisor review.",
  denied: "Location permission is off for CheckSphere. Allow location access to capture verification photos.",
  services_disabled: "Location (GPS) is turned off on this phone. Turn on Location in phone settings, then tap Retry GPS.",
  unavailable: "The phone could not get a GPS position. Move outdoors, wait a few seconds and tap Retry GPS.",
  timeout: "GPS took too long to respond. Move outdoors or near a window and tap Retry GPS.",
};

const fail = (status: GpsFailure["status"], canAskAgain = true): GpsFailure => ({
  ok: false, status, reason: status, canAskAgain, message: GPS_HELP[status],
});

export async function ensureLocationPermission(): Promise<GpsFailure | null> {
  const { status, canAskAgain } = await Location.requestForegroundPermissionsAsync();
  if (status !== "granted") return fail("denied", canAskAgain);
  if (Platform.OS !== "web" && !(await Location.hasServicesEnabledAsync())) return fail("services_disabled");
  return null;
}

// A fresh fix at the moment of capture. `poorAccuracyM` decides ok vs poor_accuracy (Super Admin setting).
export async function getGps(opts: { timeoutMs?: number; poorAccuracyM?: number } = {}): Promise<GpsResult> {
  const timeoutMs = opts.timeoutMs ?? 15000;
  try {
    const blocked = await ensureLocationPermission();
    if (blocked) return blocked;
    const pos = await Promise.race([
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High }),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), timeoutMs)),
    ]);
    if (!pos) return fail("timeout");
    const accuracy = Math.round((pos.coords.accuracy ?? 9999) * 10) / 10;
    const limit = opts.poorAccuracyM ?? 150;
    return {
      ok: true,
      status: accuracy > limit ? "poor_accuracy" : "ok",
      lat: pos.coords.latitude,
      lon: pos.coords.longitude,
      accuracy,
      mocked: !!(pos as any).mocked,
      fixAt: new Date(pos.timestamp || Date.now()).toISOString(),
    };
  } catch {
    if (Platform.OS !== "web") {
      try {
        if (!(await Location.hasServicesEnabledAsync())) return fail("services_disabled");
      } catch {
        // ignore
      }
    }
    return fail("unavailable");
  }
}

// Great-circle distance in metres (same haversine formula as the backend).
export function distanceM(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const r = 6371000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dp = toRad(lat2 - lat1);
  const dl = toRad(lon2 - lon1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dl / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(a));
}

export function openLocationSettings() {
  if (Platform.OS === "android") {
    Linking.sendIntent("android.settings.LOCATION_SOURCE_SETTINGS").catch(() => Linking.openSettings());
  } else {
    Linking.openSettings();
  }
}

// Display helpers: stored times are UTC; the app shows Indian Standard Time.
export function fmtIST(v?: string | number | Date | null): string {
  if (!v) return "—";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  const ist = new Date(d.getTime() + 330 * 60000);
  const p = (n: number) => String(n).padStart(2, "0");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  let h = ist.getUTCHours();
  const ampm = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${p(ist.getUTCDate())}-${months[ist.getUTCMonth()]}-${ist.getUTCFullYear()} ${p(h)}:${p(ist.getUTCMinutes())}:${p(ist.getUTCSeconds())} ${ampm} IST`;
}

// ---- distance check: same rules as the server (core.assess_location) so the agent sees the same answer.
export const REFERENCE_UNCERTAINTY_M: Record<string, number> = { exact: 0, street: 75, locality: 1500, pincode: 3000 };
export type LocationCheck = {
  status: "within" | "uncertain" | "outside" | "no_reference";
  distanceM: number | null;
  marginM: number | null;
  explanation: string;
};

export function assessLocation(ref: { lat?: number | null; lon?: number | null; precision?: string | null },
  fix: { lat: number; lon: number; accuracy?: number | null }, allowedM: number, maxAccuracyM = 150): LocationCheck {
  const hasRef = ref.lat != null && ref.lon != null;
  const precision = hasRef ? ref.precision || "exact" : null;
  if (!precision || !(precision in REFERENCE_UNCERTAINTY_M)) {
    return { status: "no_reference", distanceM: null, marginM: null,
      explanation: precision ? "The case location is only known roughly (region level), so the distance cannot be checked."
        : "The case has no reference location, so the distance cannot be checked. Your supervisor will review it." };
  }
  const d = distanceM(ref.lat as number, ref.lon as number, fix.lat, fix.lon);
  const acc = Math.min(fix.accuracy ?? 0, maxAccuracyM); // a very poor fix must not excuse a distant photo
  const refU = REFERENCE_UNCERTAINTY_M[precision];
  const margin = acc + refU;
  if (d <= allowedM) return { status: "within", distanceM: d, marginM: margin, explanation: `Within ${Math.round(allowedM)} m of the case location.` };
  if (d - margin <= allowedM) {
    const parts = [
      refU ? `the case location is approximate (${precision} level, up to about ${refU} m off)` : "",
      acc ? `your GPS accuracy is ±${Math.round(acc)} m` : "",
    ].filter(Boolean);
    return { status: "uncertain", distanceM: d, marginM: margin,
      explanation: `Measured about ${roundDistance(d)} m away, but ${parts.join(" and ")}, so you may be within the allowed ${Math.round(allowedM)} m. No reason is needed; your supervisor will see it marked as uncertain.` };
  }
  return { status: "outside", distanceM: d, marginM: margin,
    explanation: `You are about ${roundDistance(d)} m from the case location (allowed ${Math.round(allowedM)} m), outside even after allowing ±${Math.round(margin)} m for GPS accuracy and case-location precision.` };
}

// How the case's assigned/reference location was established, in words (never the photo's own position).
const PRECISION_WORDS: Record<string, string> = {
  exact: "exact point", street: "street level (±75 m)", locality: "locality level (±1.5 km)", pincode: "PIN-code area only (±3 km)",
};
const SOURCE_WORDS: Record<string, string> = {
  manual: "pinned by a supervisor", confirmed_candidate: "confirmed by a supervisor", geocoded: "automatic address lookup",
};
export function referenceSummary(c: any): { ok: boolean; text: string } {
  if (c?.assigned_lat == null || c?.assigned_lon == null) {
    return { ok: false, text: `Case reference location missing: ${c?.location_problem ?? "the assigned address has not been located."} Distance NOT checked; the supervisor will review.` };
  }
  const p = PRECISION_WORDS[c.location_precision ?? "exact"] ?? c.location_precision;
  const s = SOURCE_WORDS[c.location_source ?? ""] ?? "set on the case";
  return { ok: true, text: `Case reference location: ${p}, ${s}.` };
}

// "22.62, 88.35", or a Google Maps link (".../@22.62,88.35,17z", "?q=22.62,88.35") -> coordinates (null if none / invalid)
export function parseLatLon(text: string): { lat: number; lon: number } | null {
  const t = (text ?? "").trim();
  const m = t.match(/@(-?\d{1,2}\.\d+),\s*(-?\d{1,3}\.\d+)/)
    ?? t.match(/[?&](?:q|query|ll|destination)=(-?\d{1,2}\.\d+)(?:,|%2C)\s*(-?\d{1,3}\.\d+)/i)
    ?? t.match(/^(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)$/);
  if (!m) return null;
  const lat = Number(m[1]), lon = Number(m[2]);
  return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? { lat, lon } : null;
}

// Opens the point in the user's own maps app / Google Maps (a supported, keyless Maps URL; no tiles are fetched here).
export const mapsUrl = (lat: number, lon: number) => `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`;

// Display rounding so the shown distance doesn't flicker with metre-level GPS noise.
export function roundDistance(m: number): number {
  return m < 1000 ? Math.round(m / 10) * 10 : Math.round(m / 50) * 50;
}

// Keep GPS running while the camera is open, so a fresh fix is already available when the shutter is pressed
// (a cold getCurrentPosition request can take 5-15 s). Returns a stop function.
export async function watchGps(onFix: (f: GpsFix) => void, poorAccuracyM = 150): Promise<() => void> {
  try {
    const sub = await Location.watchPositionAsync(
      { accuracy: Location.Accuracy.High, timeInterval: 2000, distanceInterval: 0 },
      (pos) => {
        const accuracy = Math.round((pos.coords.accuracy ?? 9999) * 10) / 10;
        onFix({ ok: true, status: accuracy > poorAccuracyM ? "poor_accuracy" : "ok", lat: pos.coords.latitude,
          lon: pos.coords.longitude, accuracy, mocked: !!(pos as any).mocked, fixAt: new Date(pos.timestamp || Date.now()).toISOString() });
      },
    );
    return () => sub.remove();
  } catch {
    return () => {};
  }
}
