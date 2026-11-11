import { Pressable, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { ErrorBox, FLAG_LABELS, Loading, StatusPill } from "@/src/components/ui";
import { usePortalBase } from "@/src/portal/base";
import { ColumnChart, HBarChart, StackedBar } from "@/src/portal/charts";
import { Page, Panel } from "@/src/portal/Page";
import { PageHeader } from "@/src/portal/Shell";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

const CARDS = [
  { key: "total", label: "Total Cases", q: "", tone: "brand" },
  { key: "new", label: "New", q: "status=new", tone: "info" },
  { key: "assigned", label: "Assigned", q: "status=assigned", tone: "brand" },
  { key: "in_progress", label: "In Progress", q: "status=in_progress", tone: "warning" },
  { key: "submitted", label: "Submitted", q: "status=submitted", tone: "info" },
  { key: "under_review", label: "Under Review", q: "status=under_review", tone: "info" },
  { key: "returned", label: "Returned", q: "status=returned", tone: "warning" },
  { key: "approved", label: "Approved", q: "status=approved", tone: "success" },
  { key: "inconclusive", label: "Inconclusive", q: "status=inconclusive", tone: "muted" },
  { key: "exception", label: "Exceptions", q: "status=exception", tone: "error" },
  { key: "overdue", label: "Overdue", q: "sla=overdue", tone: "error" },
  { key: "pending_24h", label: "Pending > 24h", q: "status=new,assigned,in_progress,returned", tone: "warning" },
  { key: "pending_48h", label: "Pending > 48h", q: "status=new,assigned,in_progress,returned", tone: "error" },
] as const;

export default function Dashboard() {
  const styles = useStyles();
  const { colors } = useTheme();
  const router = useRouter();
  const base = usePortalBase();
  const statsQ = useQuery({ queryKey: ["admin-stats", "dash"], queryFn: () => api<any>("/dashboard/stats") });

  if (statsQ.isLoading) return <Page><Loading label="Loading dashboard…" /></Page>;
  if (statsQ.isError) return <Page><ErrorBox message="Dashboard unavailable." onRetry={() => statsQ.refetch()} /></Page>;
  const s = statsQ.data;
  const val = (k: string) => (k === "total" ? s.total : k === "overdue" || k === "pending_24h" || k === "pending_48h" ? s[k] ?? 0 : s.counts?.[k] ?? 0);
  const tone = (t: string) => ({ brand: colors.brandPrimary, info: colors.info, warning: colors.warning, success: colors.success, error: colors.error, muted: colors.borderStrong } as any)[t];
  const go = (q: string) => router.push(`${base}/cases${q ? `?${q}` : ""}` as any);
  const alertN = base === "/admin" ? s.pending_48h : s.pending_24h;

  return (
    <Page testID="portal-dashboard">
      <PageHeader title="Dashboard" subtitle={`Average turnaround ${s.avg_tat_hours ? `${Math.round(s.avg_tat_hours * 10) / 10} hrs` : "—"} · ${s.flagged_cases} cases with evidence flags`} />
      {alertN > 0 || s.requests_pending > 0 ? (
        <View style={styles.alert} testID="dash-pending-alert">
          {alertN > 0 ? <Text style={styles.alertText}>⚠ {alertN} active case{alertN > 1 ? "s have" : " has"} been pending more than {base === "/admin" ? "48" : "24"} hours without an update.</Text> : null}
          {s.requests_pending > 0 ? <Text style={styles.alertText} onPress={() => router.push(`${base}/requests` as any)}>✉ {s.requests_pending} agent case request{s.requests_pending > 1 ? "s" : ""} awaiting approval — open Case Requests.</Text> : null}
        </View>
      ) : null}
      <View style={styles.cards}>
        {CARDS.map((c) => (
          <Pressable key={c.key} onPress={() => go(c.q)} style={({ hovered }: any) => [styles.card, { borderTopColor: tone(c.tone) }, hovered && styles.cardHover]} testID={`dash-card-${c.key}`}>
            <Text style={styles.cardVal}>{val(c.key)}</Text>
            <Text style={styles.cardLabel}>{c.label}</Text>
          </Pressable>
        ))}
      </View>

      <View style={styles.grid}>
        <Panel title="Case volume (last 14 days)" style={styles.col2}>
          <ColumnChart testID="chart-volume" data={(s.volume ?? []).map((v: any) => ({ label: v.date.slice(5), value: v.count }))} />
        </Panel>
        <Panel title="Report status" style={styles.col1}>
          <StackedBar testID="chart-status" parts={[
            { label: "Open", value: (s.counts.new ?? 0) + (s.counts.assigned ?? 0) + (s.counts.in_progress ?? 0), color: colors.info },
            { label: "Review", value: (s.counts.submitted ?? 0) + (s.counts.under_review ?? 0), color: colors.brandSecondary },
            { label: "Returned", value: s.counts.returned ?? 0, color: colors.warning },
            { label: "Approved", value: (s.counts.approved ?? 0) + (s.counts.exported ?? 0), color: colors.success },
            { label: "Inconclusive", value: s.counts.inconclusive ?? 0, color: colors.borderStrong },
            { label: "Exception", value: s.counts.exception ?? 0, color: colors.error },
          ]} />
        </Panel>
      </View>

      <View style={styles.grid}>
        <Panel title="Agent performance" style={styles.col1}>
          <HBarChart testID="chart-agents" data={(s.agents ?? []).map((a: any) => ({ label: a.name === "-" ? "Unassigned" : a.name, value: a.total, note: `${a.approved} approved · ${a.overdue} overdue` }))} />
        </Panel>
        <Panel title="Turnaround time by agent (hrs)" style={styles.col1}>
          <HBarChart testID="chart-tat" tone="info" unit="h" data={(s.tat_by_agent ?? []).map((a: any) => ({ label: a.name === "-" ? "Unassigned" : a.name, value: a.hours }))} />
        </Panel>
      </View>

      <View style={styles.grid}>
        <Panel title="Branch performance" style={styles.col1}>
          <HBarChart testID="chart-branches" data={(s.branches ?? []).map((b: any) => ({ label: b.name === "-" ? "No branch" : b.name, value: b.total, note: `${b.approved} approved` }))} />
        </Panel>
        <Panel title="Evidence exception summary" style={styles.col1} right={<Text style={styles.link} onPress={() => router.push(`${base}/map` as any)}>Open map</Text>}>
          {Object.keys(s.flag_summary ?? {}).length === 0 ? <Text style={styles.muted}>No evidence flags raised.</Text> : null}
          {Object.entries(s.flag_summary ?? {}).map(([k, v]) => (
            <Pressable key={k} style={styles.listRow} onPress={() => go("flagged=1")} testID={`flag-summary-${k}`}>
              <Text style={styles.listMain}>⚑ {FLAG_LABELS[k] ?? k}</Text>
              <Text style={styles.listCount}>{String(v)}</Text>
            </Pressable>
          ))}
        </Panel>
      </View>

      <View style={styles.grid}>
        <Panel title="Pending review" style={styles.col1} right={<Text style={styles.link} onPress={() => router.push(`${base}/review` as any)}>Review queue</Text>}>
          {(s.pending_review ?? []).length === 0 ? <Text style={styles.muted}>Nothing waiting for review.</Text> : null}
          {(s.pending_review ?? []).map((c: any) => (
            <Pressable key={c.id} style={styles.listRow} onPress={() => router.push(`${base}/cases/${c.id}` as any)} testID={`pending-${c.internal_case_id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.listMain}>{c.internal_case_id} · {c.applicant_name}</Text>
                <Text style={styles.muted}>{c.client_name} · {c.report_type_name}</Text>
              </View>
              <StatusPill status={c.status} />
            </Pressable>
          ))}
        </Panel>
        <Panel title="Overdue cases" style={styles.col1} right={<Text style={styles.link} onPress={() => go("sla=overdue")}>View all</Text>}>
          {(s.overdue_cases ?? []).length === 0 ? <Text style={styles.muted}>No overdue cases.</Text> : null}
          {(s.overdue_cases ?? []).slice(0, 10).map((c: any) => (
            <Pressable key={c.id} style={styles.listRow} onPress={() => router.push(`${base}/cases/${c.id}` as any)} testID={`overdue-${c.internal_case_id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.listMain}>{c.internal_case_id} · {c.applicant_name}</Text>
                <Text style={styles.overdue}>Due {new Date(c.due_at).toLocaleString()} · {c.assigned_agent_name ?? "Unassigned"}</Text>
              </View>
              <StatusPill status={c.status} />
            </Pressable>
          ))}
        </Panel>
      </View>
    </Page>
  );
}

const useStyles = makeStyles((colors) => ({
  cards: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginBottom: spacing.lg },
  alert: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.error, borderLeftWidth: 6, borderRadius: radius.md, padding: spacing.lg, gap: spacing.xs, marginBottom: spacing.lg },
  alertText: { color: colors.error, fontWeight: "700", fontSize: 15 },
  card: { flexGrow: 1, flexBasis: 150, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, borderTopWidth: 4, padding: spacing.lg },
  cardHover: { borderColor: colors.brandPrimary, backgroundColor: colors.brandTertiary },
  cardVal: { fontSize: 28, fontWeight: "800", color: colors.onSurface },
  cardLabel: { fontSize: 14, color: colors.muted, marginTop: 2, fontWeight: "600" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.lg },
  col1: { flexGrow: 1, flexBasis: 420, minWidth: 0 },
  col2: { flexGrow: 2, flexBasis: 560, minWidth: 0 },
  link: { color: colors.info, fontWeight: "700", fontSize: 14 },
  muted: { color: colors.muted, fontSize: 13 },
  overdue: { color: colors.error, fontSize: 13 },
  listRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.divider },
  listMain: { color: colors.onSurface, fontSize: 14, fontWeight: "700" },
  listCount: { marginLeft: "auto", color: colors.error, fontWeight: "800" },
}));
