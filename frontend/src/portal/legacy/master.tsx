import { useState } from "react";
import { Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/src/api";
import { SelectField, TextField } from "@/src/components/fields";
import { Btn, Card, DisplayRow, Loading, Screen, SectionTitle, showToast } from "@/src/components/ui";
import { makeStyles, spacing, typography } from "@/src/theme";

export default function MasterData({ section = "all" }: { section?: "all" | "clients" | "settings" }) {
  const queryClient = useQueryClient();
  const styles = useStyles();

  const clientsQ = useQuery({ queryKey: ["clients"], queryFn: () => api<{ items: any[] }>("/clients") });
  const branchesQ = useQuery({ queryKey: ["branches", "all"], queryFn: () => api<{ items: any[] }>("/branches") });
  const regionsQ = useQuery({ queryKey: ["regions"], queryFn: () => api<any>("/regions") });
  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: () => api<any>("/settings") });

  const [client, setClient] = useState({ name: "", code: "" });
  const [branch, setBranch] = useState({ client_id: "", name: "", city: "", state: "" });
  const [settings, setSettings] = useState<Record<string, any>>({});
  const [busy, setBusy] = useState(false);

  const s = settingsQ.data;
  const settingsValue = { ...s, ...settings };
  const blockedText = Array.isArray(settingsValue.blocked_words) ? settingsValue.blocked_words.join(", ") : "";

  const addClient = async () => {
    setBusy(true);
    try {
      await api("/clients", { method: "POST", body: client });
      showToast("Client created", "success");
      setClient({ name: "", code: "" });
      queryClient.invalidateQueries({ queryKey: ["clients"] });
    } catch (e: any) { showToast(e?.message ?? "Failed", "error"); } finally { setBusy(false); }
  };

  const addBranch = async () => {
    setBusy(true);
    try {
      await api("/branches", { method: "POST", body: branch });
      showToast("Branch created", "success");
      setBranch({ client_id: "", name: "", city: "", state: "" });
      queryClient.invalidateQueries({ queryKey: ["branches"] });
      queryClient.invalidateQueries({ queryKey: ["regions"] });
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
        {(clientsQ.data?.items ?? []).map((c: any) => (
          <DisplayRow key={c.id} label={c.name} value={c.code ?? ""} />
        ))}
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
        <SectionTitle>Branches</SectionTitle>
        {(branchesQ.data?.items ?? []).map((b: any) => (
          <DisplayRow key={b.id} label={b.name} value={`${b.city ?? "-"}, ${b.state ?? "-"}`} />
        ))}
        <SelectField
          label="Client"
          value={clientsQ.data?.items.find((c: any) => c.id === branch.client_id)?.name}
          options={clientsQ.data?.items.map((c: any) => c.name) ?? []}
          onChange={(v) => setBranch({ ...branch, client_id: clientsQ.data?.items.find((c: any) => c.name === v)?.id ?? "" })}
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
}));
