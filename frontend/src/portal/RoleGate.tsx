// Route guard: renders the loader while the session restores, then redirects
// logged-out users to "/" and wrong-portal users to their own portal.
import type { ReactNode } from "react";
import { Redirect } from "expo-router";

import { WebLoader } from "@/src/components/WebLoader";
import { homeFor, type Role } from "@/src/navigation";
import { useSession } from "@/src/session";

export function RoleGate({ role, children }: { role: Role; children: ReactNode }) {
  const { ready, user } = useSession();
  if (!ready) return <WebLoader />;
  if (!user) return <Redirect href="/" />;
  if (user.must_change_password) return <Redirect href="/change-password" />;
  if (user.role !== role) return <Redirect href={homeFor(user.role) as any} />;
  return <>{children}</>;
}
