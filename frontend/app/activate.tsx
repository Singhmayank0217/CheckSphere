import { useState } from "react";
import { Pressable, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";

import { API_URL } from "@/src/api";
import { TextField } from "@/src/components/fields";
import { Banner, Btn, Screen } from "@/src/components/ui";

export default function Activate() {
  const { token } = useLocalSearchParams<{ token?: string }>();
  const router = useRouter();
  const [pwd, setPwd] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (pwd.length < 8 || pwd !== confirm) { setMsg({ tone: "error", text: "Passwords must match and be at least 8 characters." }); return; }
    setBusy(true);
    try {
      const res = await fetch(`${API_URL}/api/auth/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, new_password: pwd }) });
      const data = await res.json();
      if (!res.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "Activation failed");
      setMsg({ tone: "success", text: "Account activated. You can now sign in." });
    } catch (e: any) { setMsg({ tone: "error", text: e.message }); } finally { setBusy(false); }
  };
  return (
    <Screen testID="activate-screen">
      <View style={{ maxWidth: 460, width: "100%", alignSelf: "center", marginTop: 48, gap: 8 }}>
        <Text style={{ fontSize: 26, fontWeight: "800", color: "#1F4E3D" }}>Activate your CheckSphere account</Text>
        {msg ? <Banner tone={msg.tone} message={msg.text} /> : null}
        <TextField label="New password" value={pwd} onChange={setPwd} secure testID="activate-password-input" />
        <TextField label="Confirm password" value={confirm} onChange={setConfirm} secure testID="activate-confirm-input" />
        <Btn label="Activate Account" onPress={submit} loading={busy} disabled={!token} testID="activate-submit-btn" full />
        <Pressable onPress={() => router.replace("/")} style={{ alignSelf: "center", padding: 12 }} testID="activate-signin-link">
          <Text style={{ color: "#2B5278", fontWeight: "700" }}>Sign In</Text>
        </Pressable>
      </View>
    </Screen>
  );
}
