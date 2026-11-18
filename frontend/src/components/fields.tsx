// Form field components (theme-tokenised, keyboard-friendly).
import { useState } from "react";
import { FlatList, Modal, Platform, Pressable, Switch, Text, TextInput, View } from "react-native";

import DateTimePicker, { DateTimePickerEvent } from "@react-native-community/datetimepicker";

import { makeStyles, radius, spacing, typography, useTheme } from "@/src/theme";
import { fmtDob, isFuture, localDateToYmd, parseIsoDate, todayIST, toIsoDate, YMD, ymdToLocalDate } from "@/src/utils/dates";

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

// Tick any number of options (e.g. VEE "Reasons for Not Recommended"). Stored as one text value "A; B" so it is
// saved, masked and exported exactly like any other field.
export const MULTI_SEP = "; ";
export function MultiSelectField({ label, value, options, onChange, testID }: {
  label: string; value: string | null | undefined; options: string[]; onChange: (v: string) => void; testID?: string;
}) {
  const styles = useStyles();
  const picked = new Set(String(value ?? "").split(";").map((s) => s.trim()).filter(Boolean));
  const toggle = (o: string) => {
    const next = new Set(picked);
    if (next.has(o)) next.delete(o); else next.add(o);
    onChange(options.filter((x) => next.has(x)).join(MULTI_SEP)); // keep the form's option order
  };
  return (
    <View style={styles.field} testID={testID}>
      <FieldLabel label={label} />
      {options.map((o) => (
        <Pressable key={o} onPress={() => toggle(o)} style={[styles.input, { flexDirection: "row", alignItems: "center", marginBottom: 4 }]}
          accessibilityRole="checkbox" accessibilityState={{ checked: picked.has(o) }} testID={`${testID ?? "multi"}-${slug(o)}`}>
          <Text style={[styles.optionText, { width: 26, fontWeight: "700" }]}>{picked.has(o) ? "☑" : "☐"}</Text>
          <Text style={[styles.optionText, { flex: 1 }]}>{o}</Text>
        </Pressable>
      ))}
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

// Date picker (day / month / year). Stores "YYYY-MM-DD" (no time, no timezone). With maxToday, dates after
// today's date in India cannot be chosen (e.g. Date of Birth). Older free-text values are shown, never altered.
export function DateField({ label, value, onChange, required, maxToday, testID }: {
  label: string; value: string | null | undefined; onChange: (v: string) => void; required?: boolean;
  maxToday?: boolean; testID?: string;
}) {
  const styles = useStyles();
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const parsed = parseIsoDate(value);
  const legacy = !!value && !parsed; // e.g. typed "1204/2001" before the picker existed
  const max = maxToday ? todayIST() : null;
  const accept = (v: YMD | null) => {
    if (!v) return;
    if (max && isFuture(v)) {
      setError("A future date cannot be selected.");
      return;
    }
    setError(null);
    onChange(toIsoDate(v));
  };
  const initial = parsed ?? { y: (max ?? todayIST()).y - 30, m: 1, d: 1 };

  if (Platform.OS === "web") {
    return (
      <View style={styles.field}>
        <FieldLabel label={label} required={required} />
        {/* the browser's own date picker; value format is always YYYY-MM-DD */}
        <input
          type="date"
          value={parsed ? toIsoDate(parsed) : ""}
          max={max ? toIsoDate(max) : undefined}
          min="1900-01-01"
          onChange={(e: any) => accept(parseIsoDate(e.target.value))}
          data-testid={testID}
          style={{ minHeight: 44, borderRadius: 12, border: `1px solid ${colors.border}`, padding: "0 12px",
            fontSize: 16, color: colors.onSurface, background: colors.surfaceSecondary }}
        />
        {legacy ? <Text style={{ color: colors.muted, fontSize: typography.scale.sm, marginTop: 4 }}>Previously entered: {value} — please select the date.</Text> : null}
        {error ? <Text style={{ color: colors.error, fontSize: typography.scale.sm, marginTop: 4 }}>{error}</Text> : null}
      </View>
    );
  }
  return (
    <View style={styles.field}>
      <FieldLabel label={label} required={required} />
      <Pressable style={[styles.input, { justifyContent: "center" }]} onPress={() => setOpen(true)} testID={testID ?? "date-field"}>
        <Text style={[styles.selectText, !parsed && styles.selectPlaceholder]}>{parsed ? fmtDob(value) : "Select date…"}</Text>
      </Pressable>
      {legacy ? <Text style={{ color: colors.muted, fontSize: typography.scale.sm, marginTop: 4 }}>Previously entered: {value} — please select the date.</Text> : null}
      {error ? <Text style={{ color: colors.error, fontSize: typography.scale.sm, marginTop: 4 }}>{error}</Text> : null}
      {open && Platform.OS === "android" ? (
        <DateTimePicker
          value={ymdToLocalDate(initial)} mode="date" display="default"
          maximumDate={max ? ymdToLocalDate(max) : undefined} minimumDate={new Date(1900, 0, 1)}
          onChange={(ev: DateTimePickerEvent, dt?: Date) => {
            setOpen(false);
            if (ev.type === "set" && dt) accept(localDateToYmd(dt));
          }}
        />
      ) : null}
      {Platform.OS === "ios" ? (
        <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
          <Pressable style={styles.overlay} onPress={() => setOpen(false)}>
            <Pressable style={styles.sheet} onPress={() => {}}>
              <DateTimePicker
                value={ymdToLocalDate(initial)} mode="date" display="spinner"
                maximumDate={max ? ymdToLocalDate(max) : undefined} minimumDate={new Date(1900, 0, 1)}
                onChange={(_ev: DateTimePickerEvent, dt?: Date) => { if (dt) accept(localDateToYmd(dt)); }}
              />
              <Pressable style={styles.option} onPress={() => { if (!parsed) accept(initial); setOpen(false); }}>
                <Text style={[styles.optionText, { fontWeight: "700", textAlign: "center" }]}>Done</Text>
              </Pressable>
            </Pressable>
          </Pressable>
        </Modal>
      ) : null}
    </View>
  );
}
