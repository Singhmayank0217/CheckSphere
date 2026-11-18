// Map tile helpers for the MiniMap component (works on web + native via expo-image).
//
// Tiles are only fetched from a provider configured for this deployment:
//   EXPO_PUBLIC_MAP_TILE_URL     e.g. https://<provider>/{z}/{x}/{y}.png?key=<public key>   ({z} {x} {y} placeholders)
//   EXPO_PUBLIC_MAP_ATTRIBUTION  the attribution text that provider requires (e.g. "© MapTiler © OpenStreetMap contributors")
// The public OpenStreetMap servers (tile.openstreetmap.org) are NOT used: their tile usage policy does not allow
// distributed apps without permission and they answer such requests with "403 Access blocked" tiles.
// With no provider configured the map preview is replaced by coordinates and an "Open in Google Maps" link;
// GPS capture and the distance check never depend on map tiles.
export const TILE_TEMPLATE = (process.env.EXPO_PUBLIC_MAP_TILE_URL ?? "").trim();
export const TILE_ATTRIBUTION = (process.env.EXPO_PUBLIC_MAP_ATTRIBUTION ?? "").trim();
export const tilesConfigured = /\{z\}/.test(TILE_TEMPLATE) && /\{x\}/.test(TILE_TEMPLATE) && /\{y\}/.test(TILE_TEMPLATE)
  && !/tile\.openstreetmap\.org/i.test(TILE_TEMPLATE);

export function lonToTileX(lon: number, z: number): number {
  return ((lon + 180) / 360) * Math.pow(2, z);
}

export function latToTileY(lat: number, z: number): number {
  const rad = (Math.max(-85, Math.min(85, lat)) * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * Math.pow(2, z);
}

export function tileUrl(x: number, y: number, z: number): string {
  return TILE_TEMPLATE.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));
}
