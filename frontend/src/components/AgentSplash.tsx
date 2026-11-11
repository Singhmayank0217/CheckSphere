// Animated agent-app opening screen (~2.8s, no buttons, respects reduced motion).
import { useEffect } from "react";
import { ActivityIndicator, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import Animated, {
  Easing, useAnimatedProps, useAnimatedStyle, useReducedMotion, useSharedValue,
  withDelay, withRepeat, withSequence, withTiming,
} from "react-native-reanimated";
import Svg, { Path } from "react-native-svg";

import { SHIELD_PATH } from "@/src/components/WebLoader";
import { typography } from "@/src/theme";

const AnimatedPath = Animated.createAnimatedComponent(Path);
const SHIELD_LEN = 300;
export const SPLASH_MS = 2800;

export function AgentSplash({ onDone }: { onDone: () => void }) {
  const reduced = useReducedMotion();
  const { width, height } = useWindowDimensions();
  const draw = useSharedValue(reduced ? 0 : SHIELD_LEN);
  const pin = useSharedValue(reduced ? 1 : 0);
  const bob = useSharedValue(0);
  const text = useSharedValue(reduced ? 1 : 0);
  const grid = useSharedValue(0);

  useEffect(() => {
    if (!reduced) {
      draw.value = withTiming(0, { duration: 1300, easing: Easing.inOut(Easing.cubic) });
      pin.value = withDelay(1000, withTiming(1, { duration: 450 }));
      bob.value = withDelay(1450, withRepeat(withSequence(withTiming(-4, { duration: 500 }), withTiming(0, { duration: 500 })), -1));
      text.value = withDelay(1300, withTiming(1, { duration: 700 }));
      grid.value = withRepeat(withTiming(1, { duration: 6000, easing: Easing.linear }), -1);
    }
    const t = setTimeout(onDone, SPLASH_MS);
    return () => clearTimeout(t);
  }, [reduced, onDone, draw, pin, bob, text, grid]);

  const shieldProps = useAnimatedProps(() => ({ strokeDashoffset: draw.value }));
  const pinStyle = useAnimatedStyle(() => ({ opacity: pin.value, transform: [{ translateY: bob.value + (1 - pin.value) * -14 }] }));
  const textStyle = useAnimatedStyle(() => ({ opacity: text.value, transform: [{ translateY: (1 - text.value) * 8 }] }));
  const gridStyle = useAnimatedStyle(() => ({ transform: [{ translateX: -grid.value * 40 }, { translateY: -grid.value * 40 }] }));

  const lines = [];
  for (let i = 0; i < Math.ceil((width + 80) / 40); i++) lines.push(<View key={`v${i}`} style={[styles.vLine, { left: i * 40 }]} />);
  for (let j = 0; j < Math.ceil((height + 80) / 40); j++) lines.push(<View key={`h${j}`} style={[styles.hLine, { top: j * 40 }]} />);

  return (
    <LinearGradient colors={["#1F4E3D", "#12293A"]} style={styles.root} testID="agent-splash">
      <Animated.View style={[StyleSheet.absoluteFill, { width: width + 80, height: height + 80 }, gridStyle]} pointerEvents="none">
        {lines}
      </Animated.View>
      <View style={styles.center}>
        <View style={{ width: 120, height: 120 }}>
          <Svg width={120} height={120} viewBox="0 0 100 100">
            <AnimatedPath d={SHIELD_PATH} stroke="#FFFFFF" strokeWidth={3.5} fill="none" strokeLinejoin="round"
              strokeDasharray={SHIELD_LEN} animatedProps={shieldProps} />
          </Svg>
          <Animated.View style={[styles.pinWrap, pinStyle]}>
            <Svg width={34} height={34} viewBox="0 0 24 24">
              <Path d="M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7zm0 9.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5z" fill="#7FD1AE" />
            </Svg>
          </Animated.View>
        </View>
        <Animated.View style={[{ alignItems: "center" }, textStyle]}>
          <Text style={styles.name}>CheckSphere</Text>
          <Text style={styles.main}>Every Visit. Verified.</Text>
          <Text style={styles.sub}>Secure field verification, captured with proof.</Text>
        </Animated.View>
      </View>
      <ActivityIndicator color="rgba(255,255,255,0.8)" style={styles.loader} />
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  vLine: { position: "absolute", top: 0, bottom: 0, width: StyleSheet.hairlineWidth, backgroundColor: "rgba(255,255,255,0.07)" },
  hLine: { position: "absolute", left: 0, right: 0, height: StyleSheet.hairlineWidth, backgroundColor: "rgba(255,255,255,0.07)" },
  center: { alignItems: "center", gap: 20 },
  pinWrap: { position: "absolute", left: 43, top: 34 },
  name: { color: "#FFFFFF", fontSize: 30, fontWeight: "800", fontFamily: typography.fontFamily, letterSpacing: 0.5 },
  main: { color: "#FFFFFF", fontSize: 18, fontWeight: "600", marginTop: 8 },
  sub: { color: "rgba(255,255,255,0.7)", fontSize: 13, marginTop: 6 },
  loader: { position: "absolute", bottom: 64 },
});
