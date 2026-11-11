"""Evidence upload (private object storage) and authenticated file access."""
import hashlib
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

import core
import security
import storage_service
from cases_routes import can_access_case, get_case_or_404, tl

router = APIRouter()


@router.post("/evidence/upload")
async def upload_evidence(request: Request, file: UploadFile = File(...),
                          case_id: str = Form(...), slot: str = Form("document"),
                          kind: str = Form("photo"), captured_at: str | None = Form(None),
                          lat: float | None = Form(None), lon: float | None = Form(None),
                          accuracy: float | None = Form(None), device_id: str | None = Form(None),
                          ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if ctx["user"]["role"] == "agent" and case.get("assigned_agent_id") != str(ctx["user"]["_id"]):
        raise HTTPException(403, "Not allowed")
    if kind == "photo" and case.get("status") not in ("new", "assigned", "in_progress", "returned"):
        raise HTTPException(400, "Photos can only be added before submission or when returned")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 10MB)")
    sha = hashlib.sha256(data).hexdigest()
    ext = (file.filename or "photo.jpg").split(".")[-1].lower()[:5] or "jpg"
    path = storage_service.object_path(str(case["_id"]), ext)
    await storage_service.put_object_async(path, data, file.content_type or "image/jpeg")

    captured = None
    if captured_at:
        try:
            captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except ValueError:
            captured = core.now()
    doc = {
        "case_id": str(case["_id"]), "slot": slot, "kind": kind, "storage_path": path,
        "filename": file.filename or f"{slot}.{ext}", "sha256": sha,
        "gps": {"lat": lat, "lon": lon, "accuracy": accuracy},
        "captured_at": captured or core.now(), "uploaded_by": str(ctx["user"]["_id"]),
        "uploaded_by_name": ctx["user"]["name"], "device_id": device_id,
        "mime": file.content_type or "image/jpeg", "size": len(data), "created_at": core.now(),
    }
    res = await core.db.evidence.insert_one(doc)

    # Duplicate photo detection across cases / same case reuse
    dup_q = {"sha256": sha, "_id": {"$ne": res.inserted_id}, "kind": "photo"}
    other = await core.db.evidence.find_one(dup_q)
    flags_add = []
    if other:
        if other.get("case_id") != str(case["_id"]):
            flags_add.append("duplicate_photo_cross_case")
        else:
            flags_add.append("same_evidence_reused")
        await core.db.cases.update_one({"_id": case["_id"]}, {"$addToSet": {"flags": {"$each": flags_add}}})

    await core.db.cases.update_one({"_id": case["_id"]}, {"$push": {"timeline": tl(
        "photo_captured", ctx["user"], {"slot": slot, "filename": doc["filename"],
                                        "lat": lat, "lon": lon, "accuracy": accuracy})}})
    await core.audit(ctx["user"], "evidence_uploaded", "case", str(case["_id"]),
                     {"slot": slot, "sha256": sha[:12], "duplicates": flags_add}, request)
    doc["_id"] = res.inserted_id
    return core.clean(doc)


@router.get("/files/{evidence_id}")
async def get_file(evidence_id: str, request: Request, token: str | None = None,
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
    try:
        data, mime = await storage_service.get_object_async(e["storage_path"])
    except Exception:
        raise HTTPException(404, "File not available")
    await core.audit(ctx["user"], "evidence_downloaded", "evidence", evidence_id, {"case_id": e["case_id"]}, request)
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": f'inline; filename="{e.get("filename", "file")}"',
                             "Cache-Control": "private, max-age=300"})


@router.get("/cases/{case_id}/evidence")
async def list_evidence(case_id: str, ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    items = [core.clean(e) async for e in core.db.evidence.find({"case_id": str(case["_id"])}).sort("created_at", -1)]
    return {"items": items}
