// Encrypted offline drafts (AES-CTR via pure-JS aes-js) + auto-sync helpers.
import * as aesjs from "aes-js";
import * as Crypto from "expo-crypto";

import { api } from "@/src/api";
import { storage } from "@/src/utils/storage";

const REGISTRY_KEY = "draft_registry";
const DRAFT_PREFIX = "draft_";
const KEY_NAME = "draft_key";

async function getKeyHex(): Promise<string> {
  const existing = await storage.secureGet(KEY_NAME, null);
  if (existing) return existing;
  const bytes = await Crypto.getRandomBytesAsync(32);
  const hex = Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
  await storage.secureSet(KEY_NAME, hex);
  return hex;
}

function encryptJson(obj: any, keyHex: string): string {
  const keyBytes = aesjs.utils.hex.toBytes(keyHex);
  const textBytes = aesjs.utils.utf8.toBytes(JSON.stringify(obj));
  const ctr = new aesjs.ModeOfOperation.ctr(keyBytes, new aesjs.Counter(7));
  return aesjs.utils.hex.fromBytes(ctr.encrypt(textBytes));
}

function decryptJson(cipherHex: string, keyHex: string): any {
  const keyBytes = aesjs.utils.hex.toBytes(keyHex);
  const dataBytes = aesjs.utils.hex.toBytes(cipherHex);
  const ctr = new aesjs.ModeOfOperation.ctr(keyBytes, new aesjs.Counter(7));
  return JSON.parse(aesjs.utils.utf8.fromBytes(ctr.decrypt(dataBytes)));
}

async function registry(): Promise<string[]> {
  const raw = (await storage.getItem(REGISTRY_KEY, "[]")) ?? "[]";
  try {
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

async function setRegistry(ids: string[]) {
  await storage.setItem(REGISTRY_KEY, JSON.stringify(ids));
}

export type LocalDraft = {
  caseId: string;
  data: Record<string, any>;
  gps: Record<string, any>;
  declaration: boolean;
  savedAt: string;
  synced: boolean;
};

export async function saveLocalDraft(caseId: string, draft: Omit<LocalDraft, "caseId" | "savedAt" | "synced">) {
  const keyHex = await getKeyHex();
  const payload: LocalDraft = { ...draft, caseId, savedAt: new Date().toISOString(), synced: false };
  await storage.setItem(`${DRAFT_PREFIX}${caseId}`, encryptJson(payload, keyHex));
  const ids = await registry();
  if (!ids.includes(caseId)) await setRegistry([...ids, caseId]);
  return payload;
}

export async function markDraftSynced(caseId: string) {
  const keyHex = await getKeyHex();
  const raw = await storage.getItem(`${DRAFT_PREFIX}${caseId}`, null);
  if (!raw) return;
  try {
    const draft = decryptJson(raw, keyHex);
    await storage.setItem(`${DRAFT_PREFIX}${caseId}`, encryptJson({ ...draft, synced: true }, keyHex));
  } catch {
    // corrupt draft — ignore
  }
}

export async function readLocalDraft(caseId: string): Promise<LocalDraft | null> {
  const keyHex = await getKeyHex();
  const raw = await storage.getItem(`${DRAFT_PREFIX}${caseId}`, null);
  if (!raw) return null;
  try {
    return decryptJson(raw, keyHex);
  } catch {
    return null;
  }
}

export async function listUnsyncedDrafts(): Promise<LocalDraft[]> {
  const keyHex = await getKeyHex();
  const ids = await registry();
  const out: LocalDraft[] = [];
  for (const id of ids) {
    const raw = await storage.getItem(`${DRAFT_PREFIX}${id}`, null);
    if (!raw) continue;
    try {
      const d = decryptJson(raw, keyHex);
      if (!d.synced) out.push(d);
    } catch {
      // skip corrupt
    }
  }
  return out;
}

// Push every unsynced local draft to the server. Returns number synced.
export async function syncAllDrafts(): Promise<number> {
  const drafts = await listUnsyncedDrafts();
  let n = 0;
  for (const d of drafts) {
    try {
      await api(`/reports/case/${d.caseId}/draft`, {
        method: "PUT",
        body: { data: d.data, gps: d.gps, declaration: d.declaration, offline_synced: true },
      });
      await markDraftSynced(d.caseId);
      n += 1;
    } catch (e: any) {
      if (e?.status === 403 || e?.status === 400) {
        // case no longer editable — drop from queue
        await markDraftSynced(d.caseId);
      }
    }
  }
  return n;
}

export function pendingCount(): Promise<number> {
  return listUnsyncedDrafts().then((d) => d.length);
}
