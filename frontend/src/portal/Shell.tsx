// Desktop-first portal shell: fixed 260px sidebar, top header (search, notifications, user, sign out).
import { useState, type ReactNode } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { Slot, usePathname, useRouter } from "expo-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Ionicons from "@react-native-vector-icons/ionicons";

import { api } from "@/src/api";
import { ShieldMark } from "@/src/components/WebLoader";
import { ROLE_LABEL } from "@/src/navigation";
import { RoleGate } from "@/src/portal/RoleGate";
import { useSession } from "@/src/session";
import { makeStyles, radius, spacing, typography, useTheme } from "@/src/theme";

export type NavItem = { path: string; label: string; icon: string };

export const ADMIN_NAV: NavItem[] = [
  { path: "/admin", label: "Dashboard", icon: "grid-outline" },
  { path: "/admin/cases", label: "Cases", icon: "folder-open-outline" },
  { path: "/admin/create", label: "Create / Import Cases", icon: "add-circle-outline" },
  { path: "/admin/agents", label: "Agents", icon: "walk-outline" },
  { path: "/admin/supervisors", label: "Supervisors", icon: "people-outline" },
  { path: "/admin/clients", label: "Clients and Branches", icon: "business-outline" },
  { path: "/admin/templates", label: "Report Templates", icon: "document-text-outline" },
  { path: "/admin/map", label: "Map and Evidence Flags", icon: "map-outline" },
  { path: "/admin/review", label: "Review Queue", icon: "checkmark-done-outline" },
  { path: "/admin/requests", label: "Case Requests", icon: "mail-unread-outline" },
  { path: "/admin/mis", label: "MIS and Exports", icon: "download-outline" },
  { path: "/admin/audit", label: "Audit Log", icon: "list-outline" },
  { path: "/admin/security", label: "Security and Sessions", icon: "lock-closed-outline" },
  { path: "/admin/backup", label: "Backup and Retention", icon: "server-outline" },
  { path: "/admin/settings", label: "Settings", icon: "settings-outline" },
];

export const SUPERVISOR_NAV: NavItem[] = [
  { path: "/supervisor", label: "Dashboard", icon: "grid-outline" },
  { path: "/supervisor/cases", label: "Cases", icon: "folder-open-outline" },
  { path: "/supervisor/review", label: "Review Queue", icon: "checkmark-done-outline" },
  { path: "/supervisor/requests", label: "Case Requests", icon: "mail-unread-outline" },
  { path: "/supervisor/map", label: "Map and Evidence Flags", icon: "map-outline" },
  { path: "/supervisor/agents", label: "My Team", icon: "walk-outline" },
  { path: "/supervisor/mis", label: "MIS and Exports", icon: "download-outline" },
];

function Notifications({ base }: { base: string }) {
  const styles = useStyles();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const statsQ = useQuery({ queryKey: ["admin-stats", "notif"], queryFn: () => api<any>("/dashboard/stats"), refetchInterval: 60000 });
  const notifQ = useQuery({ queryKey: ["notifications"], queryFn: () => api<any>("/notifications"), refetchInterval: 30000 });
  const qc = useQueryClient();
  const s = statsQ.data;
  const alerts: any[] = (notifQ.data?.items ?? []).filter((n: any) => !n.acknowledged_at).slice(0, 8);
  const items = [
    { label: "Agent case requests awaiting approval", n: s?.requests_pending ?? 0, to: `${base}/requests` },
    { label: `Cases pending > ${base === "/admin" ? 48 : 24}h`, n: (base === "/admin" ? s?.pending_48h : s?.pending_24h) ?? 0, to: `${base}/cases?status=new,assigned,in_progress,returned` },
    { label: "Reports pending review", n: (s?.counts?.submitted ?? 0) + (s?.counts?.under_review ?? 0), to: `${base}/review` },
    { label: "Overdue cases", n: s?.overdue ?? 0, to: `${base}/cases?sla=overdue` },
    { label: "Cases with evidence flags", n: s?.flagged_cases ?? 0, to: `${base}/cases?flagged=1` },
    { label: "Escalated to Super Admin", n: s?.escalated ?? 0, to: `${base}/cases?status=under_review` },
  ].filter((i) => i.n > 0);
  const total = items.reduce((a, b) => a + b.n, 0) + (notifQ.data?.unread ?? 0);
  const ack = async (n: any) => {
    await api(`/notifications/${n.id}/ack`, { method: "POST" }).catch(() => null);
    qc.invalidateQueries({ queryKey: ["notifications"] });
    if (n.case_id) { setOpen(false); router.push(`${base}/cases/${n.case_id}` as any); }
  };
  return (
    <View>
      <Pressable onPress={() => setOpen(!open)} style={styles.iconBtn} testID="header-notifications-btn">
        <Ionicons name="notifications-outline" size={22} color={styles.headerText.color as string} />
        {total > 0 ? <View style={styles.badge}><Text style={styles.badgeText}>{total > 99 ? "99+" : total}</Text></View> : null}
      </Pressable>
      {open ? (
        <View style={styles.dropdown} testID="notifications-dropdown">
          <Text style={styles.dropTitle}>Notifications</Text>
          {items.length === 0 && alerts.length === 0 ? <Text style={styles.dropEmpty}>You are all caught up.</Text> : null}
          {alerts.map((n) => (
            <Pressable key={n.id} style={styles.dropItem} onPress={() => ack(n)} testID={`notif-alert-${n.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={[styles.dropLabel, { fontWeight: "700" }]}>{n.title}</Text>
                <Text style={styles.dropEmpty} numberOfLines={2}>{n.body}</Text>
              </View>
              <Text style={styles.dropEmpty}>✓</Text>
            </Pressable>
          ))}
          {items.map((i) => (
            <Pressable key={i.label} style={styles.dropItem} onPress={() => { setOpen(false); router.push(i.to as any); }} testID={`notif-${i.label.split(" ")[0].toLowerCase()}`}>
              <Text style={styles.dropLabel}>{i.label}</Text>
              <Text style={styles.dropCount}>{i.n}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

export function PortalShell({ role, nav }: { role: "super_admin" | "supervisor"; nav: NavItem[] }) {
  return (
    <RoleGate role={role}>
      <ShellInner role={role} nav={nav} />
    </RoleGate>
  );
}

function ShellInner({ role, nav }: { role: "super_admin" | "supervisor"; nav: NavItem[] }) {
  const { user, signOut } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const styles = useStyles();
  const { colors } = useTheme();
  const [search, setSearch] = useState("");
  const base = role === "super_admin" ? "/admin" : "/supervisor";

  const onSignOut = async () => {
    await signOut();
    router.replace("/");
  };
  const isActive = (p: string) => (p === base ? pathname === base || pathname === `${base}/` : pathname.startsWith(p));

  return (
    <View style={styles.root}>
      <View style={styles.sidebar} testID="portal-sidebar">
        <View style={styles.brandRow}>
          <ShieldMark size={34} />
          <View>
            <Text style={styles.brand}>CheckSphere</Text>
            <Text style={styles.brandSub}>{ROLE_LABEL[role]} Portal</Text>
          </View>
        </View>
        <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingVertical: spacing.md, gap: 2 }}>
          {nav.map((n) => {
            const active = isActive(n.path);
            return (
              <Pressable
                key={n.path}
                onPress={() => router.push(n.path as any)}
                style={({ hovered }: any) => [styles.navItem, hovered && styles.navHover, active && styles.navActive]}
                testID={`nav-${n.path.split("/").pop() || "dashboard"}`}
              >
                <Ionicons name={n.icon as any} size={19} color={active ? "#FFFFFF" : "rgba(255,255,255,0.75)"} />
                <Text style={[styles.navText, active && styles.navTextActive]} numberOfLines={1}>{n.label}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
        <Pressable onPress={onSignOut} style={({ hovered }: any) => [styles.navItem, styles.signOutNav, hovered && styles.navHover]} testID="sidebar-signout-btn">
          <Ionicons name="log-out-outline" size={19} color="#FFFFFF" />
          <Text style={styles.navTextActive}>Sign Out</Text>
        </Pressable>
      </View>

      <View style={styles.main}>
        <View style={styles.header} testID="portal-header">
          <View style={styles.searchBox}>
            <Ionicons name="search" size={18} color={colors.muted} />
            <TextInput
              value={search}
              onChangeText={setSearch}
              onSubmitEditing={() => router.push(`${base}/cases?q=${encodeURIComponent(search)}` as any)}
              placeholder="Search applicant, internal case ID or client case ID…"
              placeholderTextColor={colors.muted}
              style={styles.searchInput}
              testID="header-search-input"
            />
          </View>
          <View style={styles.headerRight}>
            <Notifications base={base} />
            <View style={styles.userBox} testID="header-user">
              <View style={styles.avatar}><Text style={styles.avatarText}>{(user?.name ?? "?").slice(0, 1)}</Text></View>
              <View>
                <Text style={styles.userName}>{user?.name}</Text>
                <Text style={styles.userRole}>{ROLE_LABEL[role]}</Text>
              </View>
            </View>
            <Pressable onPress={onSignOut} style={styles.signOutBtn} testID="header-signout-btn">
              <Text style={styles.signOutText}>Sign Out</Text>
            </Pressable>
          </View>
        </View>
        <View style={styles.content}>
          <Slot />
        </View>
      </View>
    </View>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  const styles = useStyles();
  return (
    <View style={styles.pageHeader}>
      <View style={{ flex: 1, minWidth: 240 }}>
        <Text style={styles.pageTitle}>{title}</Text>
        {subtitle ? <Text style={styles.pageSub}>{subtitle}</Text> : null}
      </View>
      {actions ? <View style={styles.pageActions}>{actions}</View> : null}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, flexDirection: "row", backgroundColor: colors.surface, minHeight: "100%" as any },
  sidebar: { width: 260, flexShrink: 0, backgroundColor: colors.brandPrimary, paddingHorizontal: spacing.md, paddingTop: spacing.xl, paddingBottom: spacing.lg },
  brandRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.sm, paddingBottom: spacing.md, borderBottomWidth: 1, borderBottomColor: "rgba(255,255,255,0.12)" },
  brand: { color: "#FFFFFF", fontSize: 20, fontWeight: "800", fontFamily: typography.fontFamily },
  brandSub: { color: "rgba(255,255,255,0.7)", fontSize: 12, marginTop: 1 },
  navItem: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: 11, paddingHorizontal: spacing.md, borderRadius: radius.sm },
  navHover: { backgroundColor: "rgba(255,255,255,0.08)" },
  navActive: { backgroundColor: colors.brandSecondary },
  navText: { color: "rgba(255,255,255,0.85)", fontSize: 15, fontWeight: "600", flexShrink: 1 },
  navTextActive: { color: "#FFFFFF", fontSize: 15, fontWeight: "800" },
  signOutNav: { borderTopWidth: 1, borderTopColor: "rgba(255,255,255,0.12)", borderRadius: 0, marginTop: spacing.sm, paddingTop: spacing.md },
  main: { flex: 1, minWidth: 0 },
  header: {
    height: 68, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.lg,
    paddingHorizontal: spacing.xl, backgroundColor: colors.surfaceSecondary, borderBottomWidth: 1, borderBottomColor: colors.border, zIndex: 10,
  },
  headerText: { color: colors.onSurface },
  searchBox: {
    flex: 1, maxWidth: 560, flexDirection: "row", alignItems: "center", gap: spacing.sm, height: 42,
    paddingHorizontal: spacing.md, borderRadius: radius.md, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  searchInput: { flex: 1, fontSize: 15, color: colors.onSurface, height: 40, outlineStyle: "none" as any },
  headerRight: { flexDirection: "row", alignItems: "center", gap: spacing.lg },
  iconBtn: { width: 42, height: 42, borderRadius: 21, alignItems: "center", justifyContent: "center" },
  badge: { position: "absolute", top: 4, right: 2, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: colors.error, alignItems: "center", justifyContent: "center", paddingHorizontal: 4 },
  badgeText: { color: "#FFFFFF", fontSize: 11, fontWeight: "800" },
  dropdown: {
    position: "absolute", top: 48, right: 0, width: 320, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, padding: spacing.md, shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 16, elevation: 8,
  },
  dropTitle: { fontWeight: "800", fontSize: 15, color: colors.onSurface, marginBottom: spacing.sm },
  dropEmpty: { color: colors.muted, fontSize: 14 },
  dropItem: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.divider },
  dropLabel: { color: colors.onSurface, fontSize: 14 },
  dropCount: { color: colors.error, fontWeight: "800", fontSize: 14 },
  userBox: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  avatar: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  avatarText: { color: colors.brandPrimary, fontWeight: "800" },
  userName: { color: colors.onSurface, fontWeight: "700", fontSize: 14 },
  userRole: { color: colors.muted, fontSize: 12 },
  signOutBtn: { paddingHorizontal: spacing.md, height: 38, borderRadius: radius.md, borderWidth: 1, borderColor: colors.borderStrong, justifyContent: "center" },
  signOutText: { color: colors.onSurface, fontWeight: "700", fontSize: 14 },
  content: { flex: 1, minWidth: 0 },
  pageHeader: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: spacing.md, marginBottom: spacing.lg },
  pageTitle: { fontSize: 26, fontWeight: "800", color: colors.onSurface, fontFamily: typography.fontFamily },
  pageSub: { color: colors.muted, fontSize: 15, marginTop: 2 },
  pageActions: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
}));
