import { useEffect, useState } from "react";
import { Text, TextInput, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api, downloadFile } from "@/src/api";
import { SelectField } from "@/src/components/fields";
import { Btn, FLAG_LABELS, PriorityPill, STATUS_LABELS, StatusPill, showToast } from "@/src/components/ui";
import { usePortalBase } from "@/src/portal/base";
import { DataTable, type Column } from "@/src/portal/DataTable";
import { Page, Panel } from "@/src/portal/Page";
import { PageHeader } from "@/src/portal/Shell";
import { useSession } from "@/src/session";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

const SLA_OPTS: Record<string, string> = { "": "Any SLA", overdue: "Overdue", due_24h: "Due in 24 hours", within: "Within SLA" };
const EMPTY = { q: "", client_id: "", branch_id: "", state: "", city: "", agent_id: "", supervisor_id: "", report_type: "", status: "", sla: "", from_date: "", to_date: "", applicant: "", internal_case_id: "", client_case_id: "", loan_type: "", flagged: "" };

function Input({ label, value, onChange, testID }: { label: string; value: string; onChange: (v: string) => void; testID: string }) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.filter}>
      <Text style={styles.filterLabel}>{label}</Text>
      <TextInput value={value} onChangeText={onChange} style={styles.input} placeholderTextColor={colors.muted} testID={testID} />
    </View>
  );
}

export default function CasesPage({ preset }: { preset?: "review" }) {
  const styles = useStyles();
  const router = useRouter();
  const base = usePortalBase();
  const { user } = useSession();
  const isAdmin = user?.role === "super_admin";
  const params = useLocalSearchParams<Record<string, string>>();
  const [f, setF] = useState<Record<string, string>>({ ...EMPTY });
  const [applied, setApplied] = useState<Record<string, string>>({ ...EMPTY });
  const [sort, setSort] = useState("created_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);

  useEffect(() => {
    const init = { ...EMPTY, ...Object.fromEntries(Object.entries(params).filter(([k]) => k in EMPTY)) } as Record<string, string>;
    if (preset === "review") init.status = "pending_review";
    setF(init);
    setApplied(init);
    setPage(1);
  }, [params.q, params.status, params.sla, params.flagged, preset]); // eslint-disable-line react-hooks/exhaustive-deps

  const clientsQ = useQuery({ queryKey: ["clients"], queryFn: () => api<{ items: any[] }>("/clients") });
  const branchesQ = useQuery({ queryKey: ["branches", "all"], queryFn: () => api<{ items: any[] }>("/branches") });
  const regionsQ = useQuery({ queryKey: ["regions"], queryFn: () => api<any>("/regions") });
  const agentsQ = useQuery({ queryKey: ["agents"], queryFn: () => api<{ items: any[] }>("/users?role=agent") });
  const supsQ = useQuery({ queryKey: ["supervisors"], queryFn: () => api<{ items: any[] }>("/users?role=supervisor"), enabled: isAdmin });
  const typesQ = useQuery({ queryKey: ["report-types"], queryFn: () => api<any>("/report-types") });

  const qs = () => {
    const p = new URLSearchParams({ page: String(page), limit: "25", sort, order });
    Object.entries(applied).forEach(([k, v]) => v && p.set(k, v));
    return p.toString();
  };
  const casesQ = useQuery({ queryKey: ["admin-cases", applied, sort, order, page], queryFn: () => api<any>(`/cases?${qs()}`) });

  const opt = (items: any[] | undefined, label: (x: any) => string, id: (x: any) => string, key: string, all: string, title: string) => (
    <View style={styles.filter}>
      <SelectField
        label={title}
        value={key && f[key] ? (items ?? []).map((x) => [id(x), label(x)]).find(([i]) => i === f[key])?.[1] : all}
        options={[all, ...(items ?? []).map(label)]}
        onChange={(v) => setF({ ...f, [key]: v === all ? "" : id((items ?? []).find((x) => label(x) === v)) })}
        testID={`filter-${key}`}
      />
    </View>
  );
  const strItems = (arr?: string[]) => (arr ?? []).map((s) => ({ id: s, name: s }));
  const statusItems = Object.entries(STATUS_LABELS).filter(([k]) => !["draft", "superseded"].includes(k)).map(([id, name]) => ({ id, name }));

  const onSort = (k: string) => {
    if (k === sort) setOrder(order === "asc" ? "desc" : "asc");
    else { setSort(k); setOrder("asc"); }
    setPage(1);
  };

  const columns: Column<any>[] = [
    { key: "internal_case_id", label: "Case ID", width: 130, sortable: true, render: (c) => <Text style={styles.idText}>{c.internal_case_id}</Text> },
    { key: "client_case_id", label: "Client Case ID", width: 130 },
    { key: "applicant_name", label: "Applicant", width: 170, sortable: true, render: (c) => <Text style={styles.cellText} numberOfLines={3}>{c.applicant_name}{c.co_applicant_name || c.seller_name ? <Text style={styles.sub}>{"\n"}{[c.co_applicant_name, c.seller_name].filter(Boolean).join(" / ")}</Text> : null}</Text> },
    { key: "primary_phone", label: "Contact", width: 130, render: (c) => <Text style={styles.cellText}>{c.primary_phone ?? "—"}{c.alt_phone ? <Text style={styles.sub}>{"\n"}{c.alt_phone}</Text> : null}</Text> },
    { key: "client_name", label: "Client / Branch", width: 200, sortable: true, render: (c) => <Text style={styles.cellText} numberOfLines={3}>{c.client_name}{"\n"}<Text style={styles.sub}>{c.branch_name ?? "—"}{c.bank_state ? ` · ${c.bank_state}` : ""}</Text></Text> },
    { key: "report_type", label: "Report Type", width: 210, sortable: true, render: (c) => <Text style={styles.cellText} numberOfLines={2}>{c.report_type_name}</Text> },
    { key: "city", label: "City / State / PIN", width: 150, sortable: true, render: (c) => <Text style={styles.cellText}>{c.city ?? "—"}{"\n"}<Text style={styles.sub}>{c.verification_state || c.state || ""}{c.pincode ? ` · ${c.pincode}` : ""}</Text></Text> },
    { key: "assigned_agent_name", label: "Agent", width: 140, sortable: true, render: (c) => <Text style={styles.cellText}>{c.assigned_agent_name ?? "Unassigned"}</Text> },
    { key: "status", label: "Status", width: 150, sortable: true, render: (c) => <StatusPill status={c.status} testID={`table-status-${c.internal_case_id}`} /> },
    { key: "priority", label: "Priority", width: 100, sortable: true, render: (c) => <PriorityPill priority={c.priority} /> },
    { key: "due_at", label: "Due", width: 140, sortable: true, render: (c) => {
      const od = c.due_at && new Date(c.due_at) < new Date() && ["new", "assigned", "in_progress", "returned"].includes(c.status);
      return <Text style={[styles.cellText, od && styles.overdue]}>{c.due_at ? new Date(c.due_at).toLocaleDateString() : "—"}{od ? " · overdue" : ""}</Text>;
    } },
    { key: "flags", label: "Flags", width: 180, render: (c) => <Text style={styles.flag} numberOfLines={2}>{(c.flags ?? []).map((x: string) => FLAG_LABELS[x] ?? x).join(", ")}</Text> },
  ];

  const exportXlsx = async () => {
    try { await downloadFile(`/exports/cases.xlsx${applied.status && applied.status !== "pending_review" ? `?status=${applied.status}` : ""}`, "checksphere-cases.xlsx"); }
    catch (e: any) { showToast(e.message, "error"); }
  };

  return (
    <Page testID={preset === "review" ? "portal-review-queue" : "portal-cases"}>
      <PageHeader
        title={preset === "review" ? "Review Queue" : "Cases"}
        subtitle={preset === "review" ? "Submitted and under-review reports awaiting a supervisor decision (oldest first)" : "Search, filter and manage all verification cases"}
        actions={<>
          {isAdmin ? <Btn label="Create / Import" variant="secondary" onPress={() => router.push("/admin/create" as any)} testID="cases-create-btn" /> : null}
          <Btn label="Export Excel" variant="secondary" onPress={exportXlsx} testID="cases-export-btn" />
        </>}
      />
      <Panel title="Filters" right={<View style={{ flexDirection: "row", gap: spacing.sm }}>
        <Btn label="Clear" variant="ghost" small onPress={() => { const e = { ...EMPTY, status: preset === "review" ? "pending_review" : "" }; setF(e); setApplied(e); setPage(1); }} testID="filters-clear-btn" />
        <Btn label="Apply Filters" small onPress={() => { setApplied(f); setPage(1); }} testID="filters-apply-btn" />
      </View>}>
        <View style={styles.filters}>
          <Input label="Search (any)" value={f.q} onChange={(v) => setF({ ...f, q: v })} testID="filter-q" />
          <Input label="Applicant name" value={f.applicant} onChange={(v) => setF({ ...f, applicant: v })} testID="filter-applicant" />
          <Input label="Internal case ID" value={f.internal_case_id} onChange={(v) => setF({ ...f, internal_case_id: v })} testID="filter-internal-id" />
          <Input label="Client case ID" value={f.client_case_id} onChange={(v) => setF({ ...f, client_case_id: v })} testID="filter-client-case-id" />
          {opt(clientsQ.data?.items, (x) => x.name, (x) => x.id, "client_id", "All clients", "Client")}
          {opt(branchesQ.data?.items, (x) => x.name, (x) => x.id, "branch_id", "All branches", "Branch")}
          {opt(strItems(regionsQ.data?.states), (x) => x.name, (x) => x.id, "state", "All states", "State")}
          {opt(strItems(regionsQ.data?.cities), (x) => x.name, (x) => x.id, "city", "All cities", "City")}
          {opt(agentsQ.data?.items, (x) => x.name, (x) => x.id, "agent_id", "All agents", "Agent")}
          {isAdmin ? opt(supsQ.data?.items, (x) => x.name, (x) => x.id, "supervisor_id", "All supervisors", "Supervisor") : null}
          {opt(typesQ.data?.items, (x) => x.name, (x) => x.key, "report_type", "All report types", "Report type")}
          {preset === "review" ? null : opt(statusItems, (x) => x.name, (x) => x.id, "status", "All statuses", "Status")}
          {opt(Object.entries(SLA_OPTS).filter(([k]) => k).map(([id, name]) => ({ id, name })), (x) => x.name, (x) => x.id, "sla", "Any SLA", "SLA status")}
          <Input label="Loan / product type" value={f.loan_type} onChange={(v) => setF({ ...f, loan_type: v })} testID="filter-loan" />
          <Input label="Created from (YYYY-MM-DD)" value={f.from_date} onChange={(v) => setF({ ...f, from_date: v })} testID="filter-from" />
          <Input label="Created to (YYYY-MM-DD)" value={f.to_date} onChange={(v) => setF({ ...f, to_date: v })} testID="filter-to" />
        </View>
      </Panel>
      <DataTable
        testID="cases-table"
        columns={columns}
        rows={casesQ.data?.items ?? []}
        loading={casesQ.isLoading}
        sort={sort}
        order={order}
        onSort={onSort}
        onRowPress={(c) => router.push(`${base}/cases/${c.id}` as any)}
        page={page}
        total={casesQ.data?.total}
        limit={25}
        onPage={setPage}
        empty="No cases match these filters."
      />
    </Page>
  );
}

const useStyles = makeStyles((colors) => ({
  filters: { flexDirection: "row", flexWrap: "wrap", columnGap: spacing.md },
  filter: { flexGrow: 1, flexBasis: 200, maxWidth: 320, marginBottom: spacing.xs },
  filterLabel: { fontSize: 12, fontWeight: "600", color: colors.onSurfaceSecondary, marginBottom: 6 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, height: 44, paddingHorizontal: spacing.md, fontSize: 14, color: colors.onSurface, backgroundColor: colors.surfaceSecondary, marginBottom: spacing.md },
  idText: { color: colors.brandPrimary, fontWeight: "800", fontSize: 14 },
  cellText: { color: colors.onSurface, fontSize: 14 },
  sub: { color: colors.muted, fontSize: 12 },
  overdue: { color: colors.error, fontWeight: "700" },
  flag: { color: colors.warning, fontSize: 12, fontWeight: "700" },
}));
