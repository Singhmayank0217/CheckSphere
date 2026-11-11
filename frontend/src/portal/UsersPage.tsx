import { useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/src/api";
import { TextField } from "@/src/components/fields";
import { Banner, Btn, PopupModal, showToast } from "@/src/components/ui";
import { DataTable } from "@/src/portal/DataTable";
import { Page } from "@/src/portal/Page";
import { PageHeader } from "@/src/portal/Shell";
import { useSession } from "@/src/session";
import { makeStyles, radius, spacing } from "@/src/theme";

const fmt = (d?: string) => (d ? new Date(d).toLocaleString() : "Never");

function Chips({ label, items, selected, onToggle, testID }: { label: string; items: { id: string; name: string }[]; selected: string[]; onToggle: (id: string) => void; testID: string }) {
  const styles = useStyles();
  return (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.chips}>
        {items.map((i) => (
          <Pressable key={i.id} onPress={() => onToggle(i.id)} style={[styles.chip, selected.includes(i.id) && styles.chipOn]} testID={`${testID}-${i.id}`}>
            <Text style={[styles.chipText, selected.includes(i.id) && styles.chipTextOn]}>{i.name}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

export default function UsersPage({ roles, readOnly = false }: { roles: ("agent" | "supervisor" | "super_admin")[]; readOnly?: boolean }) {
  const styles = useStyles();
  const qc = useQueryClient();
  const { user: me } = useSession();
  const [role, setRole] = useState(roles[0]);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<any>({ name: "", agent_id: "", email: "", phone: "", password: "" });
  const [sel, setSel] = useState<any>(null);
  const [panel, setPanel] = useState<"details" | "scope" | "sessions" | "activity">("details");
  const [pwd, setPwd] = useState("");
  const [link, setLink] = useState("");
  const [scope, setScope] = useState<any>({});
  const [busy, setBusy] = useState(false);

  const usersQ = useQuery({ queryKey: ["users", role, q], queryFn: () => api<{ items: any[] }>(`/users?role=${role}${q ? `&q=${encodeURIComponent(q)}` : ""}`) });
  const sessQ = useQuery({ queryKey: ["user-sessions", sel?.id], queryFn: () => api<any>(`/users/${sel.id}/sessions`), enabled: !!sel && !readOnly });
  const actQ = useQuery({ queryKey: ["user-activity", sel?.id], queryFn: () => api<any>(`/users/${sel.id}/activity`), enabled: !!sel && !readOnly && panel === "activity" });
  const clientsQ = useQuery({ queryKey: ["clients"], queryFn: () => api<any>("/clients") });
  const branchesQ = useQuery({ queryKey: ["branches", "all"], queryFn: () => api<any>("/branches") });
  const regionsQ = useQuery({ queryKey: ["regions"], queryFn: () => api<any>("/regions") });
  const agentsQ = useQuery({ queryKey: ["agents"], queryFn: () => api<any>("/users?role=agent"), enabled: role === "supervisor" });

  const refresh = () => { qc.invalidateQueries({ queryKey: ["users"] }); qc.invalidateQueries({ queryKey: ["user-sessions"] }); qc.invalidateQueries({ queryKey: ["agents"] }); };
  const run = async (fn: () => Promise<any>, ok: string) => {
    setBusy(true);
    try { await fn(); showToast(ok, "success"); refresh(); return true; } catch (e: any) { showToast(e?.message ?? "Failed", "error"); return false; } finally { setBusy(false); }
  };
  const openUser = (u: any) => { setSel(u); setPanel("details"); setPwd(""); setLink(""); setScope({ client_ids: [], states: [], cities: [], branch_ids: [], agent_ids: [], ...(u.scope ?? {}) }); };
  const toggle = (k: string, v: string) => setScope((s: any) => ({ ...s, [k]: (s[k] ?? []).includes(v) ? s[k].filter((x: string) => x !== v) : [...(s[k] ?? []), v] }));
  const titles: Record<string, string> = { agent: "Agents", supervisor: "Supervisors", super_admin: "Super Admins" };
  const items = usersQ.data?.items ?? [];
  const rows = items.slice((page - 1) * 25, page * 25);
  const str = (a?: string[]) => (a ?? []).map((x) => ({ id: x, name: x }));

  return (
    <Page testID={`portal-users-${role}`}>
      <PageHeader
        title={readOnly ? "My Team" : roles.length > 1 ? "Supervisors and Super Admins" : titles[role]}
        subtitle={readOnly ? "Field agents working on cases in your scope" : "Create accounts, reset passwords, manage sessions and access scope"}
        actions={readOnly ? null : <Btn label={`+ Create ${role === "agent" ? "Agent" : role === "supervisor" ? "Supervisor" : "Super Admin"}`} onPress={() => setCreateOpen(true)} testID="create-user-btn" />}
      />
      <View style={{ flexDirection: "row", gap: spacing.md, alignItems: "flex-end", flexWrap: "wrap", marginBottom: spacing.md }}>
        {roles.length > 1 ? roles.map((r) => (
          <Pressable key={r} onPress={() => { setRole(r); setPage(1); }} style={[styles.chip, role === r && styles.chipOn]} testID={`role-tab-${r}`}>
            <Text style={[styles.chipText, role === r && styles.chipTextOn]}>{titles[r]}</Text>
          </Pressable>
        )) : null}
        <View style={{ width: 320 }}><TextField label="Search name, ID, email or mobile" value={q} onChange={(v) => { setQ(v); setPage(1); }} testID="users-search-input" /></View>
      </View>
      <DataTable
        testID="users-table"
        rows={rows}
        loading={usersQ.isLoading}
        onRowPress={readOnly ? undefined : openUser}
        page={page} total={items.length} limit={25} onPage={setPage}
        columns={[
          { key: "name", label: "Name", width: 190, render: (u) => <Text style={styles.name}>{u.name}</Text> },
          { key: "agent_id", label: "ID", width: 100 },
          { key: "email", label: "Email", width: 220 },
          { key: "phone", label: "Mobile", width: 130 },
          { key: "status", label: "Status", width: 170, render: (u) => <Text style={u.disabled ? styles.off : styles.on}>{u.disabled ? "Deactivated" : u.must_change_password ? "Active · temp password" : "Active"}</Text> },
          { key: "last_login_at", label: "Last Login", width: 190, render: (u) => <Text style={styles.cell}>{fmt(u.last_login_at)}{u.last_login_ip ? `\nIP ${u.last_login_ip}` : ""}</Text> },
          ...(role === "supervisor" ? [{ key: "scope", label: "Scope", width: 200, render: (u: any) => {
            const s = u.scope ?? {}; const n = ["client_ids", "states", "cities", "branch_ids", "agent_ids"].reduce((a, k) => a + (s[k]?.length ?? 0), 0);
            return <Text style={styles.cell}>{n ? `${n} scope rules` : "All cases (no scope set)"}</Text>;
          } }] : []),
        ]}
      />

      <PopupModal visible={createOpen} title={`Create ${titles[role].slice(0, -1)}`} onClose={() => setCreateOpen(false)}>
        <TextField label="Full name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} testID="create-name-input" />
        {role === "agent" ? <TextField label="Agent ID (blank = auto)" value={form.agent_id} onChange={(v) => setForm({ ...form, agent_id: v })} testID="create-agent-id-input" /> : null}
        <TextField label="Email" value={form.email} onChange={(v) => setForm({ ...form, email: v })} keyboardType="email-address" testID="create-email-input" />
        <TextField label="Mobile" value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} testID="create-phone-input" />
        <TextField label="Temporary password (min 8)" value={form.password} onChange={(v) => setForm({ ...form, password: v })} testID="create-password-input" />
        <Btn label="Create account" loading={busy} disabled={!form.name || form.password.length < 8} testID="create-user-submit-btn" full onPress={async () => {
          const ok = await run(() => api("/users", { method: "POST", body: { name: form.name, role, agent_id: role === "agent" && form.agent_id ? form.agent_id : null, email: form.email || null, phone: form.phone || null, password: form.password, scope: {} } }), "Account created — share the temporary password separately");
          if (ok) { setCreateOpen(false); setForm({ name: "", agent_id: "", email: "", phone: "", password: "" }); }
        }} />
      </PopupModal>

      <PopupModal wide visible={!!sel} title={sel?.name ?? ""} onClose={() => setSel(null)}>
        <View style={[styles.chips, { marginBottom: spacing.md }]}>
          {(["details", ...(sel?.role === "supervisor" ? ["scope"] : []), "sessions", "activity"] as const).map((p) => (
            <Pressable key={p} onPress={() => setPanel(p as any)} style={[styles.chip, panel === p && styles.chipOn]} testID={`user-panel-${p}`}>
              <Text style={[styles.chipText, panel === p && styles.chipTextOn]}>{p[0].toUpperCase() + p.slice(1)}</Text>
            </Pressable>
          ))}
        </View>
        <ScrollView style={{ maxHeight: 460 }}>
          {panel === "details" && sel ? (
            <View>
              <Text style={styles.cell}>{sel.role} · {sel.agent_id ?? ""} {sel.email ?? ""} · Last login {fmt(sel.last_login_at)} {sel.last_login_device ? `(${sel.last_login_device})` : ""}</Text>
              <View style={{ height: spacing.md }} />
              <TextField label="New temporary password" value={pwd} onChange={setPwd} testID="reset-password-input" />
              <View style={styles.row}>
                <Btn label="Reset Password" small disabled={pwd.length < 8} loading={busy} onPress={() => run(() => api(`/users/${sel.id}/reset-password`, { method: "POST", body: { password: pwd } }), "Password reset — sessions revoked")} testID="reset-password-btn" />
                <Btn label="Create Activation Link" variant="secondary" small onPress={() => run(async () => { const r = await api<any>(`/users/${sel.id}/activation-link`, { method: "POST" }); setLink(`${typeof window !== "undefined" ? window.location.origin : ""}${r.path}`); }, "Activation link created (valid 72 hours)")} testID="activation-link-btn" />
                <Btn label={sel.disabled ? "Activate" : "Deactivate"} variant={sel.disabled ? "secondary" : "danger"} small disabled={sel.id === me?.id} onPress={async () => { if (await run(() => api(`/users/${sel.id}/set-active`, { method: "POST", body: { active: !!sel.disabled } }), sel.disabled ? "Activated" : "Deactivated — sessions revoked")) setSel({ ...sel, disabled: !sel.disabled }); }} testID="toggle-active-btn" />
                <Btn label="Sign Out Everywhere" variant="danger" small disabled={sel.id === me?.id} onPress={() => run(() => api(`/users/${sel.id}/revoke-all`, { method: "POST" }), "All sessions revoked")} testID="revoke-all-btn" />
              </View>
              {link ? <Banner tone="info" message={`Share separately (not via WhatsApp/personal email): ${link}`} /> : null}
            </View>
          ) : null}
          {panel === "scope" && sel ? (
            <View>
              <Banner tone="info" message="The supervisor sees cases matching ANY selected rule. With no rules selected, they see all cases." />
              <Chips label="Clients" testID="scope-client" items={(clientsQ.data?.items ?? []).map((c: any) => ({ id: c.id, name: c.name }))} selected={scope.client_ids ?? []} onToggle={(v) => toggle("client_ids", v)} />
              <Chips label="States" testID="scope-state" items={str(regionsQ.data?.states)} selected={scope.states ?? []} onToggle={(v) => toggle("states", v)} />
              <Chips label="Cities" testID="scope-city" items={str(regionsQ.data?.cities)} selected={scope.cities ?? []} onToggle={(v) => toggle("cities", v)} />
              <Chips label="Branches" testID="scope-branch" items={(branchesQ.data?.items ?? []).map((b: any) => ({ id: b.id, name: b.name }))} selected={scope.branch_ids ?? []} onToggle={(v) => toggle("branch_ids", v)} />
              <Chips label="Agents (team)" testID="scope-agent" items={(agentsQ.data?.items ?? []).map((a: any) => ({ id: a.id, name: a.name }))} selected={scope.agent_ids ?? []} onToggle={(v) => toggle("agent_ids", v)} />
              <Btn label="Save Scope" loading={busy} onPress={() => run(() => api(`/users/${sel.id}`, { method: "PUT", body: { scope } }), "Scope saved")} testID="save-scope-btn" full />
            </View>
          ) : null}
          {panel === "sessions" ? (sessQ.data?.items ?? []).map((s: any) => (
            <View key={s.id} style={styles.listRow} testID={`session-${s.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{s.device_model || "Unknown device"} {s.revoked_at ? "· revoked" : "· active"}</Text>
                <Text style={styles.cell}>Device {String(s.device_id ?? "").slice(0, 12)} · IP {s.ip ?? "—"} · {fmt(s.created_at)} · last seen {fmt(s.last_seen_at)}</Text>
              </View>
              {!s.revoked_at ? <Btn label="Log out" variant="danger" small onPress={() => run(() => api(`/auth/sessions/${s.id}/revoke`, { method: "POST" }), "Session revoked")} testID={`revoke-session-${s.id}`} /> : null}
            </View>
          )) : null}
          {panel === "activity" ? (actQ.data?.items ?? []).map((a: any) => (
            <View key={a.id} style={styles.listRow}>
              <Text style={[styles.name, { flex: 1 }]}>{a.action.replace(/_/g, " ")}</Text>
              <Text style={styles.cell}>{fmt(a.created_at)} · IP {a.ip ?? "—"}</Text>
            </View>
          )) : null}
        </ScrollView>
      </PopupModal>
    </Page>
  );
}

const useStyles = makeStyles((colors) => ({
  label: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 6 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { height: 36, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary, justifyContent: "center", marginBottom: spacing.md },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipText: { color: colors.onSurfaceSecondary, fontWeight: "600", fontSize: 13 },
  chipTextOn: { color: colors.onBrandPrimary },
  name: { color: colors.onSurface, fontWeight: "700", fontSize: 14 },
  cell: { color: colors.onSurfaceTertiary, fontSize: 13 },
  on: { color: colors.success, fontWeight: "700" },
  off: { color: colors.error, fontWeight: "700" },
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.md },
  listRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.divider },
}));
