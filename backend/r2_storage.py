"""Cloudflare R2 object storage (S3-compatible API), private bucket.

Server-side only: the R2 access key never leaves the backend. Clients get, at most, a short-lived presigned URL for ONE
object, issued after the backend has checked the user's role and case access.

Objects are immutable: writes use If-None-Match: * so an existing key is never overwritten, and every write sends the
SHA-256 of the bytes (x-amz-checksum-sha256), which R2 verifies before it stores the object.
"""
import base64
import hashlib
import logging
import os
import time
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

PROVIDER = "r2"
REQUIRED = ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
UPLOAD_URL_TTL = int(os.environ.get("R2_UPLOAD_URL_TTL_SECONDS", "600"))
DOWNLOAD_TTL = int(os.environ.get("DOWNLOAD_LINK_TTL_SECONDS", "60"))

_client = None


class R2NotConfigured(RuntimeError):
    pass


class ObjectExists(RuntimeError):
    """The key is already taken (If-None-Match: * failed)."""


def endpoint() -> str | None:
    ep = (os.environ.get("R2_ENDPOINT") or "").strip().rstrip("/")
    if ep:
        return ep
    acct = (os.environ.get("R2_ACCOUNT_ID") or "").strip()
    return f"https://{acct}.r2.cloudflarestorage.com" if acct else None


def configured() -> bool:
    return all(os.environ.get(k) for k in REQUIRED) and bool(endpoint())


def bucket() -> str:
    return os.environ["R2_BUCKET"]


def client():
    global _client
    if not configured():
        raise R2NotConfigured("Cloudflare R2 is not configured: set R2_ACCOUNT_ID (or R2_ENDPOINT), R2_ACCESS_KEY_ID, "
                              "R2_SECRET_ACCESS_KEY and R2_BUCKET")
    if _client is None:
        _client = boto3.client(
            "s3", endpoint_url=endpoint(), region_name="auto",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          retries={"max_attempts": 4, "mode": "standard"}, connect_timeout=10, read_timeout=60,
                          # we send our own SHA-256 checksum; don't let botocore add CRC32 trailers R2 may not expect
                          request_checksum_calculation="when_required", response_checksum_validation="when_required"))
    return _client


def b64_sha256(hex_digest: str) -> str:
    return base64.b64encode(bytes.fromhex(hex_digest)).decode()


def _meta(metadata: dict | None) -> dict:
    """S3 user metadata must be ASCII; values are URL-encoded and capped."""
    out = {}
    for k, v in (metadata or {}).items():
        if v is None:
            continue
        key = "".join(ch for ch in str(k).lower() if ch.isalnum() or ch == "-")[:40]
        out[key] = quote(str(v), safe=" ._-:/")[:300]
    return out


def init() -> None:
    """Cheap credential + bucket check (HEAD bucket)."""
    client().head_bucket(Bucket=bucket())


def put_object(key: str, data: bytes, content_type: str, metadata: dict | None = None) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    t0 = time.monotonic()
    try:
        res = client().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type,
                                  ContentLength=len(data), ChecksumSHA256=b64_sha256(sha), IfNoneMatch="*",
                                  Metadata=_meta({"sha256": sha, **(metadata or {})}))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in ("PreconditionFailed", "412"):
            raise ObjectExists(key) from exc
        raise
    head = head_object(key)  # confirm what R2 holds
    if not head or head["size"] != len(data):
        raise RuntimeError("R2 upload verification failed (size)")
    logger.info("r2 upload ok in %.2fs: %s (%d bytes)", time.monotonic() - t0, key, len(data))
    return {"provider": PROVIDER, "bucket": bucket(), "key": key, "bytes": len(data), "sha256": sha,
            "etag": (res.get("ETag") or "").strip('"'), "verification_status": "stored"}


def head_object(key: str) -> dict | None:
    try:
        h = client().head_object(Bucket=bucket(), Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return {"size": int(h.get("ContentLength") or 0), "content_type": h.get("ContentType"),
            "etag": (h.get("ETag") or "").strip('"'), "metadata": h.get("Metadata") or {}}


def get_object(key: str) -> bytes:
    t0 = time.monotonic()
    data = client().get_object(Bucket=bucket(), Key=key)["Body"].read()
    logger.info("r2 download ok in %.2fs: %s (%d bytes)", time.monotonic() - t0, key, len(data))
    return data


def delete_object(key: str) -> bool:
    client().delete_object(Bucket=bucket(), Key=key)
    logger.info("r2 delete: %s", key)
    return True


def presign_put(key: str, content_type: str, size: int, sha256_hex: str, ttl: int | None = None) -> dict:
    """Presigned PUT for exactly one object. Content-Type, Content-Length and the SHA-256 checksum are part of the
    signature, so the phone cannot upload a different file (R2 rejects a body whose checksum does not match)."""
    checksum = b64_sha256(sha256_hex)
    expires = int(ttl or UPLOAD_URL_TTL)
    url = client().generate_presigned_url(
        "put_object", ExpiresIn=expires, HttpMethod="PUT",
        Params={"Bucket": bucket(), "Key": key, "ContentType": content_type, "ContentLength": size,
                "ChecksumSHA256": checksum})
    return {"url": url, "method": "PUT", "expires_in": expires,
            "headers": {"Content-Type": content_type, "x-amz-checksum-sha256": checksum}}


def presign_get(key: str, filename: str | None = None, ttl: int | None = None) -> str:
    params = {"Bucket": bucket(), "Key": key}
    if filename:
        safe = "".join(ch for ch in filename if ch.isalnum() or ch in "._- ")[:100] or "file"
        params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
    return client().generate_presigned_url("get_object", Params=params, ExpiresIn=int(ttl or DOWNLOAD_TTL))
