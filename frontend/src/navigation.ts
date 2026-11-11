import { Platform } from "react-native";

// iOS 26+ renders NativeTabs (liquid glass); older iOS, Android and web use the classic Tabs.
export const usesNativeTabs = Platform.OS === "ios" && parseInt(String(Platform.Version), 10) >= 26;
