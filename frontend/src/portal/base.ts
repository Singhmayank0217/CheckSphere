import { usePathname } from "expo-router";

export function usePortalBase(): "/admin" | "/supervisor" {
  return usePathname().startsWith("/supervisor") ? "/supervisor" : "/admin";
}
