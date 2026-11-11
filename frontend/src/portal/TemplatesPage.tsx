import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/src/api";
import { SelectField, SwitchRow, TextField } from "@/src/components/fields";
import { Btn, Loading, showToast } from "@/src/components/ui";
import { Page, Panel } from "@/src/portal/Page";
import { PageHeader } from "@/src/portal/Shell";
import { makeStyles, radius, spacing } from "@/src/theme";

export default function TemplatesPage() {
  const styles = useStyles();
  const qc = useQueryClient();
  const typesQ = useQuery({ queryKey: ["report-types"], queryFn: () => api<any>("/report-types") });
  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: () => api<any>("/settings") });
  const [sel, setSel] = useState("residence_applicant");
  const [req, setReq] = useState<Record<string, boolean>>({});
  const [custom, setCustom] = useState<any[]>([]);
  const [nf, setNf] = useState({ label: "", type: "text", options: "", required: false });
  const [busy, setBusy] = useState(false);

  const cfg = typesQ.data?.configs?.[sel];
  useEffect(() => {
    if (!cfg) return;
    const m: Record<string, boolean> = {};
    cfg.sections.forEach((s: any) => s.fields.forEach((f: any) => { m[f.key] = !!f.required; }));
    setReq(m);
  }, [cfg]);
  useEffect(() => { if (settingsQ.data) setCustom(settingsQ.data.custom_form_fields ?? []); }, [settingsQ.data]);

  const save = async (updates: any, msg: string) => {
    setBusy(true);
    try { await api("/settings", { method: "PUT", body: { updates } }); showToast(msg, "success"); qc.invalidateQueries({ queryKey: ["report-types"] }); qc.invalidateQueries({ queryKey: ["settings"] }); }
    catch (e: any) { showToast(e?.message ?? "Save failed", "error"); } finally { setBusy(false); }
  };

  if (typesQ.isLoading || settingsQ.isLoading) return <Page><Loading /></Page>;
  return (
    <Page testID="portal-templates">
      <PageHeader title="Report Templates" subtitle="Configure mandatory fields per report type and the custom verification form" />
      <View style={styles.grid}>
        <Panel title="Report types" style={{ flexBasis: 300, flexGrow: 0 }}>
          {(typesQ.data?.items ?? []).map((t: any) => (
            <Pressable key={t.key} onPress={() => setSel(t.key)} style={[styles.type, sel === t.key && styles.typeOn]} testID={`template-${t.key}`}>
              <Text style={[styles.typeText, sel === t.key && styles.typeTextOn]}>{t.name}</Text>
              <Text style={styles.muted}>{t.category}</Text>
            </Pressable>
          ))}
        </Panel>
        <Panel title={`${cfg?.name ?? ""} — mandatory fields`} style={{ flexBasis: 480, flexGrow: 1, minWidth: 0 }}
          right={<Btn label="Save Mandatory Fields" small loading={busy} testID="save-required-btn"
            onPress={() => save({ required_overrides: { ...(settingsQ.data?.required_overrides ?? {}), [sel]: req } }, "Mandatory fields saved")} />}>
          <Text style={styles.muted}>GPS {cfg?.requires_gps ? "required" : "not required"} · Photos: {(cfg?.photo_slots ?? []).map((p: any) => `${p.label}${p.required ? " (required)" : ""}`).join(", ")}</Text>
          {(cfg?.sections ?? []).map((s: any) => (
            <View key={s.title} style={{ marginTop: spacing.md }}>
              <Text style={styles.section}>{s.title}</Text>
              {s.fields.map((f: any) => (
                <SwitchRow key={f.key} label={f.label} note={f.type} value={!!req[f.key]} onChange={(v) => setReq({ ...req, [f.key]: v })} testID={`required-${f.key}`} />
              ))}
            </View>
          ))}
        </Panel>
      </View>
      <Panel title="Custom Verification Form builder" right={<Btn label="Save Custom Form" small loading={busy} onPress={() => save({ custom_form_fields: custom }, "Custom form saved")} testID="save-custom-form-btn" />}>
        {custom.map((f, i) => (
          <View key={f.key} style={styles.customRow}>
            <Text style={[styles.typeText, { flex: 1 }]}>{f.label} <Text style={styles.muted}>({f.type}{f.options ? `: ${f.options.join(", ")}` : ""}){f.required ? " · required" : ""}</Text></Text>
            <Btn label="Remove" variant="ghost" small onPress={() => setCustom(custom.filter((_, j) => j !== i))} testID={`remove-custom-${f.key}`} />
          </View>
        ))}
        <View style={styles.addRow}>
          <View style={{ flexBasis: 240, flexGrow: 1 }}><TextField label="Field label" value={nf.label} onChange={(v) => setNf({ ...nf, label: v })} testID="custom-label-input" /></View>
          <View style={{ flexBasis: 160 }}><SelectField label="Type" value={nf.type} options={["text", "textarea", "number", "select"]} onChange={(v) => setNf({ ...nf, type: v })} testID="custom-type-select" /></View>
          {nf.type === "select" ? <View style={{ flexBasis: 240, flexGrow: 1 }}><TextField label="Options (comma separated)" value={nf.options} onChange={(v) => setNf({ ...nf, options: v })} testID="custom-options-input" /></View> : null}
          <View style={{ flexBasis: 160 }}><SwitchRow label="Required" value={nf.required} onChange={(v) => setNf({ ...nf, required: v })} testID="custom-required-switch" /></View>
          <Btn label="Add Field" variant="secondary" small disabled={!nf.label} testID="add-custom-field-btn" onPress={() => {
            const key = nf.label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
            setCustom([...custom, { key, label: nf.label, type: nf.type, required: nf.required, ...(nf.type === "select" ? { options: nf.options.split(",").map((o) => o.trim()).filter(Boolean) } : {}) }]);
            setNf({ label: "", type: "text", options: "", required: false });
          }} />
        </View>
      </Panel>
    </Page>
  );
}

const useStyles = makeStyles((colors) => ({
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.lg, alignItems: "flex-start" },
  type: { padding: spacing.md, borderRadius: radius.sm, marginBottom: 2 },
  typeOn: { backgroundColor: colors.brandTertiary },
  typeText: { color: colors.onSurface, fontWeight: "700", fontSize: 14 },
  typeTextOn: { color: colors.brandPrimary },
  muted: { color: colors.muted, fontSize: 12 },
  section: { fontWeight: "800", color: colors.onSurface, marginBottom: spacing.sm, fontSize: 15 },
  customRow: { flexDirection: "row", alignItems: "center", paddingVertical: 8, borderTopWidth: 1, borderTopColor: colors.divider },
  addRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, alignItems: "flex-end", marginTop: spacing.md },
}));
