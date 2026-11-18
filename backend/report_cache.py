"""Fast, safe retrieval of evidence photos and reuse of generated Word/PDF reports.

* Evidence files are immutable (each upload gets a new random storage path and R2 writes use
  If-None-Match, so an object is never overwritten), and each
  evidence record stores the SHA-256 of the stored file. Downloaded bytes are checked against that checksum before
  use, then kept in a bounded in-memory cache (never written to disk, never exposed as a URL).
* Photos of a case are fetched in parallel (bounded), not one after another.
* A generated report is cached under a hash of everything that goes into it (case, report data, evidence records,
  call logs, settings, export format, the viewer's masking level and the builder version). Any change to any of
  those gives a new key, so a stale report can never be served; nothing has to be "invalidated" by hand.
* Callers must have checked the user's access to the case BEFORE calling anything here.
"""
import asyncio
import hashlib
import json
import logging
import threading
from collections import OrderedDict

import os

import storage_service

logger = logging.getLogger(__name__)

BUILDER_VERSION = "vee-2"            # vee-2: red + black VEE content. Bump when the report layout code changes, so old cached reports are not reused
# In-memory only. Set lower on small hosts (Railway Free has ~0.5 GB RAM): IMAGE_CACHE_MB / REPORT_CACHE_MB.
IMAGE_CACHE_BYTES = int(os.environ.get("IMAGE_CACHE_MB", "200")) * 1024 * 1024
REPORT_CACHE_BYTES = int(os.environ.get("REPORT_CACHE_MB", "150")) * 1024 * 1024
FETCH_CONCURRENCY = 6


class _LRU:
    def __init__(self, max_bytes: int):
        self.max_bytes, self.size, self.items, self.lock = max_bytes, 0, OrderedDict(), threading.Lock()

    def get(self, key):
        with self.lock:
            v = self.items.get(key)
            if v is not None:
                self.items.move_to_end(key)
            return v

    def put(self, key, value: bytes):
        if len(value) > self.max_bytes // 4:
            return
        with self.lock:
            old = self.items.pop(key, None)
            if old is not None:
                self.size -= len(old)
            self.items[key] = value
            self.size += len(value)
            while self.size > self.max_bytes and self.items:
                _, ev = self.items.popitem(last=False)
                self.size -= len(ev)

    def clear(self):
        with self.lock:
            self.items.clear()
            self.size = 0


_images = _LRU(IMAGE_CACHE_BYTES)
_reports = _LRU(REPORT_CACHE_BYTES)
_fetch_sem: asyncio.Semaphore | None = None


class IntegrityError(RuntimeError):
    pass


def expected_sha256(e: dict) -> str | None:
    """Checksum of the stored (watermarked) file: watermark.sha256 for photos, else the upload's own sha256."""
    wm = e.get("watermark") or {}
    return wm.get("sha256") or (e.get("sha256") if not wm else None)


async def evidence_bytes(e: dict) -> bytes:
    """The stored file of one evidence record, checksum-verified. Raises on any problem."""
    path = e.get("storage_path")
    provider = e.get("storage_provider")
    if not storage_service.readable(provider) or not path:
        raise FileNotFoundError("not stored in a readable provider")
    cached = _images.get(path)  # keys are identical across providers for migrated files and the bytes are checksum-equal
    if cached is not None:
        return cached
    global _fetch_sem
    if _fetch_sem is None:
        _fetch_sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    async with _fetch_sem:
        data, _ = await storage_service.get_object_async(path, provider)
    want = expected_sha256(e)
    if want and hashlib.sha256(data).hexdigest() != want:
        logger.error("evidence %s: stored file checksum mismatch; not used", e.get("id") or e.get("_id"))
        raise IntegrityError("checksum mismatch")
    _images.put(path, data)
    return data


async def load_case_photos(case: dict, evidence: list) -> dict:
    """{evidence_id: bytes} for this case's photo evidence, fetched in parallel. A photo that cannot be retrieved
    (or fails its checksum) is left out, so the report shows a missing-evidence notice instead of a wrong image."""
    cid = str(case["_id"])
    photos = [e for e in evidence if e.get("kind") == "photo" and str(e.get("case_id")) == cid]  # association check
    results = await asyncio.gather(*(evidence_bytes(e) for e in photos), return_exceptions=True)
    out = {}
    for e, r in zip(photos, results):
        if isinstance(r, Exception):
            logger.warning("report photo unavailable: case %s evidence %s (%s)", cid, e.get("id"), type(r).__name__)
        else:
            out[str(e.get("id") or e.get("_id"))] = r
    return out


_VOLATILE_CASE_KEYS = {"timeline", "updated_at", "status", "notifications", "last_viewed_at"}


def report_key(fmt: str, case: dict, report: dict, evidence: list, call_logs: list, settings: dict,
               masked: bool, extra: str = "") -> str:
    """Content hash of every input of a generated report."""
    payload = {
        "v": BUILDER_VERSION, "header": header_fingerprint(), "fmt": fmt, "masked": masked, "extra": extra,
        "case": {k: v for k, v in case.items() if k not in _VOLATILE_CASE_KEYS},
        "report": report,
        "evidence": [{k: e.get(k) for k in ("id", "_id", "slot", "kind", "case_id", "storage_path", "sha256", "captured_at",
                                             "gps", "photo_address", "filename")} | {"wm": (e.get("watermark") or {}).get("sha256")}
                     for e in evidence],
        "calls": call_logs, "settings": settings,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def header_fingerprint() -> str:
    """SHA-256 of the report header image in use, so swapping the header artwork rebuilds cached reports."""
    try:
        from exporters import report_header_image
        img = report_header_image()
        return hashlib.sha256(img.read_bytes()).hexdigest()[:16] if img else "none"
    except Exception:
        return "unknown"


def cached_report(key: str) -> bytes | None:
    return _reports.get(key)


def store_report(key: str, content: bytes):
    _reports.put(key, content)


def clear():
    _images.clear()
    _reports.clear()
