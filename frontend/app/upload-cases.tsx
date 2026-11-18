// Agent "Upload New Cases": submit new case details + a PDF without prior approval. A submission is reviewed by a
// Supervisor; it is never treated as an approved or completed verification.
import { useRef, useState } from "react";
import { Linking, Platform, Text, View } from "react-native";
import * as DocumentPicker from "expo-document-picker";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { API_URL, api, newIdempotencyKey } from "@/src/api";
import { SelectField, TextField } from "@/src/components/fields";
import { BackHeader, Banner, Btn, Card, SectionTitle, StatusPill, showToast } from "@/src/components/ui";
import { RoleGate } from "@/src/portal/RoleGate";
import { useSession } from "@/src/session";
import { fmtIST } from "@/src/utils/geo";
import { fetch as expoFetch } from "expo/fetch";
import { DocumentError, discardPdf, pdfPart, PreparedPdf, preparePdf } from "@/src/utils/documents";
import { makeStyles, spacing } from "@/src/theme";

const EMPTY = { state: "", branch_name: "", applicant_name: "", co_applicant_name: "", co_applicant2_name: "", requirements: "" };
const PILL: Record<string, string> = { submitted: "submitted", under_review: "under_review", clarification: "returned", accepted: "approved", rejected: "exception" };

function UploadCasesScreen() {
  const insets = useSafeAreaInsets();
  const { token } = useSession();
  const qc = useQueryClient();
  const styles = useStyles();
  const [f, setF] = useState({ ...EMPTY });
  const [pdf, setPdf] = useState<PreparedPdf | null>(null);
  // One key per submission: pressing Submit again after a lost response replays the first result (no duplicate).
  const submitKey = useRef<string>(newIdempotencyKey());
  const [picking, setPicking] = useState(false);
  const [errs, setErrs] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const statesQ = useQuery({ queryKey: ["india-states"], queryFn: () => api<any>("/case-uploads/states") });
  const listQ = useQuery({ queryKey: ["my-case-uploads"], queryFn: () => api<any>("/case-uploads") });
  const set = (k: keyof typeof EMPTY) => (v: string) => setF((p) => ({ ...p, [k]: v }));

  // Copy the picked PDF into private app storage immediately and validate it (separate from the photo pipeline).
  const pick = async () => {
    const r = await DocumentPicker.getDocumentAsync({ type: ["application/pdf"], copyToCacheDirectory: true });
    if (r.canceled || !r.assets?.[0]) return;
    setPicking(true);
    try {
      const prepared = await preparePdf(r.assets[0] as any);
      discardPdf(pdf); // replace a previously selected, not-yet-uploaded copy
      setPdf(prepared);
      setErrs([]);
    } catch (e: any) {
      const msg = e instanceof DocumentError ? e.message : "The selected PDF is unavailable on this device. Please select the document again.";
      setErrs([msg]);
      showToast(msg, "error");
    } finally {
      setPicking(false);
    }
  };

  const submit = async () => {
    const e: string[] = [];
    if (!f.state) e.push("Choose a State");
    if (!f.branch_name.trim()) e.push("Branch Name is required");
    if (!f.applicant_name.trim()) e.push("Applicant Name is required");
    if (!f.co_applicant_name.trim()) e.push("Co-applicant Name is required");
    if (!pdf) e.push("Attach the PDF document");
    setErrs(e);
    if (e.length || !pdf) { showToast(e[0], "error"); return; }
    setBusy(true);
    try {
      const form = new FormData();
      for (const [k, v] of Object.entries(f)) form.append(k, v);
      form.append("file", pdfPart(pdf), pdf.name); // verified PDF bytes, original filename, application/pdf
      const headers: Record<string, string> = {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "Idempotency-Key": submitKey.current,
      };
      let res: Response;
      try {
        res = Platform.OS === "web"
          ? await fetch(`${API_URL}/api/case-uploads`, { method: "POST", body: form, headers })
          : (await expoFetch(`${API_URL}/api/case-uploads`, { method: "POST", body: form as any, headers })) as unknown as Response;
      } catch {
        const msg = "Network problem — your PDF is kept on this phone. Press Submit Upload again to retry.";
        setErrs([msg]);
        showToast(msg, "error");
        return;
      }
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const problems = body?.detail?.problems ?? [typeof body?.detail === "string" ? body.detail : "Upload failed — please retry"];
        setErrs(problems);
        showToast(problems[0], "error");
        return;
      }
      if (!body?.id) {
        setErrs(["The server did not confirm the upload. Your PDF is kept on this phone — please retry."]);
        return;
      }
      discardPdf(pdf); // only now: the server stored the PDF and returned the submission id
      showToast("Case uploaded — a Supervisor will review it", "success");
      setF({ ...EMPTY }); setPdf(null); setErrs([]);
      submitKey.current = newIdempotencyKey(); // the next case is a new submission
      qc.invalidateQueries({ queryKey: ["my-case-uploads"] });
    } catch (x: any) {
      const msg = x instanceof DocumentError ? x.message : x?.message ?? "Upload failed — please retry";
      setErrs([msg]);
      showToast(msg, "error");
    } finally {
      setBusy(false);
    }
  };

  const openPdf = (id: string) => {
    const url = `${API_URL}/api/case-uploads/${id}/pdf${token ? `?token=${token}` : ""}`;
    if (Platform.OS === "web") window.open(url, "_blank");
    else Linking.openURL(url);
  };

  return (
    <View style={styles.root} testID="upload-cases-screen">
      <KeyboardAwareScrollView bottomOffset={24} keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: spacing.lg, paddingTop: insets.top + spacing.sm, paddingBottom: insets.bottom + 48 }}>
        <BackHeader title="Upload New Cases" testID="upload-back-btn" />
        <Banner tone="info" message="Submit new case details with the PDF. No prior approval is needed; a Supervisor reviews the submission. It is not an approved or completed verification." />
        <Card>
          <SelectField label="State *" value={f.state} options={statesQ.data?.items ?? []} onChange={set("state")} testID="upl-state-select" />
          <TextField label="Branch Name *" value={f.branch_name} onChange={set("branch_name")} autoCapitalize="words" testID="upl-branch" />
          <TextField label="Applicant Name *" value={f.applicant_name} onChange={set("applicant_name")} autoCapitalize="words" testID="upl-applicant" />
          <TextField label="Co-applicant Name *" value={f.co_applicant_name} onChange={set("co_applicant_name")} autoCapitalize="words" testID="upl-coapplicant" />
          <TextField label="Second Co-applicant Name (optional)" value={f.co_applicant2_name} onChange={set("co_applicant2_name")} autoCapitalize="words" testID="upl-coapplicant2" />
          <Btn label={pdf ? `PDF: ${pdf.name} (${Math.max(1, Math.round(pdf.size / 1024))} KB)` : "Attach PDF Document *"} variant="secondary" onPress={pick} loading={picking} testID="upl-pdf-btn" full />
          <View style={{ height: spacing.md }} />
          <TextField label="Requirements / Instructions / Remarks" value={f.requirements} onChange={set("requirements")} multiline autoCapitalize="sentences" testID="upl-requirements" />
          {errs.length ? <View style={styles.err} testID="upload-errors">{errs.map((x) => <Text key={x} style={styles.errText}>• {x}</Text>)}</View> : null}
          <Btn label="Submit Upload" onPress={submit} loading={busy} testID="upl-submit-btn" full />
        </Card>
        <SectionTitle>My Uploaded Cases</SectionTitle>
        {(listQ.data?.items ?? []).map((u: any) => (
          <Card key={u.id} testID={`my-upload-${u.id}`}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", gap: spacing.sm }}>
              <Text style={styles.name} numberOfLines={2}>{u.applicant_name} · {u.branch_name}</Text>
              <StatusPill status={PILL[u.status] ?? "submitted"} testID={`upl-status-${u.id}`} />
            </View>
            <Text style={styles.meta}>{u.status_label} · {u.state} · {fmtIST(u.submitted_at)}</Text>
            {(u.comments ?? []).map((c: any, i: number) => <Text key={i} style={styles.comment}>{c.by}: {c.text}</Text>)}
            {u.pdf?.available ? <Btn label="View PDF" variant="ghost" small onPress={() => openPdf(u.id)} testID={`upl-pdf-${u.id}`} /> : null}
          </Card>
        ))}
      </KeyboardAwareScrollView>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.surface },
  err: { backgroundColor: colors.error, borderRadius: 12, padding: spacing.md, marginBottom: spacing.md },
  errText: { color: colors.onError, fontSize: 14, lineHeight: 20 },
  name: { flex: 1, fontWeight: "700", color: colors.onSurface, fontSize: 15 },
  meta: { color: colors.muted, fontSize: 13, marginTop: 4 },
  comment: { color: colors.warning, fontSize: 13, marginTop: 4 },
}));

export default function UploadCases() {
  return <RoleGate role="agent"><UploadCasesScreen /></RoleGate>;
}
