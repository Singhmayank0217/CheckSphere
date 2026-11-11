// Static OpenStreetMap preview (works on web + native, no native SDK).
import { useState } from "react";
import { Text, View } from "react-native";
import { Image } from "expo-image";

import { latToTileY, lonToTileX, tileUrl } from "@/src/utils/osm";
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
  meta: { fontSize: typography.scale.sm, color: colors.muted, marginTop: spacing.sm, textAlign: "center" },
}));

export function MiniMap({ lat, lon, accuracy, height = 180, testID }: {
  lat: number; lon: number; accuracy?: number | null; height?: number; testID?: string;
}) {
  const styles = useStyles();
  const [width, setWidth] = useState(0);
  const z = 16;
  const cols = Math.max(3, Math.ceil(width / Math.round(height / 3)) | 1);
  const tile = Math.round(height / 3);
  const half = Math.floor(cols / 2);
  const x = lonToTileX(lon, z);
  const y = latToTileY(lat, z);
  const fx = Math.floor(x);
  const fy = Math.floor(y);
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
        <Text style={styles.attribution}>© OpenStreetMap</Text>
      </View>
      <Text style={styles.meta}>
        {lat.toFixed(6)}, {lon.toFixed(6)}
        {accuracy != null ? ` · ±${accuracy}m accuracy` : ""}
      </Text>
    </View>
  );
}
