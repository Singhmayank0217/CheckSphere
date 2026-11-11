import { Platform, Text, View } from "react-native";

import { downloadFile } from "@/src/api";
import { Banner, Btn, Card, Screen, SectionTitle, showToast } from "@/src/components/ui";
import { useSession } from "@/src/session";
import { makeStyles, spacing, typography } from "@/src/theme";

export default function MisExports() {
  const { user } = useSession();
  const styles = useStyles();
  const webOnly = Platform.OS !== "web";

  const grab = (path: string, name: string) => async () => {
    try {
      await downloadFile(path, name);
      showToast("Download started", "success");
    } catch (e: any) {
      showToast(e?.message ?? "Download failed", "error");
    }
  };

  return (
    <Screen testID="admin-mis-screen">
      <Text style={styles.title}>MIS & Exports</Text>
      {webOnly ? (
        <Banner tone="warning" message="File downloads work on the web dashboard. The agent app keeps downloads disabled by design (no personal sharing of applicant data)." />
      ) : null}

      <Card>
        <SectionTitle>Excel MIS Reports</SectionTitle>
        <Text style={styles.help}>
          Each workbook includes: cases received / assigned / pending / submitted / approved / returned /
          inconclusive / exceptions / overdue, average TAT, and agent, supervisor, client, branch, state and
          city-wise performance.
        </Text>
        <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
          <Btn label="Daily MIS" onPress={grab("/exports/mis.xlsx?period=daily", "checksphere-mis-daily.xlsx")} testID="mis-daily-btn" />
          <Btn label="Weekly MIS" variant="secondary" onPress={grab("/exports/mis.xlsx?period=weekly", "checksphere-mis-weekly.xlsx")} testID="mis-weekly-btn" />
          <Btn label="Monthly MIS" variant="secondary" onPress={grab("/exports/mis.xlsx?period=monthly", "checksphere-mis-monthly.xlsx")} testID="mis-monthly-btn" />
        </View>
      </Card>

      <Card>
        <SectionTitle>Case Lists</SectionTitle>
        <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
          <Btn label="All Cases (.xlsx)" variant="secondary" onPress={grab("/exports/cases.xlsx", "checksphere-cases.xlsx")} testID="mis-cases-btn" />
        </View>
        <Text style={styles.help}>
          Individual Word (.docx) and PDF reports — with company branding, evidence references, QR verification
          link, disclaimer and report version — are available from each approved case&apos;s review screen.
        </Text>
      </Card>

      <Card>
        <SectionTitle>Data Protection Notes</SectionTitle>
        <Text style={styles.help}>
          • Exports are audit-logged with user, date and time.{"\n"}
          • Sensitive numbers are masked in reports unless revealed by an authorised user.{"\n"}
          • Configurable retention and secure deletion are enforced by the admin retention setting.
        </Text>
      </Card>
    </Screen>
  );
}

const useStyles = makeStyles((colors) => ({
  title: { fontSize: typography.scale.xxl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.md, fontFamily: typography.fontFamily },
  help: { color: colors.muted, fontSize: typography.scale.sm, lineHeight: 18, marginTop: spacing.sm },
}));
