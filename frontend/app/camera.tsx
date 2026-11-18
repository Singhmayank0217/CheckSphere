// In-app camera capture — gallery uploads are blocked for visit evidence.
// Capture time and GPS are taken from the device at the moment the shutter is pressed; the agent
// cannot type or edit either. Photos are saved on the phone first and uploaded through a retrying queue.
import { useEffect, useRef, useState } from "react";
import { Linking, Pressable, Text, TextInput, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { Image } from "expo-image";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { Banner, Btn, Card, Loading, showToast } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { assessLocation, ensureLocationPermission, fmtIST, getGps, GpsFix, GPS_HELP, GpsResult, openLocationSettings, referenceSummary, roundDistance, watchGps } from "@/src/utils/geo";
import { discardPrepared, discardUpload, enqueueAndUpload, PHOTO_UNAVAILABLE, PhotoUnavailableError, preparePhoto, PreparedPhoto, retryUpload } from "@/src/utils/pendingUploads";
import { makeStyles, spacing, typography } from "@/src/theme";

type Shot = { uri: string; photo: PreparedPhoto | null; capturedAt: string; gps: GpsResult | null; gpsSource?: string; readyMs?: number };

// A continuous fix is used at the shutter only if it is this fresh; otherwise a new fix is requested.
const FRESH_FIX_MS = 15000;
// Evidence photos are taken at up to ~8.5 MP: plenty for a legible watermarked photo (the server keeps at most 4096 px
// per side) while the camera's own JPEG processing stays fast. Phones with 50-200 MP sensors otherwise take seconds.
const MAX_PICTURE_PIXELS = 8_500_000;

function pickPictureSize(sizes: string[]): string | undefined {
  const parsed = sizes
    .map((s) => { const m = /^(\d+)x(\d+)$/.exec(s); return m ? { s, px: Number(m[1]) * Number(m[2]) } : null; })
    .filter((x): x is { s: string; px: number } => !!x && x.px <= MAX_PICTURE_PIXELS)
    .sort((a, b) => b.px - a.px);
  return parsed[0]?.s;
}

export default function CameraCapture() {
  const { caseId, slot, label, camera } = useLocalSearchParams<{ caseId: string; slot: string; label?: string; camera?: string }>();
  const { token } = useSession();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const styles = useStyles();

  const [permission, requestPermission] = useCameraPermissions();
  const [facing, setFacing] = useState<"front" | "back">(camera === "front" || slot === "selfie" ? "front" : "back");
  const [shot, setShot] = useState<Shot | null>(null);
  const [shooting, setShooting] = useState(false);
  const [gpsBusy, setGpsBusy] = useState(false);
  const [preflight, setPreflight] = useState<GpsResult | null>(null);
  const [reason, setReason] = useState("");
  const [uploading, setUploading] = useState(false);
  const [serverAsk, setServerAsk] = useState<{ uploadId: string; message: string } | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [pictureSize, setPictureSize] = useState<string | undefined>(undefined);
  const cameraRef = useRef<any>(null);
  const liveFix = useRef<GpsFix | null>(null);
  // Private copy made at the shutter; deleted if the agent retakes/closes without using it (never once queued).
  const unqueued = useRef<PreparedPhoto | null>(null);
  useEffect(() => () => discardPrepared(unqueued.current), []);

  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: () => api<any>("/settings") });
  const caseQ = useQuery({ queryKey: ["case", caseId], queryFn: () => api<any>(`/cases/${caseId}`), enabled: !!caseId });
  const allowedM = Number(settingsQ.data?.flag_distance_m ?? 500);
  const accuracyLimit = Number(settingsQ.data?.flag_accuracy_m ?? 150);
  const c = caseQ.data;

  // Warm up GPS and check permission / location services before the agent shoots.
  const checkGps = async () => {
    setGpsBusy(true);
    const blocked = await ensureLocationPermission().catch(() => null);
    setPreflight(blocked ?? (await getGps({ timeoutMs: 15000, poorAccuracyM: accuracyLimit })));
    setGpsBusy(false);
  };
  useEffect(() => {
    // one-off permission/GPS check when the camera opens (async; state is set after the awaits)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    checkGps();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const locationBlocked = preflight && !preflight.ok && (preflight.status === "denied" || preflight.status === "services_disabled");

  // Keep GPS warm while the camera screen is open (stopped on close), so the shutter rarely waits for a fix.
  const permissionOk = !!preflight && (preflight.ok || (preflight.status !== "denied" && preflight.status !== "services_disabled"));
  useEffect(() => {
    if (!permissionOk) return;
    let stop: (() => void) | null = null;
    let cancelled = false;
    watchGps((f) => { liveFix.current = f; }, accuracyLimit).then((s) => { if (cancelled) s(); else stop = s; });
    return () => { cancelled = true; stop?.(); };
  }, [permissionOk, accuracyLimit]);

  const onCameraReady = async () => {
    try {
      const sizes: string[] = (await cameraRef.current?.getAvailablePictureSizesAsync?.()) ?? [];
      const pick = pickPictureSize(sizes);
      if (pick) setPictureSize(pick);
    } catch {
      // keep the camera default
    }
  };

  const shoot = async () => {
    if (shooting || locationBlocked) return;
    setShooting(true);
    const t0 = Date.now();
    const capturedAt = new Date(t0).toISOString(); // device time at the shutter press
    // GPS at the shutter: the continuous fix if it is fresh (<= 15 s old) and accurate; otherwise request a new one.
    const live = liveFix.current;
    const liveAge = live ? t0 - new Date(live.fixAt).getTime() : Infinity;
    const useLive = !!live && liveAge <= FRESH_FIX_MS && live.status === "ok";
    const gpsSource = useLive ? "watch" : "request";
    const gpsPromise: Promise<GpsResult> = useLive ? Promise.resolve(live!) : getGps({ timeoutMs: 15000, poorAccuracyM: accuracyLimit });
    try {
      const p = await (cameraRef.current as any)?.takePictureAsync({ quality: 0.8, exif: false });
      if (!p?.uri) throw new PhotoUnavailableError("no_uri");
      const tTaken = Date.now();
      // Show the photo at once; Use Photo unlocks when the private copy is verified and GPS is ready.
      setShot({ uri: p.uri, photo: null, capturedAt, gps: null, gpsSource });
      setReason("");
      setPreparing(true);
      setGpsBusy(true);
      // Copy out of the camera's temporary cache into private app storage IMMEDIATELY, and verify the bytes.
      const photo = await preparePhoto(p.uri);
      discardPrepared(unqueued.current);
      unqueued.current = photo;
      setPreparing(false);
      setShot({ uri: photo.uri, photo, capturedAt, gps: null, gpsSource });
      const g = await gpsPromise;
      const readyMs = Date.now() - t0;
      console.log(`[CheckSphere capture] shutter->Use Photo ${readyMs} ms (camera ${tTaken - t0} ms, gps ${gpsSource})`);
      setShot({ uri: photo.uri, photo, capturedAt, gps: g, gpsSource, readyMs });
    } catch (e) {
      setShot(null);
      showToast(e instanceof PhotoUnavailableError ? PHOTO_UNAVAILABLE : "Could not take picture", "error");
    } finally {
      setPreparing(false);
      setGpsBusy(false);
      setShooting(false);
    }
  };

  const retryShotGps = async () => {
    if (!shot) return;
    setGpsBusy(true);
    const g = await getGps({ timeoutMs: 20000, poorAccuracyM: accuracyLimit });
    setShot({ ...shot, gps: g, gpsSource: "request" });
    setGpsBusy(false);
  };

  const g = shot?.gps;
  const fix = g && g.ok ? g : null;
  const check = fix && c ? assessLocation({ lat: c.assigned_lat, lon: c.assigned_lon, precision: c.location_precision }, fix, allowedM, accuracyLimit) : null;
  const dist = check?.distanceM ?? null;
  const outside = check?.status === "outside";
  const noFix = !!g && !g.ok;
  const needsReason = outside || noFix;
  const reasonOk = reason.trim().length >= 5;

  const finishOk = () => {
    queryClient.invalidateQueries({ queryKey: ["report", caseId] });
    queryClient.invalidateQueries({ queryKey: ["case", caseId] });
    queryClient.invalidateQueries({ queryKey: ["pending-uploads", caseId] });
  };

  const usePhoto = async () => {
    if (!shot || !shot.photo || !g || uploading) return;
    if (needsReason && !reasonOk) {
      showToast("Enter a reason (at least 5 characters) before continuing", "error");
      return;
    }
    setUploading(true);
    try {
      const { item, outcome } = await enqueueAndUpload({
        caseId: caseId!, slot: slot ?? "document", label: label ?? slot ?? "Photo", photo: shot.photo,
        meta: {
          capturedAt: shot.capturedAt,
          gpsStatus: g.ok ? g.status : g.status,
          ...(g.ok ? { lat: g.lat, lon: g.lon, accuracy: g.accuracy, mocked: g.mocked, gpsFixAt: g.fixAt, gpsSource: shot.gpsSource } : {}),
          ...(needsReason ? { locationReason: reason.trim() } : {}),
        },
      }, token);
      unqueued.current = null; // now owned by the upload queue (removed only after the server confirms)
      finishOk();
      if (outcome.ok) {
        showToast("Photo captured and uploaded", "success");
        router.back();
      } else if (outcome.retryable) {
        showToast("Saved on this phone — it will upload automatically when the connection returns. Not yet counted as completed.", "info");
        router.back();
      } else if (outcome.detail?.code === "outside_allowed_distance" || outcome.detail?.code === "gps_reason_required") {
        setServerAsk({ uploadId: item.uploadId, message: outcome.message });
      } else {
        showToast(outcome.message, "error");
        await discardUpload(item.uploadId);
        finishOk();
      }
    } catch (e: any) {
      showToast(e?.message ?? "Could not save the photo", "error");
    } finally {
      setUploading(false);
    }
  };

  const sendWithServerReason = async () => {
    if (!serverAsk || !reasonOk) return;
    setUploading(true);
    const r = await retryUpload(serverAsk.uploadId, token, reason.trim());
    setUploading(false);
    finishOk();
    if (r?.ok) {
      showToast("Photo uploaded and flagged for supervisor review", "success");
      router.back();
    } else if (r && r.retryable) {
      showToast("Saved on this phone — it will upload automatically.", "info");
      router.back();
    } else {
      showToast(r?.message ?? "Upload failed", "error");
    }
  };

  // ---- camera permission states
  if (!permission) return <Loading label="Preparing camera…" />;
  if (!permission.granted) {
    const canAsk = permission.canAskAgain !== false;
    return (
      <View style={[styles.root, { paddingTop: insets.top + spacing.xl, paddingHorizontal: spacing.lg }]} testID="camera-permission-screen">
        <Card>
          <Text style={styles.permTitle}>Camera permission needed</Text>
          <Text style={styles.permText}>
            CheckSphere needs the camera to capture mandatory visit photos with time and GPS stamps.
            Gallery uploads are not allowed for evidence.
          </Text>
          {canAsk ? (
            <Btn label="Allow Camera" onPress={() => requestPermission()} testID="camera-permission-allow-btn" full />
          ) : (
            <Btn label="Open Settings" variant="secondary" onPress={() => Linking.openSettings()} testID="camera-open-settings-btn" full />
          )}
        </Card>
        <Btn label="Cancel" variant="ghost" onPress={() => router.back()} testID="camera-cancel-btn" />
      </View>
    );
  }

  // ---- location permission / services blocked: capture is not possible until fixed
  if (locationBlocked && !shot) {
    const f = preflight as Exclude<GpsResult, { ok: true }>;
    return (
      <View style={[styles.root, { paddingTop: insets.top + spacing.xl, paddingHorizontal: spacing.lg }]} testID="camera-location-blocked">
        <Card>
          <Text style={styles.permTitle}>{f.status === "denied" ? "Location permission needed" : "Turn on Location"}</Text>
          <Text style={styles.permText}>{GPS_HELP[f.status]}</Text>
          <Text style={styles.permText}>Verification photos must carry the phone&apos;s GPS position; it cannot be entered by hand.</Text>
          {f.status === "denied" && f.canAskAgain ? (
            <Btn label="Allow Location" onPress={checkGps} loading={gpsBusy} testID="location-allow-btn" full />
          ) : (
            <Btn label={f.status === "denied" ? "Open App Settings" : "Open Location Settings"} variant="secondary"
              onPress={() => (f.status === "denied" ? Linking.openSettings() : openLocationSettings())} testID="location-settings-btn" full />
          )}
          <Btn label="I've turned it on — check again" variant="ghost" onPress={checkGps} loading={gpsBusy} testID="location-recheck-btn" />
        </Card>
        <Btn label="Cancel" variant="ghost" onPress={() => router.back()} testID="camera-cancel-btn" />
      </View>
    );
  }

  const gpsLine = (r: GpsResult | null, busy: boolean) => {
    if (busy && !r) return "Getting GPS…";
    if (!r) return "GPS not checked yet";
    if (!r.ok) return `No GPS — ${r.status.replace("_", " ")}`;
    return `${r.lat.toFixed(6)}, ${r.lon.toFixed(6)} · ±${Math.round(r.accuracy)} m${r.status === "poor_accuracy" ? " (poor)" : ""}`;
  };

  return (
    <View style={styles.root} testID="camera-screen">
      {shot ? (
        <View style={{ flex: 1, paddingTop: insets.top + spacing.md, paddingHorizontal: spacing.lg, paddingBottom: insets.bottom + spacing.lg }}>
          <Text style={styles.header}>{label ?? "Review Photo"}</Text>
          <Image source={{ uri: shot.uri }} style={{ flex: 1, borderRadius: 16, marginBottom: spacing.sm }} contentFit="contain" />
          <View style={styles.metaBox} testID="capture-metadata">
            <Text style={styles.metaText}>Captured: {fmtIST(shot.capturedAt)} (automatic)</Text>
            <Text style={styles.metaText}>GPS at capture: {gpsLine(g ?? null, gpsBusy)}</Text>
            {c?.assigned_address ? <Text style={styles.metaText} numberOfLines={2}>Assigned address: {String(c.assigned_address).replace(/\s*\n\s*/g, ", ")}</Text> : null}
            {c ? (
              <Text style={[styles.metaText, !referenceSummary(c).ok && styles.warnText]} testID="capture-reference">{referenceSummary(c).text}</Text>
            ) : null}
            {dist != null ? (
              <Text style={[styles.metaText, outside && styles.warnText]} testID="capture-distance">
                Distance from case location: about {roundDistance(dist)} m (allowed {Math.round(allowedM)} m, GPS ±{Math.round(fix?.accuracy ?? 0)} m)
              </Text>
            ) : null}
            {check && check.status !== "outside" && check.status !== "no_reference" ? (
              <Text style={styles.metaText} testID="capture-location-status">
                {check.status === "within" ? "Assessment: within range. " : "Assessment: UNCERTAIN. "}{check.status === "uncertain" ? check.explanation : ""}
              </Text>
            ) : null}
            {preparing ? <Text style={styles.metaText}>Saving the photo securely on this phone…</Text> : null}
            {shot.readyMs != null ? <Text style={styles.metaText}>Ready in {(shot.readyMs / 1000).toFixed(1)} s</Text> : null}
            <Text style={styles.metaText}>The CheckSphere GPS watermark (date, time, coordinates, address) is added automatically on upload.</Text>
            {fix?.mocked ? <Text style={styles.warnText}>This phone reports a mock/simulated location. The photo will be flagged for review.</Text> : null}
          </View>
          {g && !g.ok ? <Banner tone="warning" message={GPS_HELP[g.status]} /> : null}
          {fix?.status === "poor_accuracy" ? <Banner tone="warning" message={GPS_HELP.poor_accuracy} /> : null}
          {outside ? (
            <Banner tone="warning" message={`${check!.explanation} Photos away from the assigned address can't be accepted as visit evidence without an explanation. Give the reason below; the photo will be flagged for supervisor review. If the assigned address is wrong, ask your supervisor to correct it.`} />
          ) : null}
          {needsReason || serverAsk ? (
            <View>
              {serverAsk ? <Banner tone="warning" message={serverAsk.message} /> : null}
              <TextInput
                style={styles.reasonInput}
                placeholder={noFix ? "Why is GPS not available here?" : "Why are you away from the assigned address?"}
                placeholderTextColor="#999"
                value={reason}
                onChangeText={setReason}
                multiline
                testID="location-reason-input"
              />
            </View>
          ) : null}
          <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
            <View style={{ flex: 1 }}>
              <Btn label="Retake" variant="secondary" onPress={() => { if (shooting) return; if (!serverAsk) { discardPrepared(unqueued.current); unqueued.current = null; } setShot(null); setServerAsk(null); }} testID="photo-retake-btn" full />
            </View>
            {g && (!g.ok || g.status === "poor_accuracy") ? (
              <View style={{ flex: 1 }}>
                <Btn label="Retry GPS" variant="secondary" onPress={retryShotGps} loading={gpsBusy} testID="photo-retry-gps-btn" full />
              </View>
            ) : null}
            <View style={{ flex: 1 }}>
              <Btn
                label={uploading ? "Saving…" : preparing ? "Preparing…" : !g ? "Getting GPS…" : serverAsk ? "Send with reason" : needsReason ? "Use with reason" : "Use Photo"}
                onPress={serverAsk ? sendWithServerReason : usePhoto}
                loading={uploading || preparing || (!g && gpsBusy)}
                disabled={!shot.photo || !g || gpsBusy || ((needsReason || !!serverAsk) && !reasonOk)}
                testID="photo-use-btn"
                full
              />
            </View>
          </View>
        </View>
      ) : (
        <View style={{ flex: 1 }}>
          <CameraView ref={cameraRef} style={{ flex: 1 }} facing={facing} pictureSize={pictureSize} onCameraReady={onCameraReady} />
          <View style={[styles.shutterRow, { paddingBottom: insets.bottom + spacing.xl }]}>
            <Pressable onPress={shoot} style={[styles.shutter, shooting && { opacity: 0.5 }]} disabled={shooting} testID="camera-shutter-btn">
              <View style={styles.shutterInner} />
            </Pressable>
          </View>
          <Pressable
            onPress={() => setFacing((f) => (f === "front" ? "back" : "front"))}
            style={[styles.flipBtn, { bottom: insets.bottom + spacing.xl + 18 }]}
            testID="camera-flip-btn"
          >
            <Text style={styles.flipText}>{facing === "front" ? "Rear camera" : "Front camera"}</Text>
          </Pressable>
          <View style={[styles.topBar, { paddingTop: insets.top + spacing.sm }]}>
            <View style={{ flex: 1 }}>
              <Text style={styles.topText}>{label ?? "Capture"}</Text>
              <Text style={styles.topSub}>{gpsLine(preflight, gpsBusy)} · GPS refreshes when you press the shutter</Text>
            </View>
            <Pressable onPress={() => router.back()} hitSlop={12} testID="camera-close-btn">
              <Text style={styles.closeText}>Close</Text>
            </Pressable>
          </View>
        </View>
      )}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.onSurface },
  header: { color: colors.onSurfaceInverse, fontSize: typography.scale.lg, fontWeight: "700", marginBottom: spacing.md },
  shutterRow: { position: "absolute", left: 0, right: 0, bottom: 0, alignItems: "center" },
  shutter: { width: 76, height: 76, borderRadius: 38, borderWidth: 4, borderColor: "#FFFFFF", alignItems: "center", justifyContent: "center" },
  shutterInner: { width: 58, height: 58, borderRadius: 29, backgroundColor: "#FFFFFF" },
  flipBtn: { position: "absolute", right: spacing.lg, backgroundColor: "rgba(0,0,0,0.55)", borderRadius: 20, paddingHorizontal: 14, paddingVertical: 10 },
  flipText: { color: "#FFFFFF", fontWeight: "700" },
  topBar: { position: "absolute", left: spacing.lg, right: spacing.lg, flexDirection: "row", justifyContent: "space-between", gap: spacing.sm },
  topText: { color: "#FFFFFF", fontWeight: "700" },
  topSub: { color: "#FFFFFF", fontSize: typography.scale.sm, marginTop: 2 },
  closeText: { color: "#FFFFFF", fontWeight: "700" },
  metaBox: { backgroundColor: "rgba(255,255,255,0.08)", borderRadius: 10, padding: spacing.sm, marginBottom: spacing.sm, gap: 2 },
  metaText: { color: colors.onSurfaceInverse, fontSize: typography.scale.sm },
  warnText: { color: "#FFB020", fontSize: typography.scale.sm, fontWeight: "700" },
  reasonInput: {
    backgroundColor: "#FFFFFF", borderRadius: 10, minHeight: 56, padding: spacing.sm, color: "#111",
    fontSize: typography.scale.base, marginTop: spacing.xs,
  },
  permTitle: { fontSize: typography.scale.xl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.sm, fontFamily: typography.fontFamily },
  permText: { color: colors.onSurfaceSecondary, lineHeight: 20, marginBottom: spacing.md },
}));
