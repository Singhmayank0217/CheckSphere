// PDF document handling for "Upload New Cases" — deliberately separate from the camera photo pipeline
// (pendingUploads.ts). The selected PDF is copied into private app storage right after it is picked, validated
// byte-for-byte (%PDF- signature, non-zero size), uploaded with its original filename as application/pdf, and the
// local copy is deleted only after the server confirms storage and returns the stored document id.
import { Platform } from "react-native";
import * as Crypto from "expo-crypto";
import { Directory, File, Paths } from "expo-file-system";
import { fetch as expoFetch } from "expo/fetch";

export const PDF_UNAVAILABLE = "The selected PDF is unavailable on this device. Please select the document again.";
export const NOT_A_PDF = "The selected file is not a valid PDF document. Please select a PDF.";
export const MAX_PDF_BYTES = 10 * 1024 * 1024;

export class DocumentError extends Error {}

const log = (msg: string, data?: Record<string, unknown>) => console.log(`[CheckSphere document] ${msg}`, data ?? "");

export type PreparedPdf = {
  id: string;
  uri: string;        // persistent private copy (native) or the picker's blob/data URI (web)
  name: string;       // original filename shown to the agent and sent to the server
  size: number;
  webFile?: Blob;     // web only: the picked file itself
};

const isPdfHeader = (h: Uint8Array) => h.length >= 5 && String.fromCharCode(...Array.from(h.slice(0, 5))) === "%PDF-";

function safeName(name: string | undefined | null): string {
  const base = (name || "document.pdf").replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_").slice(0, 120);
  return /\.pdf$/i.test(base) ? base : `${base}.pdf`;
}

function inspect(uri: string): { exists: boolean; size: number; pdf: boolean; error?: string } {
  try {
    const f = new File(uri);
    if (!f.exists) return { exists: false, size: 0, pdf: false };
    const size = f.size ?? 0;
    if (!size) return { exists: true, size: 0, pdf: false };
    const h = f.open();
    try {
      return { exists: true, size, pdf: isPdfHeader(h.readBytesSync(5)) };
    } finally {
      h.close();
    }
  } catch (e: any) {
    return { exists: false, size: 0, pdf: false, error: e?.message ?? String(e) };
  }
}

// Called immediately after the document picker returns.
export async function preparePdf(asset: { uri: string; name?: string | null; size?: number | null; mimeType?: string | null; file?: any }): Promise<PreparedPdf> {
  const id = Crypto.randomUUID();
  const name = safeName(asset.name);
  if (Platform.OS === "web") {
    const blob: Blob = asset.file ?? (await (await fetch(asset.uri)).blob());
    const head = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
    if (!blob.size) throw new DocumentError(PDF_UNAVAILABLE);
    if (!isPdfHeader(head)) throw new DocumentError(NOT_A_PDF);
    if (blob.size > MAX_PDF_BYTES) throw new DocumentError("The PDF is larger than 10 MB. Please select a smaller document.");
    return { id, uri: asset.uri, name, size: blob.size, webFile: blob };
  }
  const src = inspect(asset.uri);
  log("picked", { pickerUri: asset.uri, scheme: asset.uri.split(":")[0], reportedSize: asset.size, mimeType: asset.mimeType, ...src });
  const dir = new Directory(Paths.document, "pending_documents", id);
  dir.create({ intermediates: true, idempotent: true });
  const dest = new File(dir, name); // keeps the original filename for the upload
  let copied = false;
  if (src.exists) {
    try {
      await new File(asset.uri).copy(dest);
      copied = true;
    } catch (e: any) {
      log("file copy failed", { error: e?.message });
    }
  }
  if (!copied) {
    // Fallback read through expo/fetch — the HTTP status is checked, so an error body can never become the "PDF".
    try {
      const res = await expoFetch(asset.uri);
      if (!res.ok) throw new Error(`read status ${res.status}`);
      const bytes = new Uint8Array(await res.arrayBuffer());
      if (!isPdfHeader(bytes)) throw new DocumentError(NOT_A_PDF);
      dest.create({ overwrite: true });
      dest.writeSync(bytes);
      copied = true;
    } catch (e: any) {
      log("fallback read failed", { error: e?.message });
      try { dir.delete(); } catch { /* nothing to clean */ }
      if (e instanceof DocumentError) throw e;
      throw new DocumentError(PDF_UNAVAILABLE);
    }
  }
  const copy = inspect(dest.uri);
  log("persistent copy", { persistentUri: dest.uri, ...copy });
  if (!copy.exists || !copy.size) {
    try { dir.delete(); } catch { /* ignore */ }
    throw new DocumentError(PDF_UNAVAILABLE);
  }
  if (!copy.pdf) {
    try { dir.delete(); } catch { /* ignore */ }
    throw new DocumentError(NOT_A_PDF);
  }
  if (copy.size > MAX_PDF_BYTES) {
    try { dir.delete(); } catch { /* ignore */ }
    throw new DocumentError("The PDF is larger than 10 MB. Please select a smaller document.");
  }
  return { id, uri: dest.uri, name, size: copy.size };
}

// Re-verify right before building the multipart body (the bytes sent must be the PDF bytes).
export function pdfPart(p: PreparedPdf): Blob {
  if (Platform.OS === "web") return p.webFile as Blob;
  const c = inspect(p.uri);
  log("before upload", { uri: p.uri, ...c, name: p.name });
  if (!c.exists || !c.size) throw new DocumentError(PDF_UNAVAILABLE);
  if (!c.pdf) throw new DocumentError(NOT_A_PDF);
  return new File(p.uri) as unknown as Blob; // expo/fetch reads the bytes natively; name = original filename, type = application/pdf
}

// Only after the server confirmed storage (returned an id).
export function discardPdf(p: PreparedPdf | null | undefined) {
  if (!p || Platform.OS === "web") return;
  try {
    const dir = new Directory(Paths.document, "pending_documents", p.id);
    if (dir.exists) dir.delete();
  } catch {
    // already removed
  }
}
