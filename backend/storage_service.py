"""Private media storage: Cloudflare R2 only.

* Every file (evidence photos, originals, PDFs, request documents, backups) is stored in the private R2 bucket via
  r2_storage. Cloudinary was retired on 18-Nov-2026 after all test data was cleared; no record refers to it.
* Each record keeps `storage_provider: "r2"`. A record with any other provider value (or none, e.g. purged evidence)
  is not readable, and callers answer "file not available".
* R2 keys are used only here, on the server. Clients never receive a credential or a non-expiring storage URL; at
  most a short-lived presigned URL for one object, issued after an access check.
"""
import asyncio
import logging
import os
import uuid

import r2_storage

logger = logging.getLogger(__name__)

R2 = "r2"
READABLE_PROVIDERS = (R2,)
STORAGE_APP = "checksphere"
MEDIA_ENV = (os.environ.get("MEDIA_FOLDER_ENV") or os.environ.get("APP_ENV") or "dev").strip() or "dev"

# Allowed file types, detected from the file's leading bytes (the client's filename/MIME is not trusted).
IMAGE_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "heic": "image/heic"}
DOC_TYPES = {"pdf": "application/pdf"}
ALL_TYPES = {**IMAGE_TYPES, **DOC_TYPES}


class StorageNotConfigured(RuntimeError):
    pass


def write_provider() -> str:
    """Where new files go. R2 is the only storage provider."""
    want = (os.environ.get("STORAGE_PROVIDER") or R2).strip().lower()
    if want != R2:
        logger.warning("STORAGE_PROVIDER=%r is not supported; using r2", want)
    return R2


def readable(provider: str | None) -> bool:
    return provider in READABLE_PROVIDERS


def init_storage() -> dict:
    """Validate the R2 configuration and credentials (one cheap HEAD bucket call)."""
    status = {"write_provider": R2}
    try:
        r2_storage.init()
        status[R2] = "ok"
    except Exception as exc:
        status[R2] = f"error: {type(exc).__name__}"
    return status


async def init_storage_async():
    return await asyncio.to_thread(init_storage)


# ---------------------------------------------------------------- validation
def detect_type(data: bytes) -> str | None:
    """Return a safe extension for the file content, or None if it is not an allowed type."""
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc", b"heim", b"heis"):
        return "heic"
    if head.startswith(b"%PDF-"):
        return "pdf"
    return None


def mime_for(ext: str) -> str:
    return ALL_TYPES.get(ext, "application/octet-stream")


def object_path(owner_id: str, ext: str, kind: str = "evidence") -> str:
    """R2 object key. Contains only database ids — never personal data."""
    safe_owner = "".join(ch for ch in str(owner_id) if ch.isalnum() or ch in "-_")
    safe_kind = kind if kind in ("evidence", "requests", "backups", "uploads", "incoming") else "evidence"
    safe_ext = ext if ext in ALL_TYPES else "bin"
    return f"{STORAGE_APP}/{MEDIA_ENV}/{safe_kind}/{safe_owner}/{uuid.uuid4().hex}.{safe_ext}"


# ---------------------------------------------------------------- operations
def _check_provider(provider: str | None) -> str:
    if not readable(provider):
        raise FileNotFoundError(f"storage provider {provider!r} is not readable")
    return provider


def put_object(path: str, data: bytes, content_type: str | None = None, metadata: dict | None = None) -> dict:
    """Store new bytes in R2. The result carries "provider": save it on the record."""
    ctype = content_type or mime_for(path.rpartition(".")[2])
    try:
        return r2_storage.put_object(path, data, ctype, metadata)
    except r2_storage.R2NotConfigured as exc:
        raise StorageNotConfigured(str(exc)) from exc


def get_object(path: str, provider: str | None) -> tuple[bytes, str]:
    _check_provider(provider)
    return r2_storage.get_object(path), mime_for(path.rpartition(".")[2])


def delete_object(path: str, provider: str | None) -> bool:
    _check_provider(provider)
    return r2_storage.delete_object(path)


async def put_object_async(path: str, data: bytes, content_type: str | None = None, metadata: dict | None = None) -> dict:
    return await asyncio.to_thread(put_object, path, data, content_type, metadata)


async def get_object_async(path: str, provider: str | None) -> tuple[bytes, str]:
    return await asyncio.to_thread(get_object, path, provider)


async def delete_object_async(path: str, provider: str | None) -> bool:
    return await asyncio.to_thread(delete_object, path, provider)
