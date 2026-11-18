// API client for the CheckSphere backend. All routes are under {BACKEND}/api.
import { Platform } from "react-native";
import * as Crypto from "expo-crypto";

import { storage } from "@/src/utils/storage";

export const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";

let tokenProvider: () => Promise<string | null> = () => storage.secureGet("auth_token", null);
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

// ---------------------------------------------------------------- cold start (Railway Serverless) handling
// A sleeping server takes a few seconds to wake; meanwhile the platform answers 502/503 or the connection fails.
// Requests are retried with backoff for up to ~60 s while a "Server is starting up" banner is shown.
// GETs are always safe to repeat. Every other method carries an Idempotency-Key that stays the same across these
// retries, so the server replays the first result instead of creating a second case/request/submission.
export type ServerState = "ok" | "waking";
let serverState: ServerState = "ok";
const serverListeners = new Set<(s: ServerState) => void>();
export function onServerState(fn: (s: ServerState) => void) {
  serverListeners.add(fn);
  fn(serverState);
  return () => {
    serverListeners.delete(fn);
  };
}
let wakingCount = 0;
function setWaking(on: boolean) {
  wakingCount = Math.max(0, wakingCount + (on ? 1 : -1));
  const next: ServerState = wakingCount > 0 ? "waking" : "ok";
  if (next !== serverState) {
    serverState = next;
    serverListeners.forEach((fn) => fn(next));
  }
}

const RETRY_DELAYS_MS = [1000, 2000, 3000, 5000, 8000, 10000, 15000, 15000]; // ~59 s in total
const TRANSIENT = new Set([502, 503, 504]);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// fetch with cold-start retries. Retries only: a network failure, 502/503/504, or 409 request_in_progress (the
// server is still finishing the first copy of this idempotent request). Never retries a definite answer.
export async function fetchWithWake(url: string, init: RequestInit, opts: { retry: boolean } = { retry: true }): Promise<Response> {
  const keyed = !!(init.headers as Record<string, string> | undefined)?.["Idempotency-Key"];
  let waking = false;
  try {
    for (let i = 0; ; i++) {
      let res: Response | null = null;
      let netErr: unknown = null;
      try {
        res = await fetch(url, init);
      } catch (e) {
        netErr = e;
      }
      let transient = netErr !== null || (res !== null && TRANSIENT.has(res.status));
      if (!transient && res && res.status === 409 && keyed) {
        const body = await res.clone().json().catch(() => null);
        transient = body?.detail?.code === "request_in_progress";
      }
      if (!transient || !opts.retry || i >= RETRY_DELAYS_MS.length) {
        if (netErr !== null) throw netErr;
        return res!;
      }
      if (!waking) {
        waking = true;
        setWaking(true);
      }
      await sleep(RETRY_DELAYS_MS[i]);
    }
  } finally {
    if (waking) setWaking(false);
  }
}

export function newIdempotencyKey(): string {
  return Crypto.randomUUID();
}

export async function api<T = any>(path: string, opts: { method?: string; body?: any; idempotencyKey?: string } = {}): Promise<T> {
  const token = await tokenProvider();
  const method = (opts.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  if (method !== "GET" && method !== "HEAD") headers["Idempotency-Key"] = opts.idempotencyKey ?? newIdempotencyKey();
  const res = await fetchWithWake(`${API_URL}/api${path}`, {
    method,
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
  const data = isJson ? await res.json() : await res.text();
  if (res.status === 401) {
    if (token && path !== "/auth/logout") onUnauthorized?.();
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

export async function loginRequest(identifier: string, password: string, expectedRole?: string) {
  const deviceId = await getDeviceId();
  // Login is safe to repeat (a lost response only leaves an extra session that expires), so it retries on wake-up.
  const res = await fetchWithWake(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      identifier,
      password,
      expected_role: expectedRole,
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
export type DownloadProgress = { phase: "preparing" | "downloading"; loaded: number; total: number | null };

// Authorised download through the API (never a direct storage link). onProgress reports "preparing" while the server
// builds the file, then bytes received. The server's file name (Content-Disposition) is used when present.
export async function downloadFile(path: string, filename: string, onProgress?: (p: DownloadProgress) => void) {
  const token = await tokenProvider();
  onProgress?.({ phase: "preparing", loaded: 0, total: null });
  const res = await fetchWithWake(`${API_URL}/api${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let msg = "Download failed";
    try { const b = await res.json(); if (typeof b?.detail === "string") msg = b.detail; } catch { /* not JSON */ }
    throw new ApiError(res.status, msg);
  }
  if (Platform.OS === "web") {
    const total = Number(res.headers.get("Content-Length")) || null;
    const cd = res.headers.get("Content-Disposition") ?? "";
    const serverName = /filename="([^"]+)"/.exec(cd)?.[1];
    let blob: Blob;
    if (res.body && onProgress) {
      const reader = res.body.getReader();
      const chunks: Uint8Array[] = [];
      let loaded = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        loaded += value.length;
        onProgress({ phase: "downloading", loaded, total });
      }
      blob = new Blob(chunks as BlobPart[], { type: res.headers.get("Content-Type") ?? "application/octet-stream" });
    } else {
      blob = await res.blob();
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = serverName || filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    return;
  }
  throw new ApiError(400, "File downloads are available on the web dashboard");
}

export { uploadForm } from "@/src/utils/upload";
