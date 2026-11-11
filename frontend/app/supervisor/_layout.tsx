import { PortalShell, SUPERVISOR_NAV } from "@/src/portal/Shell";

export default function SupervisorLayout() {
  return <PortalShell role="supervisor" nav={SUPERVISOR_NAV} />;
}
