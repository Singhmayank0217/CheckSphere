"""Agent 'Upload New Cases': an agent submits new case details + a PDF without prior approval.

A submission is NOT a case and is never treated as approved or completed: it stays in its own collection
(case_uploads) with a review status that only Supervisors / Super Admin can change. PDFs are stored as private
objects in Cloudflare R2 and are only served through this API after an access check.
"""
import hashlib
import logging

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

import core
import security
import storage_service

router = APIRouter()
logger = logging.getLogger(__name__)

INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi",
    "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
MAX_PDF = 10 * 1024 * 1024
STATUS_LABELS = {"submitted": "Submitted", "under_review": "Under Review", "clarification": "Clarification Requested",
                 "accepted": "Accepted", "rejected": "Rejected"}
ACTIONS = {"review": "under_review", "clarify": "clarification", "accept": "accepted", "reject": "rejected"}


def _scope(user: dict) -> dict:
    if user["role"] == "agent":
        return {"submitted_by": str(user["_id"])}
    if user["role"] == "supervisor":
        states = (user.get("scope") or {}).get("states")
        return {"state": {"$in": states}} if states else {}
    return {}


def _public(d: dict) -> dict:
    out = core.clean(d)
    pdf = out.pop("pdf", None) or {}
    out["pdf"] = {"filename": pdf.get("filename"), "size": pdf.get("size"), "available": bool(pdf.get("storage_path"))}
    out["status_label"] = STATUS_LABELS.get(out.get("status"), out.get("status"))
    return out


async def _get(uid: str, user: dict) -> dict:
    try:
        q = {"_id": ObjectId(uid), **_scope(user)}
    except Exception:
        raise HTTPException(404, "Submission not found")
    d = await core.db.case_uploads.find_one(q)
    if not d:
        raise HTTPException(404, "Submission not found")
    return d


@router.get("/case-uploads/states")
async def states(ctx=Depends(security.staff)):
    return {"items": INDIAN_STATES}


@router.post("/case-uploads")
async def create_upload(request: Request, file: UploadFile = File(...), state: str = Form(""),
                        branch_name: str = Form(""), applicant_name: str = Form(""), co_applicant_name: str = Form(""),
                        co_applicant2_name: str | None = Form(None), requirements: str | None = Form(None),
                        ctx=Depends(security.require_roles("agent"))):
    u = ctx["user"]
    clean = {k: (v or "").strip() for k, v in {"state": state, "branch_name": branch_name, "applicant_name": applicant_name,
                                                "co_applicant_name": co_applicant_name, "co_applicant2_name": co_applicant2_name,
                                                "requirements": requirements}.items()}
    errs = []
    if clean["state"] not in INDIAN_STATES:
        errs.append("Choose a valid State")
    for k, label in (("branch_name", "Branch Name"), ("applicant_name", "Applicant Name"), ("co_applicant_name", "Co-applicant Name")):
        if not clean[k]:
            errs.append(f"{label} is required")
        elif len(clean[k]) > 200:
            errs.append(f"{label} is too long")
    if len(clean["co_applicant2_name"]) > 200:
        errs.append("Second Co-applicant Name is too long")
    if len(clean["requirements"]) > 4000:
        errs.append("Requirements must be under 4000 characters")
    data = await file.read(MAX_PDF + 1)
    if len(data) > MAX_PDF:
        errs.append("PDF is too large (max 10 MB)")
    elif storage_service.detect_type(data) != "pdf":  # real file signature, not the filename or client MIME type
        errs.append("Attach a valid PDF document")
    if errs:
        if any("PDF" in e for e in errs):
            logger.warning("case upload rejected: agent %s, %d bytes, declared %s, filename-ext %s, first bytes %s",
                           u["_id"], len(data), file.content_type, (file.filename or "").rsplit(".", 1)[-1][:8], data[:8].hex())
        raise HTTPException(422, detail={"code": "validation_error", "problems": errs})

    oid = ObjectId()
    path = storage_service.object_path(str(oid), "pdf", "uploads")
    try:
        stored = await storage_service.put_object_async(path, data, "application/pdf",
                                                        {"upload-id": str(oid), "variant": "case-upload-pdf",
                                                         "original-filename": file.filename or "document.pdf"})
    except storage_service.StorageNotConfigured:
        raise HTTPException(503, "File storage is not configured on the server")
    except Exception as exc:
        logger.error("case upload: storage failed (%s): %s", oid, type(exc).__name__)
        raise HTTPException(502, "PDF upload failed. Please retry.")
    now = core.now()
    doc = {
        "_id": oid, **clean, "co_applicant2_name": clean["co_applicant2_name"] or None, "requirements": clean["requirements"] or None,
        "status": "submitted", "submitted_by": str(u["_id"]), "submitted_by_name": u["name"], "submitted_by_agent_id": u.get("agent_id"),
        "submitted_at": now, "updated_at": now,
        "pdf": {"storage_path": path, "filename": (file.filename or "document.pdf")[:200], "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(), "storage": stored, "storage_provider": stored["provider"]},
        "history": [{"action": "submitted", "by": str(u["_id"]), "by_name": u["name"], "at": now}], "comments": [],
    }
    await core.db.case_uploads.insert_one(doc)
    await core.audit(u, "case_upload_submitted", "case_upload", str(oid), {"state": clean["state"]}, request)
    logger.info("case upload stored: %s (%d bytes, private raw asset)", oid, len(data))
    from requests_routes import notify
    async for sup in core.db.users.find({"role": "supervisor", "disabled": {"$ne": True}}):
        st = (sup.get("scope") or {}).get("states")
        if not st or clean["state"] in st:
            await notify(str(sup["_id"]), "New uploaded case", f"{u['name']} uploaded a new case for review.", None, "request")
    return _public(doc)


@router.get("/case-uploads")
async def list_uploads(status: str | None = None, ctx=Depends(security.staff)):
    q = _scope(ctx["user"])
    if status:
        q = {**q, "status": {"$in": [s.strip() for s in status.split(",")]}}
    items = [_public(d) async for d in core.db.case_uploads.find(q).sort("submitted_at", -1).limit(500)]
    return {"items": items}


@router.get("/case-uploads/{uid}")
async def get_upload(uid: str, ctx=Depends(security.staff)):
    return _public(await _get(uid, ctx["user"]))


@router.get("/case-uploads/{uid}/pdf")
async def get_upload_pdf(uid: str, request: Request, token: str | None = None, creds=Depends(security.bearer)):
    ctx = await security.load_session_ctx(request, creds, token)
    d = await _get(uid, ctx["user"])
    pdf = d.get("pdf") or {}
    if not pdf.get("storage_path") or not storage_service.readable(pdf.get("storage_provider")):
        raise HTTPException(404, "PDF not available")
    try:
        data, _ = await storage_service.get_object_async(pdf["storage_path"], pdf["storage_provider"])
    except Exception:
        raise HTTPException(404, "PDF not available")
    await core.audit(ctx["user"], "case_upload_pdf_viewed", "case_upload", uid, {}, request)
    from evidence_routes import safe_file_headers
    return Response(data, media_type="application/pdf", headers=safe_file_headers(pdf.get("filename") or "document.pdf", "application/pdf"))


class UploadActionIn(BaseModel):
    action: str = Field(pattern="^(review|clarify|accept|reject)$")
    comment: str = Field(default="", max_length=2000)


@router.post("/case-uploads/{uid}/action")
async def upload_action(uid: str, body: UploadActionIn, request: Request, ctx=Depends(security.admin_sup)):
    u = ctx["user"]
    d = await _get(uid, u)
    if d["status"] in ("accepted", "rejected"):
        raise HTTPException(400, f"Submission is already {STATUS_LABELS[d['status']].lower()}")
    if body.action in ("reject", "clarify") and not body.comment.strip():
        raise HTTPException(400, "A reason / comment is required")
    now = core.now()
    new_status = ACTIONS[body.action]
    upd = {"$set": {"status": new_status, "updated_at": now, "reviewed_by": str(u["_id"]), "reviewed_by_name": u["name"], "reviewed_at": now},
           "$push": {"history": {"action": body.action, "by": str(u["_id"]), "by_name": u["name"], "at": now, "comment": body.comment}}}
    if body.comment.strip():
        upd["$push"]["comments"] = {"by": u["name"], "at": now, "text": body.comment.strip(), "action": body.action}
    await core.db.case_uploads.update_one({"_id": d["_id"]}, upd)
    await core.audit(u, f"case_upload_{body.action}", "case_upload", uid, {"comment": body.comment}, request)
    from requests_routes import notify
    # any comment is kept in the upload's comments; the notification only points to it (no applicant details)
    await notify(d["submitted_by"], f"Uploaded case {STATUS_LABELS[new_status].lower()}",
                 "Open your uploaded cases in CheckSphere to see the details.", None, "request")
    return _public(await core.db.case_uploads.find_one({"_id": d["_id"]}))
