import type { ReactNode } from "react";
import { ScrollView, Text, View } from "react-native";

import { makeStyles, radius, spacing } from "@/src/theme";

export function Page({ children, testID }: { children: ReactNode; testID?: string }) {
  return (
    <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: spacing.xxl, paddingBottom: 64 }} testID={testID}>
      {children}
    </ScrollView>
  );
}

export function Panel({ title, children, right, testID, style }: { title?: string; children: ReactNode; right?: ReactNode; testID?: string; style?: any }) {
  const styles = useStyles();
  return (
    <View style={[styles.panel, style]} testID={testID}>
      {title ? (
        <View style={styles.head}>
          <Text style={styles.title}>{title}</Text>
          {right}
        </View>
      ) : null}
      {children}
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  panel: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.xl, marginBottom: spacing.lg },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.lg, gap: spacing.md },
  title: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
}));
