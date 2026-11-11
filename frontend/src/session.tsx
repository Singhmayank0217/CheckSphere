// Session provider: token + user persistence, inactivity auto-logout, 401 handling.
import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { AppState } from "react-native";

import { api, setOnUnauthorized, setTokenProvider } from "@/src/api";
import { storage } from "@/src/utils/storage";

export type SessionUser = {
  id: string;
  name: string;
  role: "super_admin" | "supervisor" | "agent";
  agent_id?: string | null;
  email?: string | null;
  phone?: string | null;
  must_change_password?: boolean;
  disabled?: boolean;
  scope?: any;
};

type SessionCtx = {
  ready: boolean;
  user: SessionUser | null;
  token: string | null;
  signIn: (data: { access_token: string; user: SessionUser }) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
};

const Ctx = createContext<SessionCtx>({
  ready: false,
  user: null,
  token: null,
  signIn: async () => {},
  signOut: async () => {},
  refresh: async () => {},
});

const INACTIVITY_MS = 15 * 60 * 1000;

export function SessionProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<SessionUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const signOutRef = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    (async () => {
      const t = await storage.secureGet("auth_token", null);
      if (t) {
        setToken(t);
        setTokenProvider(() => Promise.resolve(t));
        try {
          const me = await api<{ user: SessionUser }>("/auth/me");
          setUser(me.user);
        } catch {
          await storage.secureRemove("auth_token");
          await storage.removeItem("auth_user");
        }
      }
      setReady(true);
    })();
  }, []);

  const signIn = useCallback(async (data: { access_token: string; user: SessionUser }) => {
    setTokenProvider(() => Promise.resolve(data.access_token));
    await storage.secureSet("auth_token", data.access_token);
    await storage.setItem("auth_user", JSON.stringify(data.user));
    setToken(data.access_token);
    setUser(data.user);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {
      // session may already be revoked
    }
    setTokenProvider(() => Promise.resolve(null));
    await storage.secureRemove("auth_token");
    await storage.removeItem("auth_user");
    setUser(null);
    setToken(null);
  }, []);
  signOutRef.current = signOut;

  useEffect(() => {
    setOnUnauthorized(() => signOutRef.current());
  }, [signOut]);

  // Auto logout after inactivity (backgrounded too long)
  useEffect(() => {
    let backgroundedAt: number | null = null;
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") {
        if (backgroundedAt && Date.now() - backgroundedAt > INACTIVITY_MS) {
          signOutRef.current();
        }
        backgroundedAt = null;
      } else if (backgroundedAt === null) {
        backgroundedAt = Date.now();
      }
    });
    return () => sub.remove();
  }, []);

  // Web has no AppState backgrounding: idle timer on user events
  useEffect(() => {
    if (typeof document === "undefined") return;
    let last = Date.now();
    const bump = () => {
      last = Date.now();
    };
    const timer = setInterval(() => {
      if (user && Date.now() - last > INACTIVITY_MS) signOutRef.current();
    }, 30 * 1000);
    ["mousedown", "keydown", "touchstart"].forEach((e) => document.addEventListener(e, bump));
    return () => {
      clearInterval(timer);
      ["mousedown", "keydown", "touchstart"].forEach((e) => document.removeEventListener(e, bump));
    };
  }, [user]);

  const refresh = useCallback(async () => {
    const me = await api<{ user: SessionUser }>("/auth/me");
    setUser(me.user);
    await storage.setItem("auth_user", JSON.stringify(me.user));
  }, []);

  // Keep AsyncStorage web shim clean (unused warm-up to surface quota errors early)
  useEffect(() => {
    AsyncStorage.getItem("auth_user").catch(() => null);
  }, []);

  return (
    <Ctx.Provider value={{ ready, user, token, signIn, signOut, refresh }}>{children}</Ctx.Provider>
  );
}

export const useSession = () => useContext(Ctx);
