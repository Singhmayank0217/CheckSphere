import { Platform } from "react-native";

// iOS 26+ renders NativeTabs (liquid glass); older iOS, Android and web use the classic Tabs.
export const usesNativeTabs = Platform.OS === "ios" && parseInt(String(Platform.Version), 10) >= 26;

export type Role = "agent" | "supervisor" | "super_admin";

// Each role has exactly one home: agents use the mobile app, staff use desktop web portals.
export function homeFor(role?: Role | string | null): string {
  if (role === "super_admin") return "/admin";
  if (role === "supervisor") return "/supervisor";
  if (role === "agent") return "/home";
  return "/";
}

export const ROLE_LABEL: Record<Role, string> = {
  agent: "Field Agent",
  supervisor: "Supervisor",
  super_admin: "Super Admin",
};
