import { useState } from "react";
import { Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/src/api";
import { SelectField, TextField } from "@/src/components/fields";
import { Btn, Card, DisplayRow, Loading, PopupModal, Screen, SectionTitle, showToast } from "@/src/components/ui";
import { makeStyles, spacing, typography } from "@/src/theme";

export default function MasterData({ section = "all" }: { section?: "all" | "clients" | "settings" }) {
  const queryClient = useQueryClient();
  const styles = useStyles();

  // Management view (Super Admin portal only): includes deactivated clients/branches. Own query keys so the active-only
  // lists used by case forms are never mixed with inactive entries.
  const clientsQ = useQuery({ queryKey: ["clients", "manage"], queryFn: () => api<{ items: any[] }>("/clients?include_inactive=true"),
    enabled: section !== "settings" });
  const branchesQ = useQuery({ queryKey: ["branches", "manage"], queryFn: () => api<{ items: any[] }>("/branches?include_inactive=true"),
    enabled: section !== "settings" });
  const regionsQ = useQuery({ queryKey: ["regions"], queryFn: () => api<any>("/regions") });
  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: () => api<any>("/settings") });

  const [client, setClient] = useState({ name: "", code: "" });
  const [branch, setBranch] = useState({ client_id: "", name: "", city: "", state: "" });
  const [settings, setSettings] = useState<Record<string, any>>({});
  const [busy, setBusy] = useState(false);
  type EditState = { kind: "client" | "branch"; id: string; name: string; code: string; city: string; state: string };
  const [editing, setEditing] = useState<EditState | null>(null);
  const [confirm, setConfirm] = useState<{ kind: "client" | "branch"; id: string; name: string; active: boolean } | null>(null);
  const activeClients = (clientsQ.data?.items ?? []).filter((c: any) => c.active !== false);

  const refreshMasters = () => {
    queryClient.invalidateQueries({ queryKey: ["clients"] });
    queryClient.invalidateQueries({ queryKey: ["branches"] });
    queryClient.invalidateQueries({ queryKey: ["regions"] });
  };

  const saveEdit = async () => {
    if (!editing) return;
    setBusy(true);
    try {
      const body = editing.kind === "client"
        ? { name: editing.name, code: editing.code }
        : { name: editing.name, city: editing.city, state: editing.state };
      await api(`/${editing.kind === "client" ? "clients" : "branches"}/${editing.id}`, { method: "PUT", body });
      showToast(editing.kind === "client" ? "Client updated" : "Branch updated", "success");
      setEditing(null);
      refreshMasters();
    } catch (e: any) { showToast(e?.message ?? "Failed", "error"); } finally { setBusy(false); }
  };

  const setActive = async (kind: "client" | "branch", id: string, active: boolean) => {
    setBusy(true);
    try {
      await api(`/${kind === "client" ? "clients" : "branches"}/${id}/set-active`, { method: "POST", body: { active } });
      showToast(`${kind === "client" ? "Client" : "Branch"} ${active ? "activated" : "deactivated"}`, "success");
      setConfirm(null);
      refreshMasters();
    } catch (e: any) { showToast(e?.message ?? "Failed", "error"); } finally { setBusy(false); }
  };

  const s = settingsQ.data;
  const settingsValue = { ...s, ...settings };
  const blockedText = Array.isArray(settingsValue.blocked_words) ? settingsValue.blocked_words.join(", ") : "";

  const addClient = async () => {
    setBusy(true);
    try {
      await api("/clients", { method: "POST", body: client });
      showToast("Client created", "success");
      setClient({ name: "", code: "" });
      refreshMasters();
    } catch (e: any) { showToast(e?.message ?? "Failed", "error"); } finally { setBusy(false); }
  };

  const addBranch = async () => {
    setBusy(true);
    try {
      await api("/branches", { method: "POST", body: branch });
      showToast("Branch created", "success");
      setBranch({ client_id: "", name: "", city: "", state: "" });
      refreshMasters();
    } catch (e: any) { showToast(e?.message ?? "Failed", "error"); } finally { setBusy(false); }
  };

  const saveSettings = async () => {
    setBusy(true);
    try {
      const updates: any = {
        flag_distance_m: Number(settingsValue.flag_distance_m),
        flag_accuracy_m: Number(settingsValue.flag_accuracy_m),
        flag_travel_kmh: Number(settingsValue.flag_travel_kmh),
        flag_same_place_min: Number(settingsValue.flag_same_place_min),
        telephone_min_attempts: Number(settingsValue.telephone_min_attempts),
        retention_days: Number(settingsValue.retention_days),
        company_name: settingsValue.company_name,
        blocked_words: blockedText.split(",").map((w: string) => w.trim()).filter(Boolean),
      };
      await api("/settings", { method: "PUT", body: { updates } });
      showToast("Settings saved", "success");
      setSettings({});
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    } catch (e: any) { showToast(e?.message ?? "Failed", "error"); } finally { setBusy(false); }
  };

  if (settingsQ.isLoading) return <Screen><Loading /></Screen>;

  return (
    <Screen testID="admin-master-screen">
      <Text style={styles.title}>{section === "clients" ? "Clients and Branches" : section === "settings" ? "Settings" : "Master Data & Settings"}</Text>

      {section !== "settings" ? (<>
      <Card>
        <SectionTitle>Clients</SectionTitle>
        {(clientsQ.data?.items ?? []).length === 0 ? <Text style={styles.muted}>No clients yet. Add the first one below.</Text> : null}
        {(clientsQ.data?.items ?? []).map((c: any) => {
          const inactive = c.active === false;
          const branches = (branchesQ.data?.items ?? []).filter((b: any) => b.client_id === c.id);
          return (
            <View key={c.id} style={styles.masterRow} testID={`client-row-${c.id}`}>
              <View style={styles.rowHead}>
                <Text style={[styles.rowTitle, inactive && styles.inactiveText]}>{c.name}{c.code ? `  ·  ${c.code}` : ""}</Text>
                <Text style={[styles.badge, inactive ? styles.badgeOff : styles.badgeOn]}>{inactive ? "Inactive" : "Active"}</Text>
                <Btn label="Edit" small variant="secondary" testID={`edit-client-${c.id}`}
                  onPress={() => setEditing({ kind: "client", id: c.id, name: c.name ?? "", code: c.code ?? "", city: "", state: "" })} />
                <Btn label={inactive ? "Activate" : "Deactivate"} small variant={inactive ? "secondary" : "danger"} testID={`toggle-client-${c.id}`}
                  onPress={() => (inactive ? setActive("client", c.id, true) : setConfirm({ kind: "client", id: c.id, name: c.name, active: false }))} />
              </View>
              {branches.map((b: any) => {
                const bOff = b.active === false;
                return (
                  <View key={b.id} style={[styles.rowHead, styles.branchRow]} testID={`branch-row-${b.id}`}>
                    <Text style={[styles.branchTitle, bOff && styles.inactiveText]}>{b.name} — {b.city ?? "-"}, {b.state ?? "-"}</Text>
                    <Text style={[styles.badge, bOff ? styles.badgeOff : styles.badgeOn]}>{bOff ? "Inactive" : "Active"}</Text>
                    <Btn label="Edit" small variant="secondary" testID={`edit-branch-${b.id}`}
                      onPress={() => setEditing({ kind: "branch", id: b.id, name: b.name ?? "", code: "", city: b.city ?? "", state: b.state ?? "" })} />
                    <Btn label={bOff ? "Activate" : "Deactivate"} small variant={bOff ? "secondary" : "danger"} testID={`toggle-branch-${b.id}`}
                      onPress={() => (bOff ? setActive("branch", b.id, true) : setConfirm({ kind: "branch", id: b.id, name: b.name, active: false }))} />
                  </View>
                );
              })}
            </View>
          );
        })}
        <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
          <View style={{ flex: 2 }}>
            <TextField label="New Client Name" value={client.name} onChange={(v) => setClient({ ...client, name: v })} testID="client-name-input" />
          </View>
          <View style={{ flex: 1 }}>
            <TextField label="Code" value={client.code} onChange={(v) => setClient({ ...client, code: v })} testID="client-code-input" />
          </View>
        </View>
        <Btn label="Add Client" small onPress={addClient} loading={busy} disabled={!client.name} testID="add-client-btn" />
      </Card>

      <Card>
        <SectionTitle>Add Branch</SectionTitle>
        <SelectField
          label="Client"
          value={activeClients.find((c: any) => c.id === branch.client_id)?.name}
          options={activeClients.map((c: any) => c.name)}
          onChange={(v) => setBranch({ ...branch, client_id: activeClients.find((c: any) => c.name === v)?.id ?? "" })}
          testID="branch-client-select"
        />
        <TextField label="Branch Name" value={branch.name} onChange={(v) => setBranch({ ...branch, name: v })} testID="branch-name-input" />
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          <View style={{ flex: 1 }}>
            <TextField label="City" value={branch.city} onChange={(v) => setBranch({ ...branch, city: v })} testID="branch-city-input" />
          </View>
          <View style={{ flex: 1 }}>
            <TextField label="State" value={branch.state} onChange={(v) => setBranch({ ...branch, state: v })} testID="branch-state-input" />
          </View>
        </View>
        <Btn label="Add Branch" small onPress={addBranch} loading={busy} disabled={!branch.client_id || !branch.name} testID="add-branch-btn" />
      </Card>

      <Card>
        <SectionTitle>Regions (derived from branches)</SectionTitle>
        <DisplayRow label="States" value={(regionsQ.data?.states ?? []).join(", ") || "-"} />
        <DisplayRow label="Cities" value={(regionsQ.data?.cities ?? []).join(", ") || "-"} />
      </Card>

      <PopupModal visible={!!editing} title={editing?.kind === "client" ? "Edit Client" : "Edit Branch"} onClose={() => setEditing(null)}>
        {editing ? (<>
          <TextField label={editing.kind === "client" ? "Client Name" : "Branch Name"} value={editing.name}
            onChange={(v) => setEditing({ ...editing, name: v })} testID="edit-name-input" />
          {editing.kind === "client" ? (
            <TextField label="Code" value={editing.code} onChange={(v) => setEditing({ ...editing, code: v })} testID="edit-code-input" />
          ) : (<>
            <TextField label="City" value={editing.city} onChange={(v) => setEditing({ ...editing, city: v })} testID="edit-city-input" />
            <TextField label="State" value={editing.state} onChange={(v) => setEditing({ ...editing, state: v })} testID="edit-state-input" />
          </>)}
          <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
            <Btn label="Save" onPress={saveEdit} loading={busy} disabled={!editing.name.trim()} testID="edit-save-btn" />
            <Btn label="Cancel" variant="secondary" onPress={() => setEditing(null)} testID="edit-cancel-btn" />
          </View>
        </>) : null}
      </PopupModal>

      <PopupModal visible={!!confirm} title={`Deactivate ${confirm?.kind === "client" ? "client" : "branch"}?`} onClose={() => setConfirm(null)}>
        <Text style={styles.muted}>
          {confirm?.kind === "client"
            ? `"${confirm?.name}" and its branches will no longer be offered for new cases. Existing cases are not changed. You can activate it again at any time.`
            : `"${confirm?.name}" will no longer be offered for new cases. Existing cases are not changed. You can activate it again at any time.`}
        </Text>
        <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.md }}>
          <Btn label="Deactivate" variant="danger" loading={busy} onPress={() => confirm && setActive(confirm.kind, confirm.id, false)} testID="confirm-deactivate-btn" />
          <Btn label="Cancel" variant="secondary" onPress={() => setConfirm(null)} testID="cancel-deactivate-btn" />
        </View>
      </PopupModal>
      </>
      ) : null}
      {section !== "clients" ? (
      <Card>
        <SectionTitle>System Settings</SectionTitle>
        <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
          <View style={{ flex: 1, minWidth: 140 }}>
            <TextField label="Company Name" value={settingsValue.company_name} onChange={(v) => setSettings((p) => ({ ...p, company_name: v }))} testID="setting-company-input" />
          </View>
          <View style={{ flex: 1, minWidth: 140 }}>
            <TextField label="Flag: Distance (m)" value={String(settingsValue.flag_distance_m ?? "")} keyboardType="numeric" onChange={(v) => setSettings((p) => ({ ...p, flag_distance_m: v }))} testID="setting-distance-input" />
          </View>
        </View>
        <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
          <View style={{ flex: 1, minWidth: 140 }}>
            <TextField label="Flag: GPS Accuracy (m)" value={String(settingsValue.flag_accuracy_m ?? "")} keyboardType="numeric" onChange={(v) => setSettings((p) => ({ ...p, flag_accuracy_m: v }))} testID="setting-accuracy-input" />
          </View>
          <View style={{ flex: 1, minWidth: 140 }}>
            <TextField label="Flag: Travel (km/h)" value={String(settingsValue.flag_travel_kmh ?? "")} keyboardType="numeric" onChange={(v) => setSettings((p) => ({ ...p, flag_travel_kmh: v }))} testID="setting-travel-input" />
          </View>
        </View>
        <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
          <View style={{ flex: 1, minWidth: 140 }}>
            <TextField label="Same-place Window (min)" value={String(settingsValue.flag_same_place_min ?? "")} keyboardType="numeric" onChange={(v) => setSettings((p) => ({ ...p, flag_same_place_min: v }))} testID="setting-sameplace-input" />
          </View>
          <View style={{ flex: 1, minWidth: 140 }}>
            <TextField label="Telephone Min Attempts" value={String(settingsValue.telephone_min_attempts ?? "")} keyboardType="numeric" onChange={(v) => setSettings((p) => ({ ...p, telephone_min_attempts: v }))} testID="setting-telephone-input" />
          </View>
          <View style={{ flex: 1, minWidth: 140 }}>
            <TextField label="Retention (days)" value={String(settingsValue.retention_days ?? "")} keyboardType="numeric" onChange={(v) => setSettings((p) => ({ ...p, retention_days: v }))} testID="setting-retention-input" />
          </View>
        </View>
        <TextField
          label="Restricted Words in Agent Remarks (comma separated)"
          value={blockedText}
          onChange={(v) => setSettings((p) => ({ ...p, blocked_words: v.split(",").map((x) => x.trim()) }))}
          multiline
          testID="setting-blocked-words-input"
        />
        <Btn label="Save Settings" onPress={saveSettings} loading={busy} testID="save-settings-btn" full />
      </Card>
      ) : null}
      <View style={{ height: spacing.xl }} />
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  title: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.md, fontFamily: typography.fontFamily },
  muted: { color: colors.onSurfaceSecondary, fontSize: typography.scale.sm, marginBottom: spacing.sm },
  masterRow: { borderBottomWidth: 1, borderColor: colors.border, paddingVertical: spacing.sm },
  rowHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" },
  rowTitle: { flex: 1, minWidth: 160, fontSize: typography.scale.base, fontWeight: "700", color: colors.onSurface },
  branchRow: { paddingLeft: spacing.lg, marginTop: spacing.xs },
  branchTitle: { flex: 1, minWidth: 160, fontSize: typography.scale.sm, color: colors.onSurface },
  inactiveText: { color: colors.onSurfaceSecondary, textDecorationLine: "line-through" },
  badge: { fontSize: typography.scale.sm, fontWeight: "700", paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: 999, overflow: "hidden" },
  badgeOn: { backgroundColor: colors.success, color: colors.onSurfaceInverse },
  badgeOff: { backgroundColor: colors.border, color: colors.onSurface },
}));
