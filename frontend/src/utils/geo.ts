// GPS capture via expo-location with contextual permission handling.
import * as Location from "expo-location";

export type GpsResult =
  | { ok: true; lat: number; lon: number; accuracy: number }
  | { ok: false; reason: "denied" | "unavailable"; canAskAgain: boolean; message: string };

export async function getGps(): Promise<GpsResult> {
  try {
    const { status, canAskAgain } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") {
      return {
        ok: false,
        reason: "denied",
        canAskAgain,
        message: canAskAgain
          ? "Location permission is needed to record visit evidence."
          : "Location permission is blocked. Enable it in Settings to record visit evidence.",
      };
    }
    const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
    return {
      ok: true,
      lat: pos.coords.latitude,
      lon: pos.coords.longitude,
      accuracy: Math.round((pos.coords.accuracy ?? 0) * 10) / 10,
    };
  } catch {
    return { ok: false, reason: "unavailable", canAskAgain: true, message: "Could not read your location. Try again outdoors." };
  }
}
