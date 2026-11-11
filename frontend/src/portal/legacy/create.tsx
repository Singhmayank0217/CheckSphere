import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import * as DocumentPicker from "expo-document-picker";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { API_URL, api, downloadFile } from "@/src/api";
import { uploadForm } from "@/src/utils/upload";
import { storage } from "@/src/utils/storage";
import { SelectField, TextField } from "@/src/components/fields";
import { Banner, Btn, Card, Screen, SectionTitle, showToast } from "@/src/components/ui";
import { makeStyles, spacing, typography } from "@/src/theme";

const BLANK = {
  client_case_id: "", applicant_name: "", co_applicant_name: "", seller_name: "", primary_phone: "", alt_phone: "", loan_type: "",
  report_type: "", assigned_address: "", pincode: "", bank_state: "", verification_state: "", city: "", state: "", priority: "Medium", due_at: "", notes: "",
};

export default function NewCases() {
  const queryClient = useQueryClient();
  const styles = useStyles();
  const [form, setForm] = useState<any>({ ...BLANK });
  const [clientId, setClientId] = useState("");
  const [branchId, setBranchId] = useState("");
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<any>(null);

  const clientsQ = useQuery({ queryKey: ["clients"], queryFn: () => api<{ items: any[] }>("/clients") });
  const branchesQ = useQuery({ queryKey: ["branches", clientId], queryFn: () => api<{ items: any[] }>(`/branches${clientId ? `?client_id=${clientId}` : ""}`), enabled: !!clientId });
  const typesQ = useQuery({ queryKey: ["report-types"], queryFn: () => api<any>("/report-types") });

  const set = (k: string, v: string) => setForm((f: any) => ({ ...f, [k]: v }));

  const create = async () => {
    if (!clientId || !form.client_case_id || !form.applicant_name || !form.report_type || !form.assigned_address || !form.primary_phone) {
      showToast("Client, Client Case ID, Applicant, Primary Contact, Report Type and Address are required", "error");
      return;
    }
    if (form.pincode && !/^\d{6}$/.test(form.pincode)) {
      showToast("Pincode must be 6 digits", "error");
      return;
    }
    setBusy(true);
    try {
      await api("/cases", {
        method: "POST",
        body: {
          ...form,
          client_id: clientId,
          branch_id: branchId || null,
          due_at: form.due_at ? new Date(form.due_at + "T18:00:00Z").toISOString() : null,
        },
      });
      showToast("Case created", "success");
      setForm({ ...BLANK });
      queryClient.invalidateQueries({ queryKey: ["admin-cases"] });
      queryClient.invalidateQueries({ queryKey: ["admin-stats"] });
    } catch (e: any) {
      showToast(e?.message ?? "Create failed", "error");
    } finally {
      setBusy(false);
    }
  };

  const importExcel = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      multiple: false,
      copyToCacheDirectory: true,
    });
    if (result.canceled || !result.assets?.[0]) return;
    const asset = result.assets[0];
    setImporting(true);
    setImportResult(null);
    try {
      const token = await storage.secureGet("auth_token", null);
      const res = await uploadForm(`${API_URL}/api/cases/import`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        files: {
          file: {
            uri: asset.uri, name: asset.name ?? "import.xlsx",
            mimeType: asset.mimeType ?? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          },
        },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "Import failed");
      setImportResult(data);
      queryClient.invalidateQueries({ queryKey: ["admin-cases"] });
      queryClient.invalidateQueries({ queryKey: ["admin-stats"] });
      showToast(`${data.created} cases imported`, "success");
    } catch (e: any) {
      showToast(e?.message ?? "Import failed", "error");
    } finally {
      setImporting(false);
    }
  };

  const downloadTemplate = async () => {
    try {
      await downloadFile("/cases/import-template", "checksphere-case-import-template.xlsx");
    } catch (e: any) {
      showToast(e?.message ?? "Download failed", "error");
    }
  };

  const types = typesQ.data?.items ?? [];

  return (
    <Screen testID="admin-new-cases-screen">
      <Text style={styles.title}>Create & Import Cases</Text>

      <Card>
        <SectionTitle>Manual Case Creation</SectionTitle>
        <View style={{ flexDirection: "row", gap: spacing.md, flexWrap: "wrap" }}>
          <View style={{ flex: 1, minWidth: 180 }}>
            <SelectField label="Client" value={clientsQ.data?.items.find((c: any) => c.id === clientId)?.name}
              options={clientsQ.data?.items.map((c: any) => c.name) ?? []}
              onChange={(v) => { setClientId(clientsQ.data?.items.find((c: any) => c.name === v)?.id ?? ""); setBranchId(""); }}
              testID="new-case-client-select" />
          </View>
          <View style={{ flex: 1, minWidth: 180 }}>
            <SelectField label="Branch" value={branchesQ.data?.items.find((b: any) => b.id === branchId)?.name}
              options={branchesQ.data?.items.map((b: any) => b.name) ?? []}
              onChange={(v) => setBranchId(branchesQ.data?.items.find((b: any) => b.name === v)?.id ?? "")}
              testID="new-case-branch-select" />
          </View>
        </View>
        <View style={{ flexDirection: "row", gap: spacing.md, flexWrap: "wrap" }}>
          <View style={{ flex: 1, minWidth: 180 }}>
            <SelectField label="Report Type" value={types.find((t: any) => t.key === form.report_type)?.name}
              options={types.map((t: any) => t.name)}
              onChange={(v) => set("report_type", types.find((t: any) => t.name === v)?.key ?? "")}
              testID="new-case-type-select" />
          </View>
          <View style={{ flex: 1, minWidth: 180 }}>
            <SelectField label="Priority" value={form.priority} options={["High", "Medium", "Low"]}
              onChange={(v) => set("priority", v)} testID="new-case-priority-select" />
          </View>
        </View>
        <TextField label="Client Case ID *" value={form.client_case_id} onChange={(v) => set("client_case_id", v)} testID="new-case-client-case-id" />
        <View style={styles.row}>
          <View style={styles.col}><TextField label="Applicant Name *" value={form.applicant_name} onChange={(v) => set("applicant_name", v)} testID="new-case-applicant-input" /></View>
          <View style={styles.col}><TextField label="Co-applicant Name" value={form.co_applicant_name} onChange={(v) => set("co_applicant_name", v)} testID="new-case-coapplicant-input" /></View>
          <View style={styles.col}><TextField label="Seller Name" value={form.seller_name} onChange={(v) => set("seller_name", v)} testID="new-case-seller-input" /></View>
        </View>
        <View style={styles.row}>
          <View style={styles.col}><TextField label="Primary Contact Number *" value={form.primary_phone} onChange={(v) => set("primary_phone", v)} keyboardType="phone-pad" testID="new-case-phone-input" /></View>
          <View style={styles.col}><TextField label="Alternate Phone" value={form.alt_phone} onChange={(v) => set("alt_phone", v)} keyboardType="phone-pad" testID="new-case-alt-phone-input" /></View>
          <View style={styles.col}><TextField label="Bank State" value={form.bank_state} onChange={(v) => set("bank_state", v)} testID="new-case-bank-state-input" /></View>
        </View>
        <TextField label="Loan / Product Type" value={form.loan_type} onChange={(v) => set("loan_type", v)} testID="new-case-loan-input" />
        <TextField label="Full Address *" value={form.assigned_address} onChange={(v) => set("assigned_address", v)} multiline testID="new-case-address-input" />
        <View style={styles.row}>
          <View style={styles.col}><TextField label="Pincode" value={form.pincode} onChange={(v) => set("pincode", v)} keyboardType="numeric" testID="new-case-pincode-input" /></View>
          <View style={styles.col}><TextField label="State of Verification" value={form.verification_state} onChange={(v) => set("verification_state", v)} testID="new-case-ver-state-input" /></View>
          <View style={styles.col}><TextField label="City / District" value={form.city} onChange={(v) => set("city", v)} testID="new-case-city-input" /></View>
          <View style={styles.col}><TextField label="State" value={form.state} onChange={(v) => set("state", v)} testID="new-case-state-input" /></View>
          <View style={styles.col}><TextField label="SLA Due (YYYY-MM-DD)" value={form.due_at} onChange={(v) => set("due_at", v)} testID="new-case-due-input" /></View>
        </View>
        <TextField label="Notes" value={form.notes} onChange={(v) => set("notes", v)} multiline testID="new-case-notes-input" />
        <Btn label="Create Case" onPress={create} loading={busy} testID="new-case-submit-btn" full />
      </Card>

      <Card>
        <SectionTitle>Excel Import</SectionTitle>
        <Text style={styles.help}>
          Download the template, fill one case per row (Client Name and Report Type must match existing masters),
          then import. Cases are created in &quot;New&quot; status ready for assignment.
        </Text>
        <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
          <Btn label="Download Template" variant="secondary" small onPress={downloadTemplate} testID="import-template-btn" />
          <Btn label={importing ? "Importing…" : "Choose .xlsx File"} variant="secondary" small onPress={importExcel} loading={importing} testID="import-file-btn" />
        </View>
        {importResult ? (
          <View style={{ marginTop: spacing.md }}>
            <Banner tone="success" message={`${importResult.created} cases created.`} />
            {(importResult.errors ?? []).length > 0 ? (
              <ScrollView style={{ maxHeight: 140, backgroundColor: "#F0EDE6", borderRadius: 8, padding: 8 }}>
                {importResult.errors.map((err: string, i: number) => (
                  <Text key={i} style={{ color: "#9E2A2B", fontSize: 12 }}>{err}</Text>
                ))}
              </ScrollView>
            ) : null}
          </View>
        ) : null}
      </Card>
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  title: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.md, fontFamily: typography.fontFamily },
  help: { color: colors.muted, fontSize: typography.scale.sm, lineHeight: 18, marginBottom: spacing.md },
  row: { flexDirection: "row", gap: spacing.md, flexWrap: "wrap" },
  col: { flex: 1, minWidth: 180 },
  fileLabel: {
    alignSelf: "center", backgroundColor: colors.brandTertiary, borderWidth: 1, borderColor: colors.brandPrimary,
    borderRadius: 12, paddingHorizontal: 16, minHeight: 36, justifyContent: "center", display: "flex", alignItems: "center",
  },
}));
