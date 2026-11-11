// API client for the CheckSphere backend. All routes are under {BACKEND}/api.
import { Platform } from "react-native";
import * as Crypto from "expo-crypto";

import { storage } from "@/src/utils/storage";

export const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";

let tokenProvider: () => Promise<string | null> = async () => null;
let onUnauthorized: (() => void) | null = null;

export function setTokenProvider(fn: () => Promise<string | null>) {
  tokenProvider = fn;
}
export function setOnUnauthorized(fn: () => void) {
  onUnauthorized = fn;
}

export class ApiError extends Error {
  status: number;
  data: any;
  constructor(status: number, message: string, data?: any) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: any } = {}): Promise<T> {
  const token = await tokenProvider();
  const res = await fetch(`${API_URL}/api${path}`, {
    method: opts.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
  const data = isJson ? await res.json() : await res.text();
  if (res.status === 401) {
    onUnauthorized?.();
    throw new ApiError(401, "Session expired. Please sign in again.");
  }
  if (!res.ok) {
    const detail = (data && (typeof data === "object" ? data.detail ?? data.message : data)) ?? "Request failed";
    const message = typeof detail === "string" ? detail : detail.message ?? "Request failed";
    throw new ApiError(res.status, message, typeof detail === "object" ? detail : data);
  }
  return data as T;
}

export async function getDeviceId(): Promise<string> {
  const existing = await storage.getItem("device_id", null);
  if (existing) return existing;
  const id = Crypto.randomUUID();
  await storage.setItem("device_id", id);
  return id;
}

export async function loginRequest(identifier: string, password: string) {
  const deviceId = await getDeviceId();
  const res = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      identifier,
      password,
      device_id: deviceId,
      device_model: `${Platform.OS} ${Platform.Version}`,
      platform: Platform.OS,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = typeof data?.detail === "string" ? data.detail : "Invalid credentials or account suspended";
    throw new ApiError(res.status, msg, data);
  }
  return data;
}

// Authenticated file URL — the backend also accepts the token as a query param
// (web <img> cannot send Authorization headers).
export function fileUrl(evidenceId: string, token: string | null) {
  return `${API_URL}/api/files/${evidenceId}${token ? `?token=${token}` : ""}`;
}

// Download helper: web triggers a file save; native opens the dashboard note.
export async function downloadFile(path: string, filename: string) {
  const token = await tokenProvider();
  const res = await fetch(`${API_URL}/api${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  if (Platform.OS === "web") {
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    return;
  }
  throw new ApiError(400, "File downloads are available on the web dashboard");
}

export { uploadForm } from "@/src/utils/upload";
