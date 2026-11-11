import { useMemo, useState } from "react";
import { Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/src/api";
import { SelectField, TextField } from "@/src/components/fields";
import { Btn, Card, DisplayRow, ErrorBox, KpiCard, Loading, Screen, SectionTitle } from "@/src/components/ui";
import { makeStyles, spacing, typography } from "@/src/theme";

export default function AdminDashboard() {
  const styles = useStyles();
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [clientId, setClientId] = useState("");

  const clientsQ = useQuery({ queryKey: ["clients"], queryFn: () => api<{ items: any[] }>("/clients") });
  const statsQ = useQuery({
    queryKey: ["admin-stats", fromDate, toDate, clientId],
    queryFn: () => {
      const p = new URLSearchParams();
      if (fromDate) p.set("from_date", fromDate);
      if (toDate) p.set("to_date", toDate);
      if (clientId) p.set("client_id", clientId);
      const s = p.toString();
      return api<any>(`/dashboard/stats${s ? `?${s}` : ""}`);
    },
  });

  const s = statsQ.data;
  const counts = s?.counts ?? {};
  const barMax = useMemo(() => {
    const arr = [...(s?.agents ?? []), ...(s?.clients ?? [])];
    return Math.max(1, ...arr.map((x: any) => x.total ?? 0));
  }, [s]);

  const pendingReview = (counts.submitted ?? 0) + (counts.under_review ?? 0);

  return (
    <Screen testID="admin-dashboard-screen">
      <Text style={styles.title}>Dashboard</Text>
      <Card>
        <SectionTitle>Filters</SectionTitle>
        <View style={styles.filtersRow}>
          <View style={{ flex: 1, minWidth: 130 }}>
            <TextField label="From (YYYY-MM-DD)" value={fromDate} onChange={setFromDate} testID="filter-from-input" />
          </View>
          <View style={{ flex: 1, minWidth: 130 }}>
            <TextField label="To (YYYY-MM-DD)" value={toDate} onChange={setToDate} testID="filter-to-input" />
          </View>
          <View style={{ flex: 1, minWidth: 160 }}>
            <SelectField
              label="Client"
              value={clientsQ.data?.items.find((c: any) => c.id === clientId)?.name}
              options={["All clients", ...(clientsQ.data?.items ?? []).map((c: any) => c.name)]}
              onChange={(v) => setClientId(v === "All clients" ? "" : clientsQ.data?.items.find((c: any) => c.name === v)?.id ?? "")}
              testID="filter-client-select"
            />
          </View>
        </View>
      </Card>

      {statsQ.isLoading ? (
        <Loading label="Aggregating MIS data…" />
      ) : statsQ.isError ? (
        <ErrorBox message="Dashboard analytics unavailable." onRetry={() => statsQ.refetch()} />
      ) : (
        <>
          <View style={{ flexDirection: "row", flexWrap: "wrap", marginHorizontal: -4 }}>
            <KpiCard label="Total Cases" value={s?.total ?? 0} testID="kpi-total" />
            <KpiCard label="Unassigned" value={s?.unassigned ?? 0} tone="warning" testID="kpi-unassigned" />
            <KpiCard label="Overdue" value={s?.overdue ?? 0} tone="error" testID="kpi-overdue" />
            <KpiCard label="Avg TAT (hrs)" value={s?.avg_tat_hours ? Math.round(s.avg_tat_hours * 10) / 10 : "—"} tone="info" testID="kpi-tat" />
            <KpiCard label="Approved" value={counts.approved ?? 0} tone="success" testID="kpi-approved" />
            <KpiCard label="Pending Review" value={pendingReview} tone="info" testID="kpi-pending-review" />
            <KpiCard label="Returned" value={counts.returned ?? 0} tone="warning" testID="kpi-returned" />
            <KpiCard label="Exceptions" value={counts.exception ?? 0} tone="error" testID="kpi-exceptions" />
            <KpiCard label="Inconclusive" value={counts.inconclusive ?? 0} tone="warning" testID="kpi-inconclusive" />
            <KpiCard label="In Progress" value={(counts.assigned ?? 0) + (counts.in_progress ?? 0)} testID="kpi-inprogress" />
          </View>

          <Card>
            <SectionTitle>Agent Productivity</SectionTitle>
            {(s?.agents ?? []).length === 0 ? <DisplayRow label="" value="No data" /> : null}
            {(s?.agents ?? []).map((a: any) => (
              <View key={a.name} style={styles.barRow} testID={`agent-row-${a.name}`}>
                <Text style={styles.barName}>{a.name === "-" ? "Unassigned" : a.name}</Text>
                <View style={styles.barTrack}>
                  <View style={[styles.barFill, { width: `${(a.total / barMax) * 100}%` }]} />
                </View>
                <Text style={styles.barValue}>{a.total} · {a.approved} approved · {a.overdue} overdue</Text>
              </View>
            ))}
          </Card>

          <Card>
            <SectionTitle>Client Performance</SectionTitle>
            {(s?.clients ?? []).map((c: any) => (
              <DisplayRow key={c.name} label={c.name} value={`${c.total} total · ${c.approved} approved · ${c.overdue} overdue`} />
            ))}
          </Card>

          <Card>
            <SectionTitle>State / City Performance</SectionTitle>
            {(s?.states ?? []).map((c: any) => (
              <DisplayRow key={c.name} label={c.name || "—"} value={`${c.total} total · ${c.approved} approved`} />
            ))}
            {(s?.cities ?? []).map((c: any) => (
              <DisplayRow key={c.name} label={c.name || "—"} value={`${c.total} total · ${c.approved} approved`} />
            ))}
          </Card>

          <Card>
            <SectionTitle>Supervisor Activity</SectionTitle>
            {(s?.supervisors ?? []).length === 0 ? <DisplayRow label="" value="No reviews yet" /> : null}
            {(s?.supervisors ?? []).map((sup: any) => (
              <DisplayRow
                key={sup.name}
                label={sup.name}
                value={`${sup.approved} approved · ${sup.returned} returned · ${sup.inconclusive} inconclusive · ${sup.exception} exceptions`}
              />
            ))}
          </Card>
        </>
      )}
      <View style={{ height: spacing.xl }} />
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  title: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.md, fontFamily: typography.fontFamily },
  filtersRow: { flexDirection: "row", gap: spacing.md, flexWrap: "wrap" },
  barRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xs },
  barName: { width: 130, color: colors.onSurface, fontSize: typography.scale.sm, fontWeight: "600" },
  barTrack: { flex: 1, height: 10, backgroundColor: colors.surfaceTertiary, borderRadius: 5, overflow: "hidden" },
  barFill: { height: 10, backgroundColor: colors.brandSecondary, borderRadius: 5 },
  barValue: { color: colors.muted, fontSize: typography.scale.sm, width: 220 },
}));
