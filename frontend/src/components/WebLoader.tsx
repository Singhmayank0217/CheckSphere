// Short desktop/web loading screen with the CheckSphere identity.
import { useEffect } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import Animated, { FadeIn } from "react-native-reanimated";
import Svg, { Circle, Path } from "react-native-svg";

import { makeStyles, typography } from "@/src/theme";

export const SHIELD_PATH = "M50 6 L88 20 V50 C88 74 70 90 50 96 C30 90 12 74 12 50 V20 Z";

export function ShieldMark({ size = 56, color = "#FFFFFF" }: { size?: number; color?: string }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 100 100">
      <Path d={SHIELD_PATH} stroke={color} strokeWidth={5} fill="none" strokeLinejoin="round" />
      <Path d="M50 34 C42 34 37 40 37 47 C37 56 50 68 50 68 C50 68 63 56 63 47 C63 40 58 34 50 34 Z" fill={color} />
      <Circle cx={50} cy={47} r={5} fill="#16384A" />
    </Svg>
  );
}

export function WebLoader({ onDone, duration = 0 }: { onDone?: () => void; duration?: number }) {
  const styles = useStyles();
  useEffect(() => {
    if (!onDone || !duration) return;
    const t = setTimeout(onDone, duration);
    return () => clearTimeout(t);
  }, [onDone, duration]);
  return (
    <LinearGradient colors={["#1F4E3D", "#12293A"]} style={styles.root} testID="web-loader">
      <Animated.View entering={FadeIn.duration(400)} style={styles.center}>
        <ShieldMark size={64} />
        <Text style={styles.name}>CheckSphere</Text>
        <Text style={styles.tag}>Every Visit. Verified.</Text>
        <ActivityIndicator color="#FFFFFF" style={{ marginTop: 24 }} />
      </Animated.View>
    </LinearGradient>
  );
}

const useStyles = makeStyles(() => ({
  root: { flex: 1, alignItems: "center", justifyContent: "center" },
  center: { alignItems: "center" },
  name: { color: "#FFFFFF", fontSize: 30, fontWeight: "800", marginTop: 16, fontFamily: typography.fontFamily, letterSpacing: 0.5 },
  tag: { color: "rgba(255,255,255,0.75)", fontSize: 15, marginTop: 6 },
}));
