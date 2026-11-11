// Form field components (theme-tokenised, keyboard-friendly).
import { useState } from "react";
import { FlatList, Modal, Platform, Pressable, Switch, Text, TextInput, View } from "react-native";

import { makeStyles, radius, spacing, typography, useTheme } from "@/src/theme";

const useStyles = makeStyles((colors) => ({
  field: { marginBottom: spacing.md },
  label: { fontSize: typography.scale.sm, fontWeight: "600", color: colors.onSurfaceSecondary, marginBottom: 6 },
  req: { color: colors.error },
  input: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, minHeight: 44,
    fontSize: typography.scale.base, color: colors.onSurface, paddingVertical: spacing.sm,
  },
  inputMultiline: { minHeight: 88, textAlignVertical: "top" },
  inputDisabled: { backgroundColor: colors.surfaceTertiary, color: colors.onSurfaceTertiary },
  selectText: { fontSize: typography.scale.base, color: colors.onSurface, paddingVertical: 0 },
  selectPlaceholder: { color: colors.muted },
  overlay: { flex: 1, backgroundColor: "rgba(26,26,24,0.5)", justifyContent: Platform.OS === "web" ? "center" : "flex-end", alignItems: Platform.OS === "web" ? "center" : "stretch" },
  sheet: {
    backgroundColor: colors.surfaceSecondary, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    maxHeight: "60%", paddingBottom: spacing.xl,
    ...(Platform.OS === "web" ? { borderRadius: radius.lg, width: 420, maxWidth: "92%" } : {}),
  },
  option: { paddingVertical: spacing.md, paddingHorizontal: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.divider },
  optionText: { fontSize: typography.scale.base, color: colors.onSurface },
}));

export function FieldLabel({ label, required }: { label: string; required?: boolean }) {
  const styles = useStyles();
  return (
    <Text style={styles.label}>
      {label} {required ? <Text style={styles.req}>*</Text> : null}
    </Text>
  );
}

export function TextField({ label, value, onChange, required, multiline, testID, keyboardType, autoCapitalize, editable, placeholder, secure }: {
  label: string; value: string | null | undefined; onChange: (v: string) => void; required?: boolean;
  multiline?: boolean; testID?: string; keyboardType?: "default" | "numeric" | "email-address" | "phone-pad";
  autoCapitalize?: "none" | "sentences" | "words"; editable?: boolean; placeholder?: string; secure?: boolean;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={styles.field}>
      <FieldLabel label={label} required={required} />
      <TextInput
        style={[styles.input, multiline && styles.inputMultiline, editable === false && styles.inputDisabled]}
        value={value ?? ""}
        onChangeText={onChange}
        placeholder={placeholder ?? (required ? "Required" : "")}
        placeholderTextColor={colors.muted}
        multiline={multiline}
        editable={editable !== false}
        secureTextEntry={secure}
        testID={testID}
        keyboardType={keyboardType}
        autoCapitalize={autoCapitalize ?? "none"}
      />
    </View>
  );
}

function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

export function SelectField({ label, value, options, onChange, testID }: {
  label: string; value: string | null | undefined; options: string[]; onChange: (v: string) => void; testID?: string;
}) {
  const styles = useStyles();
  const [open, setOpen] = useState(false);
  return (
    <View style={styles.field}>
      <FieldLabel label={label} />
      <Pressable style={[styles.input, { justifyContent: "center" }]} onPress={() => setOpen(true)} testID={testID ?? "select-field"}>
        <Text style={[styles.selectText, !value && styles.selectPlaceholder]}>{value || "Select…"}</Text>
      </Pressable>
      <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.overlay} onPress={() => setOpen(false)}>
          <Pressable style={styles.sheet} onPress={() => {}}>
            <View style={{ paddingHorizontal: spacing.lg, paddingTop: spacing.lg }}>
              <FieldLabel label={label} />
            </View>
            <FlatList
              data={options}
              keyExtractor={(i) => i}
              renderItem={({ item }) => (
                <Pressable
                  style={styles.option}
                  onPress={() => { onChange(item); setOpen(false); }}
                  testID={`select-option-${slug(item)}`}
                >
                  <Text style={[styles.optionText, item === value && { fontWeight: "700" }]}>{item}</Text>
                </Pressable>
              )}
            />
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

export function SwitchRow({ label, value, onChange, testID, note }: {
  label: string; value: boolean; onChange: (v: boolean) => void; testID?: string; note?: string;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  return (
    <View style={[styles.field, { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.md }]}>
      <View style={{ flex: 1 }}>
        <FieldLabel label={label} />
        {note ? <Text style={{ color: colors.muted, fontSize: typography.scale.sm }}>{note}</Text> : null}
      </View>
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ false: colors.border, true: colors.brandPrimary }}
        thumbColor="#FFFFFF"
        testID={testID}
      />
    </View>
  );
}
