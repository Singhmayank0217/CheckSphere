import { QueryClientProvider } from "@tanstack/react-query";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { LogBox, Platform, StyleSheet } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";

import { ErrorBoundary } from "@/src/components/error-boundary";
import { ServerWakeBanner, ToastHost } from "@/src/components/ui";
import { WebLoader } from "@/src/components/WebLoader";
import { queryClient } from "@/src/query-client";
import { SessionProvider } from "@/src/session";

// Disable logbox errors etc so that users can see the app
// and agent works as expected.
LogBox.ignoreAllLogs(true)

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts({ PlusJakartaSans: require("../assets/fonts/PlusJakartaSans.ttf") });
  // Web shows the branded loader instead of a blank page while the font downloads; a font that fails to load must
  // not block the app (it falls back to the system font). Android keeps its splash screen meanwhile.
  if (!fontsLoaded && !fontError) return Platform.OS === "web" ? <WebLoader /> : null;
  return (
    <GestureHandlerRootView style={styles.root}>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <KeyboardProvider>
            <SessionProvider>
              <Stack screenOptions={{ headerShown: false }} />
              <ToastHost />
              <ServerWakeBanner />
            </SessionProvider>
          </KeyboardProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
});
