import { useEffect, useState } from "react";
import { Linking, Pressable, Text, View } from "react-native";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAgentNotifications } from "@/src/components/AgentTopBar";
import { TextField } from "@/src/components/fields";
import { BackHeader, Banner, Btn, Card, Empty, Loading, PopupModal, Screen, showToast } from "@/src/components/ui";
import { getAlertPermission, requestAlertPermission, type AlertPermission } from "@/src/utils/phoneAlerts";
import { RoleGate } from "@/src/portal/RoleGate";
import { makeStyles, spacing } from "@/src/theme";

function NotificationsScreen() {
  const qc = useQueryClient();
  const router = useRouter();
  const styles = useStyles();
  const q = useAgentNotifications();
  const [perm, setPerm] = useState<AlertPermission>("unsupported");
  useEffect(() => { getAlertPermission().then(setPerm).catch(() => null); }, []);
  const [reassign, setReassign] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const act = async (fn: () => Promise<any>, msg: string) => {
    try { await fn(); showToast(msg, "success"); qc.invalidateQueries({ queryKey: ["notifications"] }); qc.invalidateQueries({ queryKey: ["agent-cases"] }); }
    catch (e: any) { showToast(e?.message ?? "Failed", "error"); }
  };
  return (
    <Screen testID="notifications-screen">
      <BackHeader title="Notifications" testID="notifications-back-btn" />
      {perm === "undetermined" || perm === "denied" ? (
        <Card testID="phone-alerts-card">
          <Text style={styles.title}>Get alerts on your phone</Text>
          <Text style={styles.body}>Allow notifications so new case allocations and pending-case reminders appear in your phone&apos;s notification centre.</Text>
          <View style={styles.row}><Btn label="Turn On Phone Alerts" small onPress={async () => setPerm(await requestAlertPermission())} testID="phone-alerts-enable-btn" /></View>
        </Card>
      ) : perm === "blocked" ? (
        <Card testID="phone-alerts-blocked-card">
          <Banner tone="warning" message="Phone alerts are turned off for CheckSphere. You will still see every alert here." />
          <Btn label="Open Settings" small variant="secondary" onPress={() => Linking.openSettings()} testID="phone-alerts-settings-btn" />
        </Card>
      ) : null}
      {q.isLoading ? <Loading /> : (q.data?.items ?? []).length === 0 ? <Empty title="No notifications" /> : null}
      {(q.data?.items ?? []).map((n: any) => (
        <Card key={n.id} testID={`notification-${n.id}`} style={!n.acknowledged_at ? styles.unread : undefined}>
          <Text style={styles.title}>{n.title}</Text>
          <Text style={styles.body}>{n.body}</Text>
          <Text style={styles.meta}>{new Date(n.created_at).toLocaleString()}{n.acknowledged_at ? ` · acknowledged ${new Date(n.acknowledged_at).toLocaleTimeString()}` : ""}{n.agent_response ? ` · ${n.agent_response === "accept" ? "accepted" : "reassignment requested"}` : ""}</Text>
          <View style={styles.row}>
            {!n.acknowledged_at ? <Btn label="Acknowledge" small variant="secondary" onPress={() => act(() => api(`/notifications/${n.id}/ack`, { method: "POST" }), "Acknowledged")} testID={`ack-${n.id}`} /> : null}
            {n.kind === "assignment" && n.case_id && n.can_respond ? (
              <>
                <Btn label="Accept" small onPress={() => act(async () => { await api(`/cases/${n.case_id}/agent-response`, { method: "POST", body: { response: "accept" } }); await api(`/notifications/${n.id}/ack`, { method: "POST" }); }, "Case accepted")} testID={`accept-${n.id}`} />
                <Btn label="Request Reassignment" small variant="ghost" onPress={() => { setReassign(n.case_id); setReason(""); }} testID={`reassign-${n.id}`} />
              </>
            ) : null}
            {n.case_id ? <Pressable onPress={() => router.push(`/case/${n.case_id}`)} testID={`open-case-${n.id}`}><Text style={styles.link}>Open case</Text></Pressable> : null}
          </View>
        </Card>
      ))}
      <PopupModal visible={!!reassign} title="Request reassignment" onClose={() => setReassign(null)}>
        <TextField label="Reason (required)" value={reason} onChange={setReason} multiline autoCapitalize="sentences" testID="reassign-reason-input" />
        <Btn label="Send to Supervisor" disabled={!reason.trim()} full testID="reassign-submit-btn" onPress={async () => { await act(() => api(`/cases/${reassign}/agent-response`, { method: "POST", body: { response: "reassign", reason } }), "Reassignment requested"); setReassign(null); }} />
      </PopupModal>
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  unread: { borderLeftWidth: 4, borderLeftColor: colors.brandPrimary },
  title: { fontWeight: "800", color: colors.onSurface, fontSize: 15 },
  body: { color: colors.onSurfaceSecondary, fontSize: 14, marginTop: 4 },
  meta: { color: colors.muted, fontSize: 12, marginTop: 4 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.sm, alignItems: "center" },
  link: { color: colors.info, fontWeight: "700", padding: 8 },
}));

export default function Notifications() {
  return <RoleGate role="agent"><NotificationsScreen /></RoleGate>;
}
