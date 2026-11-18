// Static map preview (works on web + native, no native SDK). Tiles come only from the provider configured in
// EXPO_PUBLIC_MAP_TILE_URL (see src/utils/osm.ts). A map that cannot be shown is a map-service issue, never a GPS
// failure: the coordinates and accuracy below the map always come from the phone's GPS and are shown regardless.
import { useState } from "react";
import { Linking, Pressable, Text, View } from "react-native";
import { Image } from "expo-image";

import { mapsUrl } from "@/src/utils/geo";
import { latToTileY, lonToTileX, TILE_ATTRIBUTION, tilesConfigured, tileUrl } from "@/src/utils/osm";
import { makeStyles, radius, spacing, typography } from "@/src/theme";

const useStyles = makeStyles((colors) => ({
  wrap: { borderRadius: radius.md, overflow: "hidden", borderWidth: 1, borderColor: colors.border, width: "100%", backgroundColor: colors.surfaceTertiary },
  grid: { flexDirection: "row" },
  marker: {
    position: "absolute", width: 18, height: 18, borderRadius: 9,
    backgroundColor: colors.error, borderWidth: 3, borderColor: "#FFFFFF",
    shadowColor: "#000", shadowOpacity: 0.3, shadowRadius: 3, elevation: 4,
  },
  attribution: {
    position: "absolute", bottom: 0, right: 0, backgroundColor: "rgba(255,255,255,0.8)",
    fontSize: 8, paddingHorizontal: 4, paddingVertical: 1, color: colors.onSurfaceTertiary,
  },
  notice: { padding: spacing.md, alignItems: "center", justifyContent: "center", gap: 4 },
  noticeText: { fontSize: typography.scale.sm, color: colors.muted, textAlign: "center" },
  overlay: { position: "absolute", left: 0, right: 0, bottom: 0, padding: 6, backgroundColor: "rgba(255,255,255,0.92)" },
  link: { fontSize: typography.scale.sm, color: colors.info, fontWeight: "700", textAlign: "center" },
  meta: { fontSize: typography.scale.sm, color: colors.muted, marginTop: spacing.sm, textAlign: "center" },
}));

export function MiniMap({ lat, lon, accuracy, height = 180, testID }: {
  lat: number; lon: number; accuracy?: number | null; height?: number; testID?: string;
}) {
  const styles = useStyles();
  const [width, setWidth] = useState(0);
  const [failed, setFailed] = useState(0);
  const z = 16;
  const tile = Math.round(height / 3);
  const cols = Math.max(3, Math.ceil(width / tile) | 1);
  const half = Math.floor(cols / 2);
  const x = lonToTileX(lon, z);
  const y = latToTileY(lat, z);
  const fx = Math.floor(x);
  const fy = Math.floor(y);
  const openMaps = (
    <Pressable onPress={() => Linking.openURL(mapsUrl(lat, lon))} accessibilityRole="link" testID={testID ? `${testID}-open` : undefined}>
      <Text style={styles.link}>Open this point in Google Maps</Text>
    </Pressable>
  );
  const meta = (
    <Text style={styles.meta}>
      {lat.toFixed(6)}, {lon.toFixed(6)}
      {accuracy != null ? ` · ±${accuracy}m accuracy` : ""}
    </Text>
  );

  if (!tilesConfigured) {
    return (
      <View testID={testID}>
        <View style={[styles.wrap, styles.notice]} testID="map-not-configured">
          <Text style={styles.noticeText}>Map preview is not set up for this app (no licensed map tile provider configured).</Text>
          <Text style={styles.noticeText}>This does not affect GPS: the position below is from the phone&apos;s GPS.</Text>
          {openMaps}
        </View>
        {meta}
      </View>
    );
  }

  const tiles = [];
  for (let dy = -1; dy <= 1; dy++) {
    const row = [];
    for (let dx = -half; dx <= half; dx++) {
      row.push(
        <Image
          key={`${dx}-${dy}`}
          source={{ uri: tileUrl(fx + dx, fy + dy, z) }}
          style={{ width: tile, height: tile }}
          contentFit="cover"
          transition={200}
          onError={() => setFailed((n) => n + 1)}
        />,
      );
    }
    tiles.push(<View key={dy} style={styles.grid}>{row}</View>);
  }
  const gridW = cols * tile;
  const offsetX = width > 0 ? (width - gridW) / 2 : 0;
  const markerLeft = offsetX + (x - (fx - half)) * tile - 9;
  const markerTop = (y - (fy - 1)) * tile - 9;
  return (
    <View testID={testID}>
      <View style={[styles.wrap, { height: tile * 3 }]} onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
        <View style={{ position: "absolute", left: offsetX, top: 0 }}>{tiles}</View>
        <View style={[styles.marker, { left: markerLeft, top: markerTop }]} testID="map-marker" />
        {TILE_ATTRIBUTION ? <Text style={styles.attribution}>{TILE_ATTRIBUTION}</Text> : null}
        {failed > 0 ? (
          <View style={styles.overlay} testID="map-tiles-failed">
            <Text style={styles.noticeText}>Map tiles could not be loaded from the map service. GPS is not affected.</Text>
            {openMaps}
          </View>
        ) : null}
      </View>
      {meta}
    </View>
  );
}
