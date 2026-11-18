"""Evidence upload (private object storage) and authenticated file access."""
import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

import core
import security
import geocoding
import r2_storage
import report_cache
import storage_service
import watermark
from cases_routes import can_access_case, get_case_or_404, tl
from report_config import config_for

router = APIRouter()
logger = logging.getLogger(__name__)


STALE_FIX_S = 120  # a GPS fix older than the shutter press by more than this is flagged as stale
GPS_STATUSES = ("ok", "poor_accuracy", "denied", "services_disabled", "unavailable", "timeout")


def _parse_device_time(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "captured_at must be an ISO-8601 timestamp")
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


MAX_UPLOAD = 10 * 1024 * 1024


@router.post("/evidence/upload")
async def upload_evidence(request: Request, file: UploadFile = File(...),
                          case_id: str = Form(...), slot: str = Form("document"),
                          kind: str = Form("photo"), captured_at: str | None = Form(None),
                          lat: float | None = Form(None), lon: float | None = Form(None),
                          accuracy: float | None = Form(None), device_id: str | None = Form(None),
                          gps_status: str | None = Form(None), mocked: str | None = Form(None),
                          gps_fix_at: str | None = Form(None), location_reason: str | None = Form(None),
                          upload_id: str | None = Form(None), gps_source: str | None = Form(None),
                          client_build: str | None = Form(None), client_file_size: str | None = Form(None),
                          client_format: str | None = Form(None),
                          ctx=Depends(security.staff)):
    """Upload through the API (web dashboard, older app builds, and the fallback when direct upload is unavailable)."""
    async def read_data() -> bytes:
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(400, "File too large (max 10MB)")
        return data

    return await _ingest(request, ctx, read_data, case_id=case_id, filename=file.filename, declared_type=file.content_type,
                         slot=slot, kind=kind, captured_at=captured_at, lat=lat, lon=lon, accuracy=accuracy,
                         device_id=device_id, gps_status=gps_status, mocked=mocked, gps_fix_at=gps_fix_at,
                         location_reason=location_reason, upload_id=upload_id, gps_source=gps_source,
                         client_build=client_build, client_file_size=client_file_size, client_format=client_format)


async def _ingest(request: Request, ctx: dict, read_data, *, case_id: str, filename: str | None, declared_type: str | None,
                  slot: str, kind: str, captured_at: str | None, lat: float | None, lon: float | None,
                  accuracy: float | None, device_id: str | None, gps_status: str | None, mocked: str | None,
                  gps_fix_at: str | None, location_reason: str | None, upload_id: str | None, gps_source: str | None,
                  client_build: str | None, client_file_size: str | None, client_format: str | None):
    """Validate, watermark, store and record one evidence file. `read_data()` returns the received bytes (from the
    multipart body, or from the R2 incoming object for a direct upload); it is called only after the checks that do
    not need the file, exactly as before."""
    t0 = time.monotonic()
    received = core.now()  # server receipt time, recorded separately from the device capture time
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    if kind == "photo" and case.get("status") not in ("new", "assigned", "in_progress", "returned"):
        raise HTTPException(400, "Photos can only be added before submission or when returned")
    upload_id = (upload_id or "").strip()[:64] or None
    if upload_id:  # idempotent retry from the app's pending-upload queue: never create a duplicate
        existing = await core.db.evidence.find_one({"upload_id": upload_id, "case_id": str(case["_id"])})
        if existing:
            return core.clean(existing)

    settings = await core.get_settings()
    config = config_for(case["report_type"], settings)
    if kind == "photo":
        slot_keys = {s_["key"] for s_ in config.get("photo_slots", [])}
        if slot_keys and slot not in slot_keys:
            raise HTTPException(400, "Unknown photo slot for this verification type")

    # ---- capture time (device clock at shutter) vs server receipt
    captured = _parse_device_time(captured_at)
    captured_source = "device" if captured else "server_receipt"
    captured = captured or received
    skew_s = (captured - received).total_seconds()
    flags_add = []
    too_far_ahead = skew_s > float(settings.get("flag_clock_skew_min", 5)) * 60
    too_old = -skew_s > float(settings.get("flag_capture_max_age_h", 72)) * 3600
    if too_far_ahead or too_old:
        flags_add.append("device_clock_suspect")

    # ---- GPS status, mock flag, distance from the case reference location
    has_fix = lat is not None and lon is not None
    if has_fix and not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(400, "Invalid GPS coordinates")
    is_mocked = str(mocked).lower() in ("1", "true", "yes")
    acc_limit = float(settings.get("flag_accuracy_m", 150))
    if has_fix:
        status = "poor_accuracy" if (accuracy is None or accuracy > acc_limit) else "ok"
    else:
        status = gps_status if gps_status in GPS_STATUSES and gps_status not in ("ok", "poor_accuracy") else "unavailable"
    reason = (location_reason or "").strip()[:500] or None
    needs_gps = kind == "photo" and bool(config.get("requires_gps"))
    distance_m, allowed_m = None, float(settings.get("flag_distance_m", 500))
    location_check = None
    if needs_gps:
        if is_mocked:
            flags_add.append("possible_mock_location")
        if status == "poor_accuracy":
            flags_add.append("low_gps_accuracy")
        if not has_fix:
            if not reason:
                raise HTTPException(422, detail={
                    "code": "gps_reason_required", "gps_status": status,
                    "message": "No GPS fix for this photo. Give a reason; it will be flagged for supervisor review."})
            flags_add.append("photo_without_gps")
        else:
            location_check = core.assess_location(case.get("assigned_lat"), case.get("assigned_lon"),
                                                  case.get("location_precision"), lat, lon, accuracy, allowed_m, acc_limit)
            distance_m = location_check["distance_m"]
            if location_check["status"] == "outside":
                if not reason:
                    raise HTTPException(422, detail={
                        "code": "outside_allowed_distance", "distance_m": distance_m, "allowed_m": allowed_m,
                        "accuracy_m": accuracy, "location_precision": case.get("location_precision"),
                        "margin_m": location_check["margin_m"], "message": location_check["explanation"]})
                flags_add.append("photo_far_from_assigned")
            elif location_check["status"] == "uncertain":
                flags_add.append("location_uncertain")
            elif location_check["status"] == "no_reference":
                flags_add.append("no_reference_location")
                # say exactly which case-location data is missing (never "checked" when it was not)
                problem = geocoding.location_problem(case)
                if problem:
                    location_check["explanation"] = f"The distance cannot be checked: {problem}"
                location_check["case_location_status"] = case.get("location_status")
            # what the photo was compared with: the case's assigned/reference location (never the photo's own address)
            location_check["reference"] = {"address": case.get("assigned_address"), "lat": case.get("assigned_lat"),
                                           "lon": case.get("assigned_lon"), "precision": case.get("location_precision"),
                                           "source": case.get("location_source"), "status": case.get("location_status")}
        fix_at = _parse_device_time(gps_fix_at) if has_fix and gps_fix_at else None
        if fix_at and (captured - fix_at).total_seconds() > STALE_FIX_S:
            flags_add.append("stale_gps_fix")  # the position is older than the shutter press by more than allowed

    t_auth = time.monotonic()
    data = await read_data()
    is_photo = kind == "photo"
    img = None
    if is_photo:
        # Validate by fully decoding the image (never by filename / client MIME type).
        try:
            img, ext = await asyncio.to_thread(watermark.decode_photo, data)
        except watermark.InvalidImage as exc:
            logger.warning("evidence upload rejected: not a decodable photo (case %s, %d bytes, declared %s, first bytes %s, "
                           "client_build %s, client_size %s, client_format %s): %s",
                           case["_id"], len(data), declared_type, data[:12].hex(), (client_build or "none")[:60],
                           (client_file_size or "-")[:12], (client_format or "-")[:10], exc)
            raise HTTPException(400, "Unsupported file type. Photos must be JPEG/PNG/WebP/HEIC; documents may also be PDF.")
    else:
        ext = storage_service.detect_type(data)
        if ext not in storage_service.ALL_TYPES:
            raise HTTPException(400, "Unsupported file type. Photos must be JPEG/PNG/WebP/HEIC; documents may also be PDF.")
    sha = hashlib.sha256(data).hexdigest()  # checksum of the ORIGINAL bytes received from the device
    t_valid = time.monotonic()

    original, wm_meta, photo_address = None, None, None
    upload_bytes, upload_ext = data, ext
    if is_photo:
        # Address printed on the photo = reverse geocode of the coordinates captured at the shutter (never the case address).
        photo_address = await asyncio.to_thread(geocoding.reverse_geocode, lat, lon) if has_fix else \
            {"text": None, "status": "unavailable", "precision": None, "reason": "no_gps"}
        slot_label = next((s_["label"] for s_ in config.get("photo_slots", []) if s_["key"] == slot), slot)
        lines = watermark.watermark_lines(captured, lat if has_fix else None, lon if has_fix else None, photo_address, slot, slot_label)
        upload_bytes, layout = await asyncio.to_thread(watermark.render_watermark, img, lines, slot)
        logger.info("evidence watermark: case %s slot %s original %s %d bytes %dx%d -> watermarked jpg %d bytes %dx%d (address %s)",
                    case["_id"], slot, ext, len(data), img.size[0], img.size[1], len(upload_bytes), layout["size"][0],
                    layout["size"][1], photo_address.get("status"))
        upload_ext = "jpg"
        wm_meta = {"sha256": hashlib.sha256(upload_bytes).hexdigest(), "size": len(upload_bytes), "lines": lines,
                   "printed_lines": layout["printed_lines"], "box": layout["box"], "image_size": layout["size"],
                   "band": layout["band"], "format": "jpg"}
    path = storage_service.object_path(str(case["_id"]), upload_ext, "evidence")
    orig_path = storage_service.object_path(str(case["_id"]), ext, "evidence") if is_photo else None
    meta = {"case-id": str(case["_id"]), "slot": slot, "original-filename": filename or f"{slot}.{ext}"}
    orig_stored = None
    try:
        if is_photo:  # keep the untouched camera original as a separate private object
            orig_stored = await storage_service.put_object_async(orig_path, data, storage_service.mime_for(ext),
                                                                 {**meta, "variant": "original"})
            original = {"storage_path": orig_path, "storage_provider": orig_stored["provider"], "sha256": sha,
                        "size": len(data), "format": ext, "storage": orig_stored}
        try:
            stored = await storage_service.put_object_async(path, upload_bytes, storage_service.mime_for(upload_ext),
                                                            {**meta, "variant": "watermarked" if is_photo else "document"})
        except Exception:
            if orig_stored:
                await storage_service.delete_object_async(orig_path, orig_stored["provider"])
            raise
    except storage_service.StorageNotConfigured:
        logger.error("evidence upload: storage not configured (case %s)", case["_id"])
        raise HTTPException(503, "File storage is not configured on the server")
    except Exception as exc:
        logger.error("evidence upload: storage failed after %.2fs (case %s, %s, %d bytes): %s",
                     time.monotonic() - t_valid, case["_id"], ext, len(data), type(exc).__name__)
        raise HTTPException(502, "Upload to file storage failed. Please retry.")
    t_store = time.monotonic()

    flagged_location = "photo_far_from_assigned" in flags_add or "photo_without_gps" in flags_add
    doc = {
        "case_id": str(case["_id"]), "slot": slot, "kind": kind, "storage_path": path,
        "filename": filename or f"{slot}.{ext}", "sha256": sha,
        "gps": {"lat": lat if has_fix else None, "lon": lon if has_fix else None,
                "accuracy": accuracy if has_fix else None, "status": status, "mocked": is_mocked, "fix_at": gps_fix_at,
                "source": "".join(ch for ch in (gps_source or "device") if ch.isalnum() or ch == "_")[:20] if has_fix else None},
        "location_check": location_check,
        "distance_m": distance_m, "allowed_distance_m": allowed_m if distance_m is not None else None,
        "location_reason": reason if flagged_location else None,
        "captured_at": captured, "captured_at_source": captured_source, "received_at": received,
        "clock_skew_s": round(skew_s, 1), "uploaded_by": str(ctx["user"]["_id"]),
        "uploaded_by_name": ctx["user"]["name"], "device_id": device_id,
        "mime": storage_service.mime_for(upload_ext), "size": len(upload_bytes), "created_at": received,
        "original": original, "watermark": wm_meta, "photo_address": photo_address,
        "client_build": (client_build or None) and client_build[:60],
        "storage_provider": stored["provider"], "storage": stored,
        "verification_status": stored.get("verification_status"), "upload_status": "uploaded",
        "agent_id": case.get("assigned_agent_id"), "uploaded_at": core.now(), "flags": sorted(set(flags_add)),
    }
    if upload_id:
        doc["upload_id"] = upload_id
    try:
        res = await core.db.evidence.insert_one(doc)
    except DuplicateKeyError:  # a concurrent retry with the same upload_id won the race
        await storage_service.delete_object_async(path, stored["provider"])
        if orig_stored:
            await storage_service.delete_object_async(orig_path, orig_stored["provider"])
        return core.clean(await core.db.evidence.find_one({"upload_id": upload_id}))

    # Duplicate photo detection across cases / same case reuse
    dup_q = {"sha256": sha, "_id": {"$ne": res.inserted_id}, "kind": "photo"}
    other = await core.db.evidence.find_one(dup_q)
    if other:
        flags_add.append("duplicate_photo_cross_case" if other.get("case_id") != str(case["_id"]) else "same_evidence_reused")
    if flags_add:
        await core.db.cases.update_one({"_id": case["_id"]}, {"$addToSet": {"flags": {"$each": sorted(set(flags_add))}}})

    await core.db.cases.update_one({"_id": case["_id"]}, {"$push": {"timeline": tl(
        "photo_captured", ctx["user"], {"slot": slot, "filename": doc["filename"], "lat": doc["gps"]["lat"],
                                        "lon": doc["gps"]["lon"], "accuracy": doc["gps"]["accuracy"],
                                        "gps_status": status, "distance_m": distance_m, "captured_at": captured,
                                        "flags": sorted(set(flags_add))})}})
    await core.audit(ctx["user"], "evidence_uploaded", "case", str(case["_id"]),
                     {"slot": slot, "sha256": sha[:12], "flags": sorted(set(flags_add)), "gps_status": status}, request)
    doc["_id"] = res.inserted_id
    logger.info("evidence upload ok: case %s evidence %s received %s %d bytes (client_build %s, client_size %s) stored %s %d bytes"
                " | auth %.2fs, read+validate %.2fs, storage %.2fs, db %.2fs",
                case["_id"], res.inserted_id, ext, len(data), (client_build or "none")[:60], (client_file_size or "-")[:12],
                upload_ext, len(upload_bytes), t_auth - t0, t_valid - t_auth, t_store - t_valid, time.monotonic() - t_store)
    return core.clean(doc)


# ---------------------------------------------------------------- direct upload to R2 (phone -> R2, then verify)
DIRECT_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic",
                "image/heif": "heic", "application/pdf": "pdf"}
PENDING_UPLOAD_TTL_H = 48  # authorisations older than this are dropped (an R2 lifecycle rule also clears incoming/)


class UploadUrlIn(BaseModel):
    case_id: str
    slot: str = "document"
    kind: str = "photo"
    upload_id: str = Field(min_length=8, max_length=64)
    size: int = Field(gt=0, le=MAX_UPLOAD)
    sha256: str = Field(min_length=64, max_length=64, pattern="^[0-9a-fA-F]{64}$")
    content_type: str
    filename: str | None = Field(default=None, max_length=200)


def _incoming_key(case_id: str, upload_id: str, ext: str) -> str:
    safe_up = "".join(ch for ch in upload_id if ch.isalnum() or ch in "-_")
    folder = storage_service.object_path(case_id, ext, "incoming").rsplit("/", 1)[0]
    return f"{folder}/{safe_up}.{ext}"


@router.post("/evidence/upload-url")
async def evidence_upload_url(body: UploadUrlIn, ctx=Depends(security.staff)):
    """Step 1 of a direct upload: check the user may add this evidence, then issue a short-lived presigned PUT for ONE
    object. Size, type and SHA-256 are signed into the URL, so R2 refuses any other file. The app falls back to
    POST /evidence/upload when this answers 409 direct_upload_unavailable."""
    if (os.environ.get("DIRECT_UPLOAD_ENABLED", "true").strip().lower() != "true"
            or storage_service.write_provider() != storage_service.R2 or not r2_storage.configured()):
        raise HTTPException(409, detail={"code": "direct_upload_unavailable", "message": "Direct upload is not enabled"})
    case = await get_case_or_404(body.case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    if body.kind == "photo" and case.get("status") not in ("new", "assigned", "in_progress", "returned"):
        raise HTTPException(400, "Photos can only be added before submission or when returned")
    if body.kind == "photo":
        config = config_for(case["report_type"], await core.get_settings())
        slot_keys = {s_["key"] for s_ in config.get("photo_slots", [])}
        if slot_keys and body.slot not in slot_keys:
            raise HTTPException(400, "Unknown photo slot for this verification type")
    ctype = body.content_type.split(";")[0].strip().lower()
    ext = DIRECT_TYPES.get(ctype)
    if not ext or (body.kind == "photo" and ext == "pdf"):
        raise HTTPException(400, "Unsupported file type. Photos must be JPEG/PNG/WebP/HEIC; documents may also be PDF.")
    case_id, uid, sha = str(case["_id"]), body.upload_id.strip(), body.sha256.lower()
    existing = await core.db.evidence.find_one({"upload_id": uid, "case_id": case_id})
    if existing:  # already stored (an earlier attempt completed): nothing to upload
        return {"already_uploaded": True, "evidence": core.clean(existing)}
    user_id = str(ctx["user"]["_id"])
    pending = await core.db.pending_uploads.find_one({"upload_id": uid})
    if pending and (pending["user_id"] != user_id or pending["case_id"] != case_id or pending["sha256"] != sha
                    or pending["size"] != body.size):
        raise HTTPException(409, detail={"code": "upload_id_conflict", "message": "This upload id is already in use"})
    key = pending["key"] if pending else _incoming_key(case_id, uid, ext)
    if not pending:
        try:
            await core.db.pending_uploads.insert_one({
                "upload_id": uid, "case_id": case_id, "user_id": user_id, "key": key, "size": body.size, "sha256": sha,
                "content_type": ctype, "kind": body.kind, "slot": body.slot, "filename": body.filename,
                "created_at": core.now(), "expires_at": core.now() + timedelta(hours=PENDING_UPLOAD_TTL_H)})
        except DuplicateKeyError:
            raise HTTPException(409, detail={"code": "upload_id_conflict", "message": "Upload already being authorised; retry"})
    signed = await asyncio.to_thread(r2_storage.presign_put, key, ctype, body.size, sha)
    return {"already_uploaded": False, "upload_id": uid, **signed}


@router.post("/evidence/complete")
async def complete_direct_upload(request: Request, upload_id: str = Form(...), captured_at: str | None = Form(None),
                                 lat: float | None = Form(None), lon: float | None = Form(None),
                                 accuracy: float | None = Form(None), device_id: str | None = Form(None),
                                 gps_status: str | None = Form(None), mocked: str | None = Form(None),
                                 gps_fix_at: str | None = Form(None), location_reason: str | None = Form(None),
                                 gps_source: str | None = Form(None), client_build: str | None = Form(None),
                                 client_file_size: str | None = Form(None), client_format: str | None = Form(None),
                                 ctx=Depends(security.staff)):
    """Step 3 of a direct upload: verify the object the phone PUT to R2 (size + SHA-256 + real file type), then
    watermark, store and record it exactly like a normal upload. Safe to retry: a completed upload_id returns the
    existing evidence record."""
    uid = upload_id.strip()[:64]
    p = await core.db.pending_uploads.find_one({"upload_id": uid})
    if not p:
        done = await core.db.evidence.find_one({"upload_id": uid})
        if done:
            case = await get_case_or_404(done["case_id"])
            if not await can_access_case(ctx["user"], case):
                raise HTTPException(403, "Not allowed")
            return core.clean(done)
        raise HTTPException(404, detail={"code": "upload_not_authorised", "message": "Request an upload URL first"})
    if p["user_id"] != str(ctx["user"]["_id"]):
        raise HTTPException(403, "This upload belongs to another user")

    async def read_data() -> bytes:
        head = await asyncio.to_thread(r2_storage.head_object, p["key"])
        if not head:
            raise HTTPException(409, detail={"code": "upload_missing", "message": "The file has not reached storage yet"})
        if head["size"] != p["size"]:
            await asyncio.to_thread(r2_storage.delete_object, p["key"])
            raise HTTPException(400, detail={"code": "size_mismatch", "message": "Uploaded file size does not match"})
        data = await asyncio.to_thread(r2_storage.get_object, p["key"])
        if hashlib.sha256(data).hexdigest() != p["sha256"]:
            await asyncio.to_thread(r2_storage.delete_object, p["key"])
            raise HTTPException(400, detail={"code": "checksum_mismatch", "message": "Uploaded file is corrupted; upload again"})
        return data

    result = await _ingest(request, ctx, read_data, case_id=p["case_id"], filename=p.get("filename"),
                           declared_type=p.get("content_type"), slot=p["slot"], kind=p["kind"], captured_at=captured_at,
                           lat=lat, lon=lon, accuracy=accuracy, device_id=device_id, gps_status=gps_status, mocked=mocked,
                           gps_fix_at=gps_fix_at, location_reason=location_reason, upload_id=uid, gps_source=gps_source,
                           client_build=client_build, client_file_size=client_file_size, client_format=client_format)
    # The verified bytes now live in the final private objects; drop the temporary one (best effort: lifecycle rule).
    try:
        await asyncio.to_thread(r2_storage.delete_object, p["key"])
    except Exception as exc:
        logger.warning("could not delete incoming object %s: %s", p["key"], type(exc).__name__)
    await core.db.pending_uploads.delete_one({"_id": p["_id"]})
    return result


@router.get("/files/{evidence_id}")
async def get_file(evidence_id: str, request: Request, token: str | None = None, variant: str | None = None,
                   creds=Depends(security.bearer)):
    ctx = await security.load_session_ctx(request, creds, token)
    try:
        e = await core.db.evidence.find_one({"_id": ObjectId(evidence_id)})
    except Exception:
        raise HTTPException(404, "File not found")
    if not e:
        raise HTTPException(404, "File not found")
    case = await core.db.cases.find_one({"_id": ObjectId(e["case_id"])})
    if not case or not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    if case.get("deleted_at") and ctx["user"]["role"] != "super_admin":
        # evidence of a soft-deleted case is kept for audit/investigation, retrievable by the Super Admin only
        raise HTTPException(404, "File not found")
    if not storage_service.readable(e.get("storage_provider")) or not e.get("storage_path"):
        # Legacy Emergent-stored (or purged) evidence: metadata is kept, the file is not retrievable here.
        raise HTTPException(404, "File not available")
    target = e["storage_path"]
    if variant == "original":
        if ctx["user"]["role"] not in ("super_admin", "supervisor"):
            raise HTTPException(403, "Only supervisors and Super Admin can download the unwatermarked original")
        if not (e.get("original") or {}).get("storage_path"):
            raise HTTPException(404, "No separate original stored for this evidence")
        target = e["original"]["storage_path"]
    try:
        if variant == "original":
            orig = e["original"]
            data, mime = await storage_service.get_object_async(target, orig.get("storage_provider") or e.get("storage_provider"))
        else:  # stored (watermarked) file: checksum-verified and cached in memory for repeat views
            data, mime = await report_cache.evidence_bytes(core.clean(dict(e))), e.get("mime") or storage_service.mime_for(
                target.rpartition(".")[2])
    except Exception:
        raise HTTPException(404, "File not available")
    await core.audit(ctx["user"], "evidence_downloaded", "evidence", evidence_id,
                     {"case_id": e["case_id"], "variant": "original" if variant == "original" else "watermarked"}, request)
    return Response(content=data, media_type=mime, headers=safe_file_headers(e.get("filename"), mime))


def safe_file_headers(filename: str | None, mime: str) -> dict:
    name = "".join(ch for ch in (filename or "file") if ch.isalnum() or ch in "._- ")[:100] or "file"
    disposition = "inline" if mime.startswith("image/") or mime == "application/pdf" else "attachment"
    return {"Content-Disposition": f'{disposition}; filename="{name}"', "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300"}


@router.get("/cases/{case_id}/evidence")
async def list_evidence(case_id: str, ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    items = [core.clean(e) async for e in core.db.evidence.find({"case_id": str(case["_id"])}).sort("created_at", -1)]
    return {"items": items}
