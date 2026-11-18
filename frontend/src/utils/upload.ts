// Multipart upload that works in BOTH runtimes. Use this for every file upload; never
// build the FormData part yourself.
//
//   import { uploadForm } from "@/src/utils/upload";
//   const res = await uploadForm(`${BACKEND_URL}/api/photos`, {
//     fields: { caption },
//     files: { image: { uri: asset.uri, name: "photo.jpg", mimeType: asset.mimeType } },
//   });
//
// Why: on a phone the global fetch is `expo/fetch` (SDK 54+), which rejects the old RN
// `{ uri, name, type }` part with "Unsupported FormDataPart implementation". The web
// preview accepts that shape, so the bug only shows on a device. Never set Content-Type:
// the runtime adds the multipart boundary. No extra dependency: `expo/fetch` reads
// `file://` on iOS and Android itself (React Native's own fetch cannot on Android).

import { Platform } from "react-native";
import { fetch as expoFetch } from "expo/fetch";
import { File as FSFile } from "expo-file-system";

export type LocalFile = {
  uri: string; // asset.uri from expo-image-picker / expo-document-picker / expo-audio
  name?: string; // "photo.jpg"; last path segment of uri when omitted
  mimeType?: string; // asset.mimeType, e.g. "image/jpeg"
};

export type UploadOptions = {
  files: Record<string, LocalFile>; // form field name -> file
  fields?: Record<string, string>;
  method?: "POST" | "PUT";
  headers?: Record<string, string>; // auth only; never Content-Type
  signal?: AbortSignal;
};

export function fileNameFor(file: LocalFile): string {
  return file.name || file.uri.split("?")[0].split("/").pop() || "file";
}

// Raised when the local file cannot be read; the upload is NOT attempted (never send an error body as the file).
export class LocalFileError extends Error {}

// Turn a local file into a part that the current runtime's fetch can serialise.
//
// Root cause of the Android "Unsupported file type" rejection: the previous native path read the photo with
// expo/fetch(file://...). When that path is missing, Expo's Android file handler does not throw — it returns an
// HTTP 404 whose body is the text "File not found". The response status was never checked, so those 14 bytes
// were uploaded as "capture.jpg" and the server (correctly) rejected them as not being an image.
// Now: native files are passed as expo-file-system File objects (bytes are read natively by expo/fetch's
// multipart encoder — no Blob/base64 round trip), and missing/empty files fail loudly on the phone.
export async function toFormDataPart(file: LocalFile): Promise<Blob> {
  if (Platform.OS === "web") {
    // blob:/data: URL from the browser picker; the browser fetch reads it fine.
    const res = await fetch(file.uri);
    if (!res.ok) throw new LocalFileError(`Could not read the selected file (${res.status})`);
    const blob = await res.blob();
    const type = file.mimeType || blob.type;
    return type && type !== blob.type ? new Blob([blob], { type }) : blob;
  }
  const f = new FSFile(file.uri);
  // Generic wording: this helper serves photos AND documents (the photo queue maps it to its own photo message).
  if (!f.exists) throw new LocalFileError("The selected file is unavailable on this device. Please select it again.");
  if (!f.size) throw new LocalFileError("The selected file on this device is empty. Please select it again.");
  return f as unknown as Blob;
}

export async function uploadForm(url: string, opts: UploadOptions): Promise<Response> {
  const form = new FormData();
  for (const [k, v] of Object.entries(opts.fields ?? {})) form.append(k, v);
  for (const [field, file] of Object.entries(opts.files)) {
    form.append(field, await toFormDataPart(file), fileNameFor(file));
  }
  const init = {
    method: opts.method ?? "POST",
    body: form,
    headers: opts.headers, // the runtime adds the multipart boundary
    signal: opts.signal,
  };
  // Branch the call, not the function reference: the two fetches have different RequestInit types.
  return Platform.OS === "web" ? fetch(url, init) : expoFetch(url, init);
}
