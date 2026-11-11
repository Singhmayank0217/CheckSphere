import { useState } from "react";
import { FlatList, Pressable, ScrollView, Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/src/api";
import { SelectField, TextField } from "@/src/components/fields";
import { Banner, Btn, Card, Loading, PopupModal, Screen, SectionTitle, showToast } from "@/src/components/ui";
import { makeStyles, radius, spacing, typography } from "@/src/theme";

const ROLE_CHIPS = [
  { key: "", label: "All" },
  { key: "agent", label: "Agents" },
  { key: "supervisor", label: "Supervisors" },
  { key: "super_admin", label: "Super Admins" },
];

export default function Users() {
  const queryClient = useQueryClient();
  const styles = useStyles();
  const [role, setRole] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [resetFor, setResetFor] = useState<any>(null);
  const [sessionsFor, setSessionsFor] = useState<any>(null);
  const [form, setForm] = useState<any>({ name: "", role: "agent", agent_id: "", email: "", phone: "", password: "" });
  const [newPassword, setNewPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const usersQ = useQuery({ queryKey: ["users", role], queryFn: () => api<{ items: any[] }>(`/users${role ? `?role=${role}` : ""}`) });
  const sessionsQ = useQuery({
    queryKey: ["user-sessions", sessionsFor?.id],
    queryFn: () => api<{ items: any[] }>(`/users/${sessionsFor.id}/sessions`),
    enabled: !!sessionsFor,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["users"] });

  const createUser = async () => {
    setBusy(true);
    try {
      await api("/users", {
        method: "POST",
        body: {
          name: form.name, role: form.role,
          agent_id: form.role === "agent" && form.agent_id ? form.agent_id : null,
          email: form.email || null, phone: form.phone || null,
          password: form.password, scope: {},
        },
      });
      showToast("User created — share the temporary password separately", "success");
      setCreateOpen(false);
      setForm({ name: "", role: "agent", agent_id: "", email: "", phone: "", password: "" });
      invalidate();
    } catch (e: any) {
      showToast(e?.message ?? "Create failed", "error");
    } finally {
      setBusy(false);
    }
  };

  const resetPassword = async () => {
    setBusy(true);
    try {
      await api(`/users/${resetFor.id}/reset-password`, { method: "POST", body: { password: newPassword } });
      showToast("Password reset — all sessions revoked", "success");
      setResetFor(null);
      setNewPassword("");
      invalidate();
    } catch (e: any) {
      showToast(e?.message ?? "Reset failed", "error");
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (u: any) => {
    try {
      await api(`/users/${u.id}/set-active`, { method: "POST", body: { active: !!u.disabled } });
      showToast(u.disabled ? "User activated" : "User deactivated — sessions revoked", "success");
      invalidate();
    } catch (e: any) {
      showToast(e?.message ?? "Failed", "error");
    }
  };

  const revoke = async (sid: string) => {
    try {
      await api(`/auth/sessions/${sid}/revoke`, { method: "POST" });
      showToast("Session revoked", "success");
      queryClient.invalidateQueries({ queryKey: ["user-sessions"] });
    } catch (e: any) {
      showToast(e?.message ?? "Failed", "error");
    }
  };

  return (
    <Screen testID="admin-users-screen">
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.md }}>
        <Text style={styles.title}>Users</Text>
        <Btn label="+ Create User" onPress={() => setCreateOpen(true)} testID="create-user-btn" />
      </View>

      <View style={styles.chipRow}>
        {ROLE_CHIPS.map((r) => (
          <Pressable key={r.key} style={[styles.chip, role === r.key && styles.chipActive]} onPress={() => setRole(r.key)} testID={`role-chip-${r.key || "all"}`}>
            <Text style={[styles.chipText, role === r.key && styles.chipTextActive]}>{r.label}</Text>
          </Pressable>
        ))}
      </View>

      {usersQ.isLoading ? (
        <Loading />
      ) : (
        <FlatList
          data={usersQ.data?.items ?? []}
          keyExtractor={(u) => u.id}
          contentContainerStyle={{ paddingBottom: spacing.xl }}
          renderItem={({ item: u }) => (
            <View style={styles.row} testID={`user-row-${u.agent_id ?? u.email ?? u.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.userName}>{u.name} <Text style={styles.roleTag}>({u.role.replace("_", " ")})</Text></Text>
                <Text style={styles.meta}>{u.agent_id ?? ""} {u.email ?? ""} {u.disabled ? "· DEACTIVATED" : ""}{u.must_change_password ? " · temp password active" : ""}</Text>
              </View>
              <View style={{ gap: spacing.xs, alignItems: "flex-end" }}>
                <View style={{ flexDirection: "row", gap: spacing.sm }}>
                  <Btn label="Reset" variant="secondary" small onPress={() => { setResetFor(u); setNewPassword(""); }} testID={`reset-password-btn-${u.id}`} />
                  <Btn label={u.disabled ? "Activate" : "Deactivate"} variant={u.disabled ? "secondary" : "danger"} small onPress={() => toggleActive(u)} testID={`toggle-active-btn-${u.id}`} />
                  <Btn label="Sessions" variant="ghost" small onPress={() => setSessionsFor(u)} testID={`sessions-btn-${u.id}`} />
                </View>
              </View>
            </View>
          )}
        />
      )}

      <PopupModal visible={createOpen} title="Create User" onClose={() => setCreateOpen(false)}>
        <SelectField label="Role" value={form.role.replace("_", " ")} options={["agent", "supervisor", "super admin"]}
          onChange={(v) => setForm({ ...form, role: v === "super admin" ? "super_admin" : v })} testID="create-role-select" />
        <TextField label="Full Name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} testID="create-name-input" />
        {form.role === "agent" ? (
          <TextField label="Agent ID (blank = auto)" value={form.agent_id} onChange={(v) => setForm({ ...form, agent_id: v })} testID="create-agent-id-input" />
        ) : null}
        <TextField label="Email" value={form.email} onChange={(v) => setForm({ ...form, email: v })} testID="create-email-input" />
        <TextField label="Mobile" value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} testID="create-phone-input" />
        <TextField label="Temporary Password (min 8 chars)" value={form.password} onChange={(v) => setForm({ ...form, password: v })} testID="create-password-input" />
        <Btn label="Create User" onPress={createUser} loading={busy} testID="create-user-submit-btn" full />
      </PopupModal>

      <PopupModal visible={!!resetFor} title={`Reset Password — ${resetFor?.name ?? ""}`} onClose={() => setResetFor(null)}>
        <Banner tone="warning" message="The user must change this password at next login and all their sessions will be revoked." />
        <TextField label="New Temporary Password" value={newPassword} onChange={setNewPassword} testID="reset-password-input" />
        <Btn label="Reset Password" onPress={resetPassword} loading={busy} disabled={newPassword.length < 8} testID="reset-password-submit-btn" full />
      </PopupModal>

      <PopupModal visible={!!sessionsFor} title={`Sessions — ${sessionsFor?.name ?? ""}`} onClose={() => setSessionsFor(null)}>
        <ScrollView style={{ maxHeight: 360 }}>
          {(sessionsQ.data?.items ?? []).length === 0 ? <Text style={styles.meta}>No sessions</Text> : null}
          {(sessionsQ.data?.items ?? []).map((s: any) => (
            <View key={s.id} style={styles.sessionRow} testID={`session-${s.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.sessionTitle}>{s.device_model || "Unknown device"} {s.revoked_at ? "(revoked)" : ""}</Text>
                <Text style={styles.meta}>{s.device_id?.slice(0, 12)}… · IP {s.ip ?? "-"} · {s.created_at ? new Date(s.created_at).toLocaleString() : ""}</Text>
              </View>
              {!s.revoked_at ? (
                <Btn label="Revoke" variant="danger" small onPress={() => revoke(s.id)} testID={`revoke-session-btn-${s.id}`} />
              ) : null}
            </View>
          ))}
        </ScrollView>
      </PopupModal>
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  title: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, fontFamily: typography.fontFamily },
  chipRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.md, flexWrap: "wrap" },
  chip: { height: 36, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary, justifyContent: "center" },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipText: { color: colors.onSurfaceSecondary, fontSize: typography.scale.sm, fontWeight: "600" },
  chipTextActive: { color: colors.onBrandPrimary },
  row: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, marginBottom: spacing.sm, flexDirection: "row", gap: spacing.sm,
  },
  userName: { color: colors.onSurface, fontWeight: "700", fontSize: typography.scale.base },
  roleTag: { color: colors.muted, fontWeight: "500" },
  meta: { color: colors.muted, fontSize: typography.scale.sm },
  sessionRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider, paddingVertical: spacing.sm },
  sessionTitle: { color: colors.onSurface, fontWeight: "600", fontSize: typography.scale.sm },
}));
