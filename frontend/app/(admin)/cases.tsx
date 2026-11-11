import { useMemo, useState } from "react";
import { FlatList, Modal, Pressable, Text, View } from "react-native";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";

import { api, downloadFile } from "@/src/api";
import { SelectField, TextField } from "@/src/components/fields";
import { Btn, Card, FLAG_LABELS, Loading, PopupModal, PriorityPill, Screen, SectionTitle, StatusPill, Empty, showToast } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { makeStyles, radius, spacing, typography } from "@/src/theme";

const STATUSES = ["all", "new", "assigned", "in_progress", "submitted", "under_review", "returned", "approved", "inconclusive", "exception", "exported"];

export default function AdminCases() {
  const { user } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const styles = useStyles();

  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [clientId, setClientId] = useState("");
  const [reportType, setReportType] = useState("");
  const [assignFor, setAssignFor] = useState<any>(null);
  const [agentId, setAgentId] = useState("");

  const clientsQ = useQuery({ queryKey: ["clients"], queryFn: () => api<{ items: any[] }>("/clients") });
  const agentsQ = useQuery({ queryKey: ["agents"], queryFn: () => api<{ items: any[] }>("/users?role=agent") });
  const typesQ = useQuery({ queryKey: ["report-types"], queryFn: () => api<any>("/report-types") });

  const casesQ = useQuery({
    queryKey: ["admin-cases", status, query, page, clientId, reportType],
    queryFn: () => {
      const p = new URLSearchParams({ page: String(page), limit: "25" });
      if (status !== "all") p.set("status", status);
      if (query) p.set("q", query);
      if (clientId) p.set("client_id", clientId);
      if (reportType) p.set("report_type", reportType);
      return api<any>(`/cases?${p.toString()}`);
    },
  });

  const assign = async () => {
    try {
      await api(`/cases/${assignFor.id}/assign`, { method: "POST", body: { agent_id: agentId } });
      queryClient.invalidateQueries({ queryKey: ["admin-cases"] });
      queryClient.invalidateQueries({ queryKey: ["admin-stats"] });
      showToast("Case assigned", "success");
      setAssignFor(null);
    } catch (e: any) {
      showToast(e?.message ?? "Assign failed", "error");
    }
  };

  const types = typesQ.data?.items ?? [];
  const items = casesQ.data?.items ?? [];

  return (
    <Screen testID="admin-cases-screen">
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <Text style={styles.title}>Cases</Text>
        <Btn label="Export Excel" variant="secondary" small onPress={async () => {
          try { await downloadFile("/exports/cases.xlsx", "checksphere-cases.xlsx"); } catch (e: any) { showToast(e.message, "error"); }
        }} testID="cases-export-btn" />
      </View>

      <Card>
        <View style={styles.chipWrap}>
          {STATUSES.map((st) => (
            <Pressable
              key={st}
              onPress={() => { setStatus(st); setPage(1); }}
              style={[styles.chip, status === st && styles.chipActive]}
              testID={`status-chip-${st}`}
            >
              <Text style={[styles.chipText, status === st && styles.chipTextActive]}>{st.replace("_", " ")}</Text>
            </Pressable>
          ))}
        </View>
        <View style={{ flexDirection: "row", gap: spacing.md, flexWrap: "wrap" }}>
          <View style={{ flex: 2, minWidth: 200 }}>
            <TextField label="Search" value={q} onChange={setQ} placeholder="Applicant / Internal ID / Client Case ID" testID="admin-cases-search-input" />
          </View>
          <View style={{ flex: 1, minWidth: 150 }}>
            <SelectField
              label="Client"
              value={clientsQ.data?.items.find((c: any) => c.id === clientId)?.name}
              options={["All clients", ...(clientsQ.data?.items ?? []).map((c: any) => c.name)]}
              onChange={(v) => { setClientId(v === "All clients" ? "" : clientsQ.data?.items.find((c: any) => c.name === v)?.id ?? ""); setPage(1); }}
              testID="admin-cases-client-select"
            />
          </View>
          <View style={{ flex: 1, minWidth: 150 }}>
            <SelectField
              label="Report Type"
              value={types.find((t: any) => t.key === reportType)?.name}
              options={["All types", ...types.map((t: any) => t.name)]}
              onChange={(v) => { setReportType(v === "All types" ? "" : types.find((t: any) => t.name === v)?.key ?? ""); setPage(1); }}
              testID="admin-cases-type-select"
            />
          </View>
          <View style={{ justifyContent: "flex-end", paddingBottom: spacing.md }}>
            <Btn label="Search" onPress={() => { setQuery(q); setPage(1); }} testID="admin-cases-search-btn" small />
          </View>
        </View>
      </Card>

      {casesQ.isLoading ? (
        <Loading label="Fetching case queue…" />
      ) : items.length === 0 ? (
        <Empty title="No cases match" message="Adjust the filters to see more cases." />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(c) => c.id}
          contentContainerStyle={{ paddingBottom: spacing.xl }}
          renderItem={({ item: c }) => (
            <View style={styles.row} testID={`admin-case-${c.internal_case_id}`}>
              <Pressable style={{ flex: 1, gap: 3 }} onPress={() => router.push(`/cases/${c.id}`)}>
                <Text style={styles.applicant}>{c.applicant_name} · {c.internal_case_id}</Text>
                <Text style={styles.meta}>{c.client_name} · {c.branch_name ?? "-"} · {c.city ?? "-"}</Text>
                <Text style={styles.meta}>{c.report_type_name || c.report_type}</Text>
                <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: 4, alignItems: "center", flexWrap: "wrap" }}>
                  <StatusPill status={c.status} testID={`admin-case-status-${c.internal_case_id}`} />
                  <PriorityPill priority={c.priority} />
                  {(c.flags ?? []).length > 0 ? (
                    <View style={[styles.chip, styles.flagChip]}>
                      <Text style={styles.flagText}>⚑ {(c.flags ?? []).map((f: string) => FLAG_LABELS[f] ?? f).join(", ")}</Text>
                    </View>
                  ) : null}
                </View>
              </Pressable>
              <View style={{ gap: spacing.sm, justifyContent: "center" }}>
                {c.status === "new" || !c.assigned_agent_id ? (
                  <Btn label="Assign" small onPress={() => { setAssignFor(c); setAgentId(""); }} testID={`assign-btn-${c.internal_case_id}`} />
                ) : null}
                {c.assigned_agent_name ? <Text style={styles.meta}>{c.assigned_agent_name}</Text> : null}
                {c.due_at ? <Text style={styles.meta}>Due {new Date(c.due_at).toLocaleDateString()}</Text> : null}
              </View>
            </View>
          )}
        />
      )}

      <View style={{ flexDirection: "row", justifyContent: "center", gap: spacing.md, paddingVertical: spacing.md }}>
        <Btn label="Prev" variant="secondary" small disabled={page <= 1} onPress={() => setPage((p) => Math.max(1, p - 1))} testID="cases-prev-btn" />
        <Text style={{ alignSelf: "center", color: "#73706A" }}>Page {casesQ.data?.page ?? page} · {casesQ.data?.total ?? 0} cases</Text>
        <Btn label="Next" variant="secondary" small disabled={page * 25 >= (casesQ.data?.total ?? 0)} onPress={() => setPage((p) => p + 1)} testID="cases-next-btn" />
      </View>

      <PopupModal visible={!!assignFor} title={`Assign ${assignFor?.internal_case_id ?? ""}`} onClose={() => setAssignFor(null)}>
        <SelectField
          label="Field Agent"
          value={agentsQ.data?.items.find((a: any) => a.id === agentId)?.name}
          options={agentsQ.data?.items.map((a: any) => a.name) ?? []}
          onChange={(v) => setAgentId(agentsQ.data?.items.find((a: any) => a.name === v)?.id ?? "")}
          testID="assign-agent-select"
        />
        <Btn label="Confirm Assignment" onPress={assign} disabled={!agentId} testID="assign-confirm-btn" full />
      </PopupModal>
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  title: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.md, fontFamily: typography.fontFamily },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.md },
  chip: { height: 36, paddingHorizontal: spacing.md, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceTertiary, justifyContent: "center" },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipText: { color: colors.onSurfaceSecondary, fontSize: typography.scale.sm, fontWeight: "600", textTransform: "capitalize" },
  chipTextActive: { color: colors.onBrandPrimary },
  flagChip: { backgroundColor: colors.warning, borderColor: colors.warning },
  flagText: { color: colors.onWarning, fontSize: typography.scale.sm, fontWeight: "700" },
  row: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, marginBottom: spacing.sm, flexDirection: "row", gap: spacing.md,
  },
  applicant: { color: colors.onSurface, fontWeight: "700", fontSize: typography.scale.base },
  meta: { color: colors.muted, fontSize: typography.scale.sm },
}));
