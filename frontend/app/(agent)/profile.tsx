import { useQuery } from "@tanstack/react-query";
import { Text, View } from "react-native";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { Btn, Card, DisplayRow, Loading, Screen, SectionTitle } from "@/src/components/ui";
import { AgentTopBar } from "@/src/components/AgentTopBar";
import { useSession } from "@/src/session";
import { makeStyles, spacing, typography } from "@/src/theme";

export default function AgentProfile() {
  const { user, signOut } = useSession();
  const router = useRouter();
  const sessionsQ = useQuery({ queryKey: ["my-sessions"], queryFn: () => api<{ items: any[] }>("/auth/sessions") });
  const styles = useStyles();

  return (
    <Screen testID="agent-profile-screen">
      <AgentTopBar title="Profile" />
      <Card>
        <DisplayRow label="Name" value={user?.name} />
        <DisplayRow label="Agent ID" value={user?.agent_id} />
        <DisplayRow label="Role" value={user?.role === "agent" ? "Field Agent" : user?.role} />
        <DisplayRow label="Email" value={user?.email} />
      </Card>

      <SectionTitle>Active sessions on my account</SectionTitle>
      {sessionsQ.isLoading ? (
        <Loading />
      ) : (
        (sessionsQ.data?.items ?? []).map((s) => (
          <Card key={s.id} testID={`session-card-${s.id}`}>
            <DisplayRow label="Device" value={`${s.device_model || "Unknown"} (${s.device_id?.slice(0, 8)}…)`} />
            <DisplayRow label="Signed in" value={s.created_at ? new Date(s.created_at).toLocaleString() : "-"} />
            <DisplayRow label="IP" value={s.ip} />
          </Card>
        ))
      )}

      <View style={{ height: spacing.md }} />
      <Btn label="Change Password" variant="secondary" onPress={() => router.push("/change-password")} testID="profile-change-password-btn" full />
      <View style={{ height: spacing.md }} />
      <Btn label="Sign Out" variant="danger" onPress={async () => { await signOut(); router.replace("/login?role=agent"); }} testID="profile-logout-btn" full />
      <Text style={styles.note}>
        CheckSphere records login device, IP and time for audit purposes. Your offline drafts are stored
        encrypted on this device and sync automatically when the internet is available.
      </Text>
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  note: { color: colors.muted, fontSize: typography.scale.sm, textAlign: "center", lineHeight: 18, padding: spacing.md },
}));
