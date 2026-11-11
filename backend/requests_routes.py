"""Agent case requests, in-app notifications, agent accept/reassign, pending-case alerts."""
import asyncio
import logging
import re
from datetime import timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import core
import security
import storage_service
from cases_routes import get_case_or_404, tl

router = APIRouter()
logger = logging.getLogger(__name__)

REQ_TYPES = {"Residence Verification": "residence_applicant", "Office Verification": "office_coapplicant",
             "Business Verification": "business_applicant", "Telephone Verification": "tel_residence",
             "Income Verification": "income", "KYC Verification": "kyc", "Seller Verification": "seller", "Other": "custom"}
FIELDS = ["request_type", "applicant_name", "co_applicant_name", "seller_name", "primary_phone", "alt_phone", "client_name",
          "branch_name", "bank_state", "full_address", "pincode", "verification_state", "city", "notes", "priority", "supervisor_id"]


async def notify(user_id: str, title: str, body: str, case_id: str | None = None, kind: str = "info"):
    await core.db.notifications.insert_one({"user_id": user_id, "title": title, "body": body, "case_id": case_id, "kind": kind,
                                            "created_at": core.now(), "delivered_at": None, "acknowledged_at": None})


async def notify_role(role: str, title: str, body: str, case_id: str | None = None, kind: str = "alert"):
    async for u in core.db.users.find({"role": role, "disabled": {"$ne": True}}, {"_id": 1}):
        await notify(str(u["_id"]), title, body, case_id, kind)


async def notify_case_supervisors(case: dict, title: str, body: str, kind: str = "alert"):
    """Notify only supervisors whose scope covers this case (or who allocated it)."""
    async for u in core.db.users.find({"role": "supervisor", "disabled": {"$ne": True}}):
        if str(u["_id"]) == case.get("assigned_supervisor_id"):
            await notify(str(u["_id"]), title, body, str(case["_id"]), kind)
            continue
        q = security.case_scope_query(u)
        if not q or await core.db.cases.count_documents({"_id": case["_id"], **q}):
            await notify(str(u["_id"]), title, body, str(case["_id"]), kind)


def oid(v: str) -> ObjectId:
    try:
        return ObjectId(v)
    except Exception:
        raise HTTPException(404, "Not found")


def validate(d: dict) -> list:
    errs = []
    if d.get("request_type") not in REQ_TYPES:
        errs.append("Choose a request type")
    if not any((d.get(k) or "").strip() for k in ("applicant_name", "co_applicant_name", "seller_name")):
        errs.append("Enter at least one of Applicant, Co-applicant or Seller name")
    for k, label in (("full_address", "Full address"), ("branch_name", "Branch name"), ("primary_phone", "Primary contact number")):
        if not (d.get(k) or "").strip():
            errs.append(f"{label} is required")
    if not re.fullmatch(r"\d{6}", (d.get("pincode") or "").strip()):
        errs.append("Pincode must be 6 digits")
    if not (d.get("supervisor_id") or "").strip():
        errs.append("Choose the supervisor to send this request to")
    return errs


@router.get("/requests/supervisors")
async def request_supervisors(ctx=Depends(security.staff)):
    items = [{"id": str(u["_id"]), "name": u["name"]}
             async for u in core.db.users.find({"role": "supervisor", "disabled": {"$ne": True}}, {"name": 1}).sort("name", 1)]
    return {"items": items}


async def scoped_query(user: dict) -> dict:
    if user["role"] == "agent":
        return {"requested_by": str(user["_id"])}
    if user["role"] == "supervisor":
        s = user.get("scope") or {}
        cons = [{"supervisor_id": str(user["_id"])}]
        if s.get("states"):
            cons += [{"verification_state": {"$in": s["states"]}}, {"bank_state": {"$in": s["states"]}}]
        if s.get("agent_ids"):
            cons.append({"requested_by": {"$in": s["agent_ids"]}})
        if s.get("client_ids"):
            names = [c["name"] async for c in core.db.clients.find({"_id": {"$in": [ObjectId(i) for i in s["client_ids"]]}})]
            cons.append({"client_name": {"$in": names}})
        return {"$or": cons}
    return {}


async def get_req(rid: str, user: dict) -> dict:
    q = {"_id": oid(rid), **(await scoped_query(user))}
    r = await core.db.case_requests.find_one(q)
    if not r:
        raise HTTPException(404, "Request not found")
    return r


class ReqIn(BaseModel):
    data: dict
    declaration: bool = False


@router.post("/requests")
async def create_request(body: ReqIn, request: Request, ctx=Depends(security.require_roles("agent"))):
    d = {k: str(body.data.get(k) or "").strip() for k in FIELDS}
    u = ctx["user"]
    doc = {**d, "status": "draft", "declaration": body.declaration, "requested_by": str(u["_id"]), "requested_by_name": u["name"],
           "documents": [], "history": [tl("request_created", u, {})], "comments": [], "created_at": core.now(), "updated_at": core.now()}
    res = await core.db.case_requests.insert_one(doc)
    await core.audit(u, "case_request_created", "case_request", str(res.inserted_id), {}, request)
    return core.clean(await core.db.case_requests.find_one({"_id": res.inserted_id}))


@router.post("/requests/{rid}/document")
async def upload_doc(rid: str, request: Request, file: UploadFile = File(...), ctx=Depends(security.staff)):
    r = await get_req(rid, ctx["user"])
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 10MB)")
    ext = (file.filename or "doc.jpg").split(".")[-1][:5]
    path = storage_service.object_path(f"requests/{rid}", ext)
    await storage_service.put_object_async(path, data, file.content_type or "application/octet-stream")
    d = {"id": ObjectId().__str__(), "path": path, "filename": file.filename, "mime": file.content_type, "at": core.now()}
    await core.db.case_requests.update_one({"_id": r["_id"]}, {"$push": {"documents": d, "history": tl("document_uploaded", ctx["user"], {"file": file.filename})}})
    await core.audit(ctx["user"], "case_request_document", "case_request", rid, {}, request)
    return {k: v for k, v in d.items() if k != "path"}


@router.get("/requests/{rid}/document/{did}")
async def get_doc(rid: str, did: str, request: Request, token: str | None = None, creds=Depends(security.bearer)):
    ctx = await security.load_session_ctx(request, creds, token)
    r = await get_req(rid, ctx["user"])
    d = next((x for x in r.get("documents", []) if x["id"] == did), None)
    if not d:
        raise HTTPException(404, "Document not found")
    data, mime = await storage_service.get_object_async(d["path"])
    await core.audit(ctx["user"], "case_request_document_viewed", "case_request", rid, {}, request)
    return Response(data, media_type=mime)


@router.post("/requests/{rid}/submit")
async def submit_request(rid: str, body: ReqIn, request: Request, ctx=Depends(security.require_roles("agent"))):
    r = await get_req(rid, ctx["user"])
    if r["status"] not in ("draft", "clarification"):
        raise HTTPException(400, "Request already submitted")
    d = {k: str(body.data.get(k) or "").strip() for k in FIELDS}
    errs = validate(d)
    sup = None
    if d["supervisor_id"]:
        try:
            sup = await core.db.users.find_one({"_id": ObjectId(d["supervisor_id"]), "role": "supervisor", "disabled": {"$ne": True}})
        except Exception:
            sup = None
        if not sup:
            errs.append("Selected supervisor is not available")
    if not r.get("documents"):
        errs.append("Supporting document upload is mandatory")
    if not body.declaration:
        errs.append("Accept the agent declaration")
    if errs:
        raise HTTPException(422, detail={"code": "validation_error", "problems": errs})
    await core.db.case_requests.update_one({"_id": r["_id"]}, {"$set": {**d, "supervisor_name": sup["name"], "declaration": True, "status": "sent_for_allocation",
                                                                        "submitted_at": core.now(), "updated_at": core.now()},
                                                              "$push": {"history": tl("request_submitted", ctx["user"], {"supervisor": sup["name"]})}})
    await core.audit(ctx["user"], "case_request_submitted", "case_request", rid, {"supervisor": sup["name"]}, request)
    await notify(str(sup["_id"]), "New case request", f"{ctx['user']['name']} raised a {d['request_type']} request for your approval", None, "request")
    return {"ok": True}


@router.get("/requests")
async def list_requests(status: str | None = None, ctx=Depends(security.staff)):
    q = await scoped_query(ctx["user"])
    if ctx["user"]["role"] != "agent":
        q = {"$and": [q, {"status": {"$ne": "draft"}}]} if q else {"status": {"$ne": "draft"}}
    if status:
        q = {"$and": [q, {"status": status}]}
    items = []
    async for r in core.db.case_requests.find(q).sort("created_at", -1).limit(500):
        d = core.clean(r)
        d["documents"] = [{k: v for k, v in x.items() if k != "path"} for x in r.get("documents", [])]
        items.append(d)
    return {"items": items}


class ActionIn(BaseModel):
    action: str
    comment: str = ""
    data: dict | None = None
    agent_id: str | None = None
    due_at: str | None = None


@router.post("/requests/{rid}/action")
async def request_action(rid: str, body: ActionIn, request: Request, ctx=Depends(security.admin_sup)):
    u = ctx["user"]
    r = await get_req(rid, u)
    if r["status"] in ("assigned", "rejected", "cancelled", "duplicate"):
        raise HTTPException(400, f"Request is already {r['status']}")
    now = core.now()
    sets, ev = {"updated_at": now}, body.action
    if body.action == "edit":
        changes = {k: str(v).strip() for k, v in (body.data or {}).items() if k in FIELDS and str(v).strip() != (r.get(k) or "")}
        sets.update(changes)
        sets["status"] = "under_review"
        hist = tl("request_edited", u, {"changes": {k: f"{r.get(k) or ''} → {v}" for k, v in changes.items()}})
    elif body.action in ("reject", "clarify", "duplicate", "escalate", "review"):
        if body.action in ("reject", "clarify") and not body.comment.strip():
            raise HTTPException(400, "A reason / comment is required")
        sets["status"] = {"reject": "rejected", "clarify": "clarification", "duplicate": "duplicate", "escalate": "under_review", "review": "under_review"}[body.action]
        if body.action == "escalate":
            sets["escalated"] = True
            await notify_role("super_admin", "Case request escalated", f"{u['name']} escalated a request", None, "request")
        hist = tl(f"request_{body.action}", u, {"comment": body.comment})
        if body.action in ("reject", "clarify", "duplicate"):
            await notify(r["requested_by"], f"Request {sets['status']}", body.comment or "See request details", None, "request")
    elif body.action == "approve":
        changes = {k: str(v).strip() for k, v in (body.data or {}).items() if k in FIELDS and k != "supervisor_id"}
        if changes:
            sets.update(changes)
            r = {**r, **changes}
        errs = validate(r)
        if errs:
            raise HTTPException(422, detail={"code": "validation_error", "problems": errs})
        if not body.agent_id:
            raise HTTPException(400, "Select the agent to allocate before activation")
        agent = await core.db.users.find_one({"_id": oid(body.agent_id), "role": "agent", "disabled": {"$ne": True}})
        if not agent:
            raise HTTPException(400, "Agent not found or inactive")
        client = await core.db.clients.find_one({"name": {"$regex": f"^{re.escape(r.get('client_name') or '')}$", "$options": "i"}})
        branch = await core.db.branches.find_one({"name": {"$regex": f"^{re.escape(r.get('branch_name') or '')}$", "$options": "i"}})
        from datetime import datetime, timezone
        try:
            due = datetime.fromisoformat(body.due_at).replace(tzinfo=timezone.utc) if body.due_at else now + timedelta(hours=48)
        except ValueError:
            raise HTTPException(400, "SLA due must be a date like 2026-06-30 or 2026-06-30T18:00")
        seq = await core.next_seq("case_seq")
        case = {
            "internal_case_id": f"CSV-{seq:06d}", "client_case_id": f"REQ-{str(r['_id'])[-6:].upper()}",
            "client_id": str(client["_id"]) if client else None, "client_name": r.get("client_name") or "Unspecified",
            "branch_id": str(branch["_id"]) if branch else None, "branch_name": r.get("branch_name"),
            "applicant_name": r.get("applicant_name") or r.get("co_applicant_name") or r.get("seller_name"),
            "co_applicant_name": r.get("co_applicant_name") or None, "seller_name": r.get("seller_name") or None,
            "primary_phone": r.get("primary_phone"), "alt_phone": r.get("alt_phone"), "bank_state": r.get("bank_state"),
            "pincode": r.get("pincode"), "verification_state": r.get("verification_state"), "notes": r.get("notes"),
            "report_type": REQ_TYPES[r["request_type"]], "assigned_address": r.get("full_address"),
            "city": r.get("city"), "state": r.get("verification_state") or r.get("bank_state"),
            "priority": "High" if r.get("priority") == "Urgent" else "Medium", "due_at": due, "status": "assigned",
            "assigned_agent_id": str(agent["_id"]), "assigned_agent_name": agent["name"], "assigned_supervisor_id": str(u["_id"]),
            "created_by": str(u["_id"]), "source_request_id": rid, "flags": [], "created_at": now, "updated_at": now,
            "timeline": [*r.get("history", []), tl("case_created", u, {"source": "agent request", "requested_by": r["requested_by_name"]}),
                         tl("request_approved", u, {"approved_by": u["name"]}), tl("assigned", u, {"agent": agent["name"]})],
        }
        res = await core.db.cases.insert_one(case)
        sets.update({"status": "assigned", "case_id": str(res.inserted_id), "internal_case_id": case["internal_case_id"], "approved_by": u["name"],
                     "approved_at": now, "allocated_at": now, "assigned_agent_id": str(agent["_id"]), "assigned_agent_name": agent["name"]})
        hist = tl("request_approved_allocated", u, {"case": case["internal_case_id"], "agent": agent["name"]})
        await notify(str(agent["_id"]), "New case assigned", f"{case['internal_case_id']} · {case['applicant_name']} · due {due:%d %b %H:%M}", str(res.inserted_id), "assignment")
        if r["requested_by"] != str(agent["_id"]):
            await notify(r["requested_by"], "Your request was approved", f"Allocated to {agent['name']} as {case['internal_case_id']}", None, "request")
    else:
        raise HTTPException(400, "Unknown action")
    if body.comment:
        sets_comment = {"by": u["name"], "at": now, "text": body.comment, "action": body.action}
        await core.db.case_requests.update_one({"_id": r["_id"]}, {"$push": {"comments": sets_comment}})
    await core.db.case_requests.update_one({"_id": r["_id"]}, {"$set": sets, "$push": {"history": hist}})
    await core.audit(u, f"case_request_{ev}", "case_request", rid, {"comment": body.comment}, request)
    return {"ok": True, "status": sets.get("status")}


@router.post("/requests/{rid}/cancel")
async def cancel_request(rid: str, request: Request, ctx=Depends(security.require_roles("agent"))):
    r = await get_req(rid, ctx["user"])
    if r["status"] in ("assigned", "rejected"):
        raise HTTPException(400, "Cannot cancel")
    await core.db.case_requests.update_one({"_id": r["_id"]}, {"$set": {"status": "cancelled"}, "$push": {"history": tl("request_cancelled", ctx["user"], {})}})
    await core.audit(ctx["user"], "case_request_cancelled", "case_request", rid, {}, request)
    return {"ok": True}


# ---------------------------------------------------------------- notifications
@router.get("/notifications")
async def my_notifications(ctx=Depends(security.staff)):
    uid = str(ctx["user"]["_id"])
    await core.db.notifications.update_many({"user_id": uid, "delivered_at": None}, {"$set": {"delivered_at": core.now()}})
    items = [core.clean(n) async for n in core.db.notifications.find({"user_id": uid}).sort("created_at", -1).limit(100)]
    case_ids = list({n["case_id"] for n in items if n.get("kind") == "assignment" and n.get("case_id")})
    if case_ids:
        resp = {str(c["_id"]): c async for c in core.db.cases.find({"_id": {"$in": [ObjectId(i) for i in case_ids if ObjectId.is_valid(i)]}},
                                                                     {"agent_response": 1, "assigned_agent_id": 1})}
        for n in items:
            c = resp.get(n.get("case_id") or "")
            if n.get("kind") == "assignment":
                n["can_respond"] = bool(c and c.get("assigned_agent_id") == uid and not c.get("agent_response"))
                n["agent_response"] = (c or {}).get("agent_response")
    return {"items": items, "unread": sum(1 for n in items if not n.get("acknowledged_at"))}


@router.post("/notifications/{nid}/ack")
async def ack(nid: str, ctx=Depends(security.staff)):
    await core.db.notifications.update_one({"_id": oid(nid), "user_id": str(ctx["user"]["_id"])}, {"$set": {"acknowledged_at": core.now()}})
    return {"ok": True}


class AgentResp(BaseModel):
    response: str
    reason: str = ""


@router.post("/cases/{case_id}/agent-response")
async def agent_response(case_id: str, body: AgentResp, request: Request, ctx=Depends(security.require_roles("agent"))):
    case = await get_case_or_404(case_id)
    if case.get("assigned_agent_id") != str(ctx["user"]["_id"]):
        raise HTTPException(403, "Not allowed")
    if body.response not in ("accept", "reassign"):
        raise HTTPException(400, "Response must be accept or reassign")
    if case.get("agent_response"):
        raise HTTPException(400, "You have already responded to this allocation")
    if body.response == "reassign" and not body.reason.strip():
        raise HTTPException(400, "Give a reason for the reassignment request")
    act = "agent_accepted" if body.response == "accept" else "agent_requested_reassignment"
    await core.db.cases.update_one({"_id": case["_id"]}, {"$set": {"agent_response": body.response, "agent_response_at": core.now(),
                                                                 "agent_response_reason": body.reason},
                                                        "$push": {"timeline": tl(act, ctx["user"], {"reason": body.reason})}})
    await core.audit(ctx["user"], act, "case", case_id, {"reason": body.reason}, request)
    if body.response == "reassign":
        await notify_case_supervisors(case, "Reassignment requested", f"{ctx['user']['name']}: {case['internal_case_id']} — {body.reason}")
    return {"ok": True}


# ---------------------------------------------------------------- pending alerts
async def pending_alert_loop():
    while True:
        try:
            now = core.now()
            q = {"status": {"$in": core.ACTIVE_STATUSES}, "deleted_at": None}
            async for c in core.db.cases.find({**q, "updated_at": {"$lt": now - timedelta(hours=24)}, "alert_24h_at": None}):
                body = f"{c['internal_case_id']} · {c.get('applicant_name')} pending more than 24 hours"
                if c.get("assigned_agent_id"):
                    await notify(c["assigned_agent_id"], "Case pending > 24h", body, str(c["_id"]), "alert")
                await notify_case_supervisors(c, "Case pending > 24h", body)
                await core.db.cases.update_one({"_id": c["_id"]}, {"$set": {"alert_24h_at": now}})
            async for c in core.db.cases.find({**q, "updated_at": {"$lt": now - timedelta(hours=48)}, "alert_48h_at": None}):
                await notify_role("super_admin", "Case pending > 48h", f"{c['internal_case_id']} · {c.get('applicant_name')} pending more than 48 hours", str(c["_id"]))
                await core.db.cases.update_one({"_id": c["_id"]}, {"$set": {"alert_48h_at": now}})
            rq = {"status": {"$in": ["sent_for_allocation", "under_review", "clarification"]}}
            async for r in core.db.case_requests.find({**rq, "submitted_at": {"$lt": now - timedelta(hours=24)}, "alert_24h_at": None}):
                body = f"{r['request_type']} request from {r['requested_by_name']} awaiting allocation more than 24 hours"
                await notify(r["requested_by"], "Request pending > 24h", body, None, "alert")
                if r.get("supervisor_id"):
                    await notify(r["supervisor_id"], "Request pending > 24h", body, None, "alert")
                await core.db.case_requests.update_one({"_id": r["_id"]}, {"$set": {"alert_24h_at": now}})
            async for r in core.db.case_requests.find({**rq, "submitted_at": {"$lt": now - timedelta(hours=48)}, "alert_48h_at": None}):
                await notify_role("super_admin", "Request pending > 48h", f"{r['request_type']} request from {r['requested_by_name']} not allocated for 48 hours")
                await core.db.case_requests.update_one({"_id": r["_id"]}, {"$set": {"alert_48h_at": now}})
        except Exception as exc:
            logger.error("pending alerts failed: %s", exc)
        await asyncio.sleep(300)
