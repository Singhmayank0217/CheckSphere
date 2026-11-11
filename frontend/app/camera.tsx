// In-app camera capture — gallery uploads are blocked for visit evidence.
import { useRef, useEffect, useState } from "react";
import { Linking, Pressable, Text, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { Image } from "expo-image";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useQueryClient } from "@tanstack/react-query";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, uploadForm } from "@/src/api";
import { Banner, Btn, Card, Loading, showToast } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { getGps } from "@/src/utils/geo";
import { makeStyles, spacing, typography } from "@/src/theme";

export default function CameraCapture() {
  const { caseId, slot, label } = useLocalSearchParams<{ caseId: string; slot: string; label?: string }>();
  const { token } = useSession();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const styles = useStyles();

  const [permission, requestPermission] = useCameraPermissions();
  const [photo, setPhoto] = useState<any>(null);
  const [uploading, setUploading] = useState(false);
  const [gps, setGps] = useState<any>(null);

  useEffect(() => {
    (async () => {
      const g = await getGps();
      if (g.ok) setGps({ lat: g.lat, lon: g.lon, accuracy: g.accuracy });
    })();
  }, []);

  const cameraRef = useRef<any>(null);

  const shoot = async () => {
    try {
      const p = await (cameraRef.current as any)?.takePictureAsync({ quality: 60 });
      setPhoto(p);
    } catch {
      showToast("Could not take picture", "error");
    }
  };

  const usePhoto = async () => {
    if (!photo) return;
    setUploading(true);
    try {
      const res = await uploadForm(`${API_URL}/api/evidence/upload`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        fields: {
          case_id: caseId ?? "",
          slot: slot ?? "document",
          kind: "photo",
          captured_at: new Date().toISOString(),
          ...(gps?.lat ? { lat: String(gps.lat), lon: String(gps.lon), accuracy: String(gps.accuracy) } : {}),
        },
        files: { file: { uri: photo.uri, name: `capture-${Date.now()}.jpg`, mimeType: "image/jpeg" } },
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text.slice(0, 200) || "Upload failed");
      }
      queryClient.invalidateQueries({ queryKey: ["report", caseId] });
      showToast("Photo captured and uploaded", "success");
      router.back();
    } catch (e: any) {
      showToast(e?.message ?? "Upload failed", "error");
    } finally {
      setUploading(false);
    }
  };

  // ---- permission states (handle_permissions_contract) ----
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

  return (
    <View style={styles.root} testID="camera-screen">
      {photo ? (
        <View style={{ flex: 1, paddingTop: insets.top + spacing.md, paddingHorizontal: spacing.lg }}>
          <Text style={styles.header}>{label ?? "Review Photo"}</Text>
          <Image source={{ uri: photo.uri }} style={{ flex: 1, borderRadius: 16, marginBottom: spacing.md }} contentFit="contain" />
          {!gps ? <Banner tone="warning" message="GPS not captured for this photo — it will be flagged for review." /> : null}
          <View style={{ flexDirection: "row", gap: spacing.sm, marginBottom: insets.bottom + spacing.lg }}>
            <View style={{ flex: 1 }}>
              <Btn label="Retake" variant="secondary" onPress={() => setPhoto(null)} testID="photo-retake-btn" full />
            </View>
            <View style={{ flex: 1 }}>
              <Btn label={uploading ? "Uploading…" : "Use Photo"} onPress={usePhoto} loading={uploading} testID="photo-use-btn" full />
            </View>
          </View>
        </View>
      ) : (
        <View style={{ flex: 1 }}>
          <CameraView ref={cameraRef} style={{ flex: 1 }} facing="back" />
          <View style={[styles.shutterRow, { paddingBottom: insets.bottom + spacing.xl }]}>
            <Pressable onPress={shoot} style={styles.shutter} testID="camera-shutter-btn">
              <View style={styles.shutterInner} />
            </Pressable>
          </View>
          <View style={[styles.topBar, { paddingTop: insets.top + spacing.sm }]}>
            <Text style={styles.topText}>{label ?? "Capture"} · {gps ? `GPS ±${gps.accuracy}m` : "no GPS"}</Text>
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
  topBar: { position: "absolute", left: spacing.lg, right: spacing.lg, flexDirection: "row", justifyContent: "space-between" },
  topText: { color: "#FFFFFF", fontWeight: "600" },
  closeText: { color: "#FFFFFF", fontWeight: "700" },
  permTitle: { fontSize: typography.scale.xl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.sm, fontFamily: typography.fontFamily },
  permText: { color: colors.onSurfaceSecondary, lineHeight: 20, marginBottom: spacing.md },
}));
