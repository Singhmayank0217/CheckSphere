// Reliable photo upload queue. A captured photo is copied into the app's private document storage together
// with its original capture metadata (shutter time, GPS at capture, slot) BEFORE any network call.
// It is removed only after the server confirms the upload. Retries reuse the same upload_id, which the
// server de-duplicates, so a retry can never create a second evidence record.
// A queued photo is NOT counted as a completed photo until the server has it.
import { Platform } from "react-native";
import * as Crypto from "expo-crypto";
import { Directory, File, Paths } from "expo-file-system";

import { API_URL, getDeviceId } from "@/src/api";
import { CLIENT_BUILD } from "@/src/buildInfo";
import { storage } from "@/src/utils/storage";
import { LocalFileError, uploadForm } from "@/src/utils/upload";
import { fetch as expoFetch } from "expo/fetch";

const KEY = "pending_photo_uploads_v1";

export type PendingMeta = {
  capturedAt: string; // device time at shutter (ISO, UTC)
  lat?: number;
  lon?: number;
  accuracy?: number;
  gpsStatus: string;
  mocked?: boolean;
  gpsFixAt?: string;
  gpsSource?: string; // "watch" (continuous fix, <=15 s old at the shutter) or "request" (fix requested at the shutter)
  locationReason?: string;
};

export type PendingUpload = {
  uploadId: string;
  caseId: string;
  slot: string;
  label: string;
  fileUri: string;
  meta: PendingMeta;
  state: "pending" | "failed";
  attempts: number;
  directPut?: boolean; // the bytes already reached private storage via a signed URL; only "complete" is left
  lastError?: string;
  createdAt: string;
};

export type UploadOutcome =
  | { ok: true; evidence: any }
  | { ok: false; retryable: boolean; status: number; message: string; detail?: any };

let processing: Promise<number> | null = null;
const listeners = new Set<() => void>();
export function onQueueChange(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}
const notify = () => listeners.forEach((fn) => fn());

async function readAll(): Promise<PendingUpload[]> {
  const raw = await storage.getItem<string | null>(KEY, null);
  try {
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

async function writeAll(items: PendingUpload[]) {
  await storage.setItem(KEY, JSON.stringify(items));
  notify();
}

export async function listPending(caseId?: string): Promise<PendingUpload[]> {
  const all = await readAll();
  return caseId ? all.filter((p) => p.caseId === caseId) : all;
}

export const PHOTO_UNAVAILABLE = "Photo file unavailable – please retake the photo";
export class PhotoUnavailableError extends Error {
  constructor(detail?: string) {
    super(PHOTO_UNAVAILABLE);
    this.name = detail ?? "PhotoUnavailableError";
  }
}

const MIN_PHOTO_BYTES = 1024; // a real camera photo is never this small
const log = (msg: string, data?: Record<string, unknown>) => console.log(`[CheckSphere capture] ${msg}`, data ?? "");

// Detect the image format from the file's leading bytes (same signatures the server accepts).
export function detectImageFormat(h: Uint8Array): "jpeg" | "png" | "webp" | "heic" | null {
  if (h.length < 12) return null;
  const ascii = (a: number, b: number) => String.fromCharCode(...Array.from(h.slice(a, b)));
  if (h[0] === 0xff && h[1] === 0xd8 && h[2] === 0xff) return "jpeg";
  if (h[0] === 0x89 && ascii(1, 4) === "PNG") return "png";
  if (ascii(0, 4) === "RIFF" && ascii(8, 12) === "WEBP") return "webp";
  if (ascii(4, 8) === "ftyp") return "heic";
  return null;
}

export type LocalPhotoInfo = { ok: boolean; exists: boolean; size: number; format: string | null; reason?: string };

// Read the actual file bytes (not just metadata) before anything is uploaded.
export function inspectLocalPhoto(uri: string): LocalPhotoInfo {
  if (Platform.OS === "web") return { ok: true, exists: true, size: 0, format: "jpeg" };
  try {
    const f = new File(uri);
    if (!f.exists) return { ok: false, exists: false, size: 0, format: null, reason: "missing" };
    const size = f.size ?? 0;
    if (size < MIN_PHOTO_BYTES) return { ok: false, exists: true, size, format: null, reason: "too_small" };
    const handle = f.open();
    let head: Uint8Array;
    try {
      head = handle.readBytesSync(12);
    } finally {
      handle.close();
    }
    const format = detectImageFormat(head);
    if (!format) return { ok: false, exists: true, size, format: null, reason: "not_an_image" };
    return { ok: true, exists: true, size, format };
  } catch (e: any) {
    return { ok: false, exists: false, size: 0, format: null, reason: `read_error:${e?.message ?? "unknown"}` };
  }
}

export type PreparedPhoto = { uploadId: string; uri: string; size: number; format: string };

// Called immediately after the shutter, before the review screen or any navigation: copies the camera's
// temporary cache file into the app's private document storage and verifies the copy byte-for-byte header
// and size. The camera cache file is never used for uploading. Throws PhotoUnavailableError on any problem.
export async function preparePhoto(cameraUri: string): Promise<PreparedPhoto> {
  const uploadId = Crypto.randomUUID();
  if (Platform.OS === "web") return { uploadId, uri: cameraUri, size: 0, format: "jpeg" };
  const src = inspectLocalPhoto(cameraUri);
  log("camera output", { cameraUri, exists: src.exists, size: src.size, format: src.format, reason: src.reason });
  if (!src.ok) throw new PhotoUnavailableError(`camera_${src.reason}`);
  const ext = src.format === "jpeg" ? "jpg" : src.format!;
  const dir = new Directory(Paths.document, "pending_uploads");
  if (!dir.exists) dir.create({ intermediates: true, idempotent: true });
  const dest = new File(dir, `${uploadId}.${ext}`);
  try {
    await new File(cameraUri).copy(dest);
  } catch (e: any) {
    log("copy failed", { cameraUri, error: e?.message });
    throw new PhotoUnavailableError("copy_failed");
  }
  const copy = inspectLocalPhoto(dest.uri);
  log("persistent copy", { persistentUri: dest.uri, exists: copy.exists, size: copy.size, format: copy.format, reason: copy.reason });
  if (!copy.ok || copy.size !== src.size) {
    removeFileSync(dest.uri);
    throw new PhotoUnavailableError("copy_verification_failed");
  }
  return { uploadId, uri: dest.uri, size: copy.size, format: copy.format! };
}

function removeFileSync(uri: string) {
  try {
    const f = new File(uri);
    if (f.exists) f.delete();
  } catch {
    // already gone
  }
}

// Retake / cancel before "Use Photo": delete the private copy (it was never queued).
export function discardPrepared(p: PreparedPhoto | null | undefined) {
  if (p && Platform.OS !== "web") removeFileSync(p.uri);
}

async function removeFile(uri: string) {
  if (Platform.OS === "web") return;
  try {
    const f = new File(uri);
    if (f.exists) f.delete();
  } catch {
    // already gone
  }
}

async function send(item: PendingUpload, token: string | null): Promise<UploadOutcome> {
  const m = item.meta;
  const fields: Record<string, string> = {
    case_id: item.caseId,
    slot: item.slot,
    kind: "photo",
    captured_at: m.capturedAt,
    gps_status: m.gpsStatus,
    upload_id: item.uploadId,
    device_id: await getDeviceId(),
  };
  if (m.lat != null && m.lon != null) {
    fields.lat = String(m.lat);
    fields.lon = String(m.lon);
    if (m.accuracy != null) fields.accuracy = String(m.accuracy);
  }
  if (m.mocked != null) fields.mocked = String(!!m.mocked);
  if (m.gpsFixAt) fields.gps_fix_at = m.gpsFixAt;
  if (m.gpsSource) fields.gps_source = m.gpsSource;
  if (m.locationReason) fields.location_reason = m.locationReason;
  const local = inspectLocalPhoto(item.fileUri);
  log("upload attempt", { uploadId: item.uploadId, fileUri: item.fileUri, exists: local.exists, size: local.size,
    format: local.format, reason: local.reason, attempt: item.attempts + 1 });
  if (!local.ok) return { ok: false, retryable: false, status: -1, message: PHOTO_UNAVAILABLE };
  fields.client_build = CLIENT_BUILD;
  fields.client_file_size = String(local.size);
  fields.client_format = String(local.format);
  const ext = local.format === "jpeg" ? "jpg" : local.format;
  const mime = local.format === "jpeg" ? "image/jpeg" : `image/${local.format}`;
  if (Platform.OS !== "web") {
    const direct = await sendDirect(item, token, fields, mime, `${item.slot}-${item.uploadId.slice(0, 8)}.${ext}`);
    if (direct !== "fallback") return direct;
    log("direct upload unavailable, using API upload", { uploadId: item.uploadId });
  }
  let res: Response;
  try {
    res = await uploadForm(`${API_URL}/api/evidence/upload`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      fields,
      files: { file: { uri: item.fileUri, name: `${item.slot}-${item.uploadId.slice(0, 8)}.${ext}`, mimeType: mime } },
    });
  } catch (e) {
    if (e instanceof LocalFileError) return { ok: false, retryable: false, status: -1, message: PHOTO_UNAVAILABLE };
    return { ok: false, retryable: true, status: 0, message: "No connection — the photo is saved and will upload automatically." };
  }
  const text = await res.text();
  let body: any = null;
  try {
    body = JSON.parse(text);
  } catch {
    body = null;
  }
  log("upload response", { uploadId: item.uploadId, status: res.status });
  if (res.ok && body?.id) return { ok: true, evidence: body };
  if (res.ok) return { ok: false, retryable: true, status: res.status, message: "Server did not confirm the upload; will retry." };
  const detail = body?.detail;
  const message = typeof detail === "string" ? detail : detail?.message ?? `Upload failed (${res.status})`;
  // 5xx / 429 are temporary; 4xx means the server refused this photo (e.g. case locked, reason required)
  const retryable = res.status >= 500 || res.status === 429 || res.status === 408;
  return { ok: false, retryable, status: res.status, message, detail };
}

const OFFLINE: UploadOutcome = { ok: false, retryable: true, status: 0, message: "No connection — the photo is saved and will upload automatically." };

function outcomeFrom(status: number, body: any): UploadOutcome {
  const detail = body?.detail;
  const message = typeof detail === "string" ? detail : detail?.message ?? `Upload failed (${status})`;
  const retryable = status >= 500 || status === 429 || status === 408;
  return { ok: false, retryable, status, message, detail };
}

const toHex = (buf: ArrayBuffer) => Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");

async function setDirectPut(uploadId: string, value: boolean) {
  const all = await readAll();
  await writeAll(all.map((p) => (p.uploadId === uploadId ? { ...p, directPut: value } : p)));
}

// Direct upload: 1) the server checks role/case/slot and returns a short-lived signed URL for ONE private object
// (size, type and SHA-256 are part of the signature); 2) the phone PUTs the bytes straight to storage; 3) the server
// re-checks size + SHA-256 + real image type, watermarks, stores and records the evidence. Every step is keyed by
// upload_id, so retries never duplicate. Returns "fallback" whenever the API upload should be used instead (older
// server, direct upload switched off, or storage refused the PUT); nothing has been recorded in that case.
async function sendDirect(item: PendingUpload, token: string | null, fields: Record<string, string>, mime: string,
  filename: string): Promise<UploadOutcome | "fallback"> {
  const auth: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
  let bytes: Uint8Array;
  try {
    bytes = await new File(item.fileUri).bytes();
  } catch {
    return { ok: false, retryable: false, status: -1, message: PHOTO_UNAVAILABLE };
  }
  const sha256 = toHex(await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, bytes as unknown as BufferSource));

  let r: Response;
  try {
    r = await fetch(`${API_URL}/api/evidence/upload-url`, {
      method: "POST",
      headers: { ...auth, "Content-Type": "application/json" },
      body: JSON.stringify({ case_id: item.caseId, slot: item.slot, kind: "photo", upload_id: item.uploadId,
        size: bytes.length, sha256, content_type: mime, filename }),
    });
  } catch {
    return OFFLINE;
  }
  if (r.status === 404 || r.status === 405) return "fallback"; // server without direct upload
  const grant = await r.json().catch(() => null);
  if (r.status === 409 && grant?.detail?.code === "direct_upload_unavailable") return "fallback";
  if (!r.ok) return outcomeFrom(r.status, grant);
  if (grant?.already_uploaded && grant.evidence?.id) return { ok: true, evidence: grant.evidence };

  if (!item.directPut) {
    let put: Response;
    try {
      put = (await expoFetch(grant.url, { method: "PUT", headers: grant.headers, body: bytes as any })) as unknown as Response;
    } catch {
      return OFFLINE;
    }
    log("direct put", { uploadId: item.uploadId, status: put.status });
    if (!put.ok) return "fallback"; // e.g. signature/clock problem: the API upload path still works
    await setDirectPut(item.uploadId, true);
  }

  const { case_id: _c, slot: _s, kind: _k, ...completeFields } = fields;
  let c: Response;
  try {
    c = await uploadForm(`${API_URL}/api/evidence/complete`, { headers: auth, fields: completeFields, files: {} });
  } catch {
    return OFFLINE;
  }
  const body = await c.json().catch(() => null);
  log("direct complete", { uploadId: item.uploadId, status: c.status });
  if (c.ok && body?.id) return { ok: true, evidence: body };
  if (c.status === 409 && body?.detail?.code === "upload_missing") {
    await setDirectPut(item.uploadId, false); // storage does not have it (expired/cleaned): upload again next try
    return { ok: false, retryable: true, status: 409, message: "Upload incomplete; retrying." };
  }
  if (c.status === 400 && ["checksum_mismatch", "size_mismatch"].includes(body?.detail?.code)) {
    await setDirectPut(item.uploadId, false);
    return { ok: false, retryable: true, status: 400, message: "Upload was corrupted in transit; retrying." };
  }
  return outcomeFrom(c.status, body);
}

// Save first, then try to upload. Returns the server outcome of the first attempt.
export async function enqueueAndUpload(
  input: { caseId: string; slot: string; label: string; photo: PreparedPhoto; meta: PendingMeta },
  token: string | null,
): Promise<{ item: PendingUpload; outcome: UploadOutcome }> {
  const { uploadId, uri: fileUri } = input.photo;
  const item: PendingUpload = {
    uploadId, caseId: input.caseId, slot: input.slot, label: input.label, fileUri, meta: input.meta,
    state: "pending", attempts: 0, createdAt: new Date().toISOString(),
  };
  await writeAll([...(await readAll()), item]);
  const outcome = await attempt(item, token);
  return { item, outcome };
}

async function attempt(item: PendingUpload, token: string | null): Promise<UploadOutcome> {
  const outcome = await send(item, token);
  const all = await readAll();
  if (outcome.ok) { // server confirmed storage (evidence id returned) -> only now remove the local original
    await writeAll(all.filter((p) => p.uploadId !== item.uploadId));
    await removeFile(item.fileUri);
  } else {
    await writeAll(all.map((p) => (p.uploadId === item.uploadId
      ? { ...p, attempts: p.attempts + 1, lastError: outcome.message, state: outcome.retryable ? "pending" : "failed" }
      : p)));
  }
  return outcome;
}

// Retry every pending (not failed) upload. Safe to call often; runs one pass at a time.
export function processPendingUploads(token: string | null): Promise<number> {
  if (processing) return processing;
  processing = (async () => {
    let done = 0;
    for (const item of await readAll()) {
      if (item.state !== "pending") continue;
      const r = await attempt(item, token);
      if (r.ok) done += 1;
      else if (r.retryable && r.status === 0) break; // offline: stop this pass
    }
    return done;
  })().finally(() => {
    processing = null;
  });
  return processing;
}

// Retry a single failed item, optionally adding the agent's location reason the server asked for.
export async function retryUpload(uploadId: string, token: string | null, locationReason?: string): Promise<UploadOutcome | null> {
  const all = await readAll();
  const item = all.find((p) => p.uploadId === uploadId);
  if (!item) return null;
  const updated = { ...item, state: "pending" as const, meta: { ...item.meta, ...(locationReason ? { locationReason } : {}) } };
  await writeAll(all.map((p) => (p.uploadId === uploadId ? updated : p)));
  return attempt(updated, token);
}

// Agent explicitly discards a photo that the server refused (it was never counted as completed).
export async function discardUpload(uploadId: string) {
  const all = await readAll();
  const item = all.find((p) => p.uploadId === uploadId);
  if (item) await removeFile(item.fileUri);
  await writeAll(all.filter((p) => p.uploadId !== uploadId));
}
