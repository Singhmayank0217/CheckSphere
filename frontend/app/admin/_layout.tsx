import { ADMIN_NAV, PortalShell } from "@/src/portal/Shell";

export default function AdminLayout() {
  return <PortalShell role="super_admin" nav={ADMIN_NAV} />;
}
