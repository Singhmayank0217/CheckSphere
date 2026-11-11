// Design tokens for CheckSphere — light professional palette (design_guidelines.json).
// Keys match the "color" block of /app/design_guidelines.json. Do not add a second theme file.
//
// Usage:
//   const styles = makeStyles((colors) => ({ card: { backgroundColor: colors.surfaceSecondary } }));
//   const { colors } = useTheme(); // for icon colors etc.

import { useMemo } from "react";
import { Appearance, StyleSheet, useColorScheme, type ImageStyle, type TextStyle, type ViewStyle } from "react-native";

export type ColorScheme = "light" | "dark";

const light = {
  surface: "#F9F8F6",
  onSurface: "#1A1A18",
  surfaceSecondary: "#FFFFFF",
  onSurfaceSecondary: "#1A1A18",
  surfaceTertiary: "#F0EDE6",
  onSurfaceTertiary: "#595752",
  surfaceInverse: "#1A1A18",
  onSurfaceInverse: "#F9F8F6",
  muted: "#73706A",

  brand: "#1F4E3D",
  onBrand: "#FFFFFF",
  brandPrimary: "#1F4E3D",
  onBrandPrimary: "#FFFFFF",
  brandSecondary: "#326853",
  onBrandSecondary: "#FFFFFF",
  brandTertiary: "#E4EBE7",
  onBrandTertiary: "#1F4E3D",

  success: "#2E6930",
  onSuccess: "#FFFFFF",
  warning: "#9C6B14",
  onWarning: "#FFFFFF",
  error: "#9E2A2B",
  onError: "#FFFFFF",
  info: "#2B5278",
  onInfo: "#FFFFFF",

  border: "#E2DFD8",
  borderStrong: "#C7C2B6",
  divider: "#EFECE6",
};

export type ThemeColors = typeof light;

export const defaultScheme = "light" satisfies ColorScheme;
export const themes: { light: ThemeColors; dark?: ThemeColors } = { light };

// Spacing & radius tokens from design_guidelines.json
export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, xxxl: 48 };
export const radius = { sm: 6, md: 12, lg: 20, pill: 999 };

// Typography: Plus Jakarta Sans loaded via expo-font in app/_layout.tsx.
export const typography = {
  fontFamily: "PlusJakartaSans",
  scale: { sm: 12, base: 14, lg: 16, xl: 20, xxl: 24 },
};

export function setColorScheme(scheme: ColorScheme | null) {
  Appearance.setColorScheme?.(scheme ?? "unspecified");
}

setColorScheme?.(themes.dark ? null : defaultScheme);

export function useTheme(): { scheme: ColorScheme; colors: ThemeColors } {
  const system = useColorScheme();
  const scheme: ColorScheme = (system === "light" || system === "dark") && themes[system] ? system : defaultScheme;
  return { scheme, colors: themes[scheme] ?? themes.light };
}

type NamedStyles = { [key: string]: ViewStyle | TextStyle | ImageStyle };

export function makeStyles<T extends NamedStyles>(
  factory: (colors: ThemeColors) => T,
): () => T {
  return function useStyles(): T {
    const { colors } = useTheme();
    return useMemo(() => StyleSheet.create(factory(colors)), [colors]);
  };
}
