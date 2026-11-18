"""Case routes: create, Excel import, list, detail, assign, timeline, visit start, call logs."""
import asyncio
import io
import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field

import core
import security
import geocoding
from report_config import REPORT_TYPES

router = APIRouter()


def tl(action: str, user, details: dict | None = None) -> dict:
    return {"action": action, "by": str(user.get("_id") or ""), "by_name": (user or {}).get("name") or "system",
            "at": core.now(), "details": details or {}}


async def can_access_case(user: dict, case: dict) -> bool:
    if case.get("is_draft"):
        # An unsubmitted Create New Verification draft is not a case yet: only the agent who started it can open it.
        return user["role"] == "agent" and case.get("created_by") == str(user["_id"])
    if user["role"] == "super_admin":
        return True
    if user["role"] == "agent":
        return case.get("assigned_agent_id") == str(user["_id"])
    q = security.case_scope_query(user)
    if not q:
        return True
    merged = {"_id": case["_id"], **q}
    return await core.db.cases.count_documents(merged) > 0


async def get_case_or_404(case_id: str) -> dict:
    try:
        case = await core.db.cases.find_one({"_id": ObjectId(case_id)})
    except Exception:
        case = await core.db.cases.find_one({"internal_case_id": case_id})
    if not case or case.get("deleted_at"):
        raise HTTPException(404, "Case not found")
    return case


def clean_external_id(v) -> str | None:
    """Client / External Case ID is optional: blank becomes None. It never replaces the Internal Case ID."""
    v = str(v).strip() if v is not None else ""
    if v.endswith(".0") and v[:-2].isdigit():  # Excel numeric cell, e.g. 12345.0
        v = v[:-2]
    return v[:120] or None


class CaseCreate(BaseModel):
    client_case_id: str | None = Field(default=None, max_length=120)  # optional client / external reference
    client_id: str
    branch_id: str | None = None
    applicant_name: str = Field(min_length=1, max_length=200)
    co_applicant_name: str | None = None
    loan_type: str | None = None
    report_type: str
    assigned_address: str = Field(min_length=1)
    city: str | None = None
    state: str | None = None
    priority: str = "Medium"
    due_at: datetime | None = None
    assigned_lat: float | None = None
    assigned_lon: float | None = None
    seller_name: str | None = None
    primary_phone: str | None = None
    alt_phone: str | None = None
    bank_state: str | None = None
    pincode: str | None = None
    verification_state: str | None = None
    notes: str | None = None
    agent_id: str | None = None  # assign on creation (required when a Supervisor creates the case)


def create_case_doc(body: CaseCreate, client: dict, branch: dict | None, user) -> dict:
    doc = {
        "client_case_id": clean_external_id(body.client_case_id), "client_id": str(client["_id"]), "client_name": client["name"],
        "branch_id": (str(branch["_id"]) if branch else None), "branch_name": (branch or {}).get("name"),
        "applicant_name": body.applicant_name, "co_applicant_name": body.co_applicant_name,
        "loan_type": body.loan_type, "report_type": body.report_type,
        "assigned_address": body.assigned_address, "city": body.city or (branch or {}).get("city"),
        "state": body.state or (branch or {}).get("state"), "priority": body.priority or "Medium",
        "due_at": body.due_at, "assigned_lat": body.assigned_lat, "assigned_lon": body.assigned_lon,
        "seller_name": body.seller_name, "primary_phone": body.primary_phone, "alt_phone": body.alt_phone,
        "bank_state": body.bank_state, "pincode": body.pincode, "verification_state": body.verification_state, "notes": body.notes,
        "status": "new", "created_by": str(user["_id"]), "created_by_role": user.get("role"),
        "source": "supervisor_created" if user.get("role") == "supervisor" else "admin_created",
        "flags": [], "timeline": [],
        "created_at": core.now(), "updated_at": core.now(),
        **geocoding.initial_location_fields(body.assigned_lat, body.assigned_lon),
    }
    return doc


@router.post("/cases")
async def create_case(body: CaseCreate, request: Request, ctx=Depends(security.admin_sup)):
    u = ctx["user"]
    try:
        client = await core.db.clients.find_one({"_id": ObjectId(body.client_id)})
    except Exception:
        client = None
    if not client:
        raise HTTPException(400, "Client not found")
    if client.get("active") is False:
        raise HTTPException(400, "This client is deactivated and cannot be used for new cases")
    scope = (u.get("scope") or {}) if u["role"] == "supervisor" else {}
    if scope.get("client_ids") and str(client["_id"]) not in scope["client_ids"]:
        raise HTTPException(403, "This client is outside your supervision scope")
    agent = None
    if u["role"] == "supervisor" and not body.agent_id:
        raise HTTPException(400, "Select the agent to assign this case to")
    if body.agent_id:
        try:
            agent = await core.db.users.find_one({"_id": ObjectId(body.agent_id), "role": "agent", "disabled": {"$ne": True}})
        except Exception:
            agent = None
        if not agent:
            raise HTTPException(400, "Agent not found or inactive")
        if scope.get("agent_ids") and str(agent["_id"]) not in scope["agent_ids"]:
            raise HTTPException(403, "This agent is outside your supervision scope")
    if body.report_type not in REPORT_TYPES:
        raise HTTPException(400, "Unknown report type")
    if not (body.primary_phone or "").strip():
        raise HTTPException(400, "Primary contact number is required")
    if body.pincode and not re.fullmatch(r"\d{6}", body.pincode.strip()):
        raise HTTPException(400, "Pincode must be 6 digits")
    branch = None
    if body.branch_id:
        try:
            branch = await core.db.branches.find_one({"_id": ObjectId(body.branch_id)})
        except Exception:
            branch = None
        if not branch or branch.get("client_id") != str(client["_id"]):
            raise HTTPException(400, "Branch not found for this client")
        if branch.get("active") is False:
            raise HTTPException(400, "This branch is deactivated and cannot be used for new cases")
    doc = create_case_doc(body, client, branch, ctx["user"])
    doc["internal_case_id"] = await core.next_internal_case_id()
    doc["timeline"] = [tl("case_created", u, {"source": "manual", "by_role": u["role"]})]
    if u["role"] == "supervisor":
        doc["assigned_supervisor_id"] = str(u["_id"])
    if agent:
        now = core.now()
        doc.update({"assigned_agent_id": str(agent["_id"]), "assigned_agent_name": agent["name"], "status": "assigned",
                    "assigned_at": now, "assigned_by": str(u["_id"])})
        doc["timeline"].append(tl("assigned", u, {"agent": agent["name"], "reason": "assigned on creation"}))
    res = await core.db.cases.insert_one(doc)
    await core.audit(u, "case_created", "case", str(res.inserted_id),
                     {"internal_case_id": doc["internal_case_id"], "source": doc["source"],
                      "assigned_agent": agent["name"] if agent else None}, request)
    if agent:
        await core.audit(u, "case_assigned", "case", str(res.inserted_id), {"agent": agent["name"]}, request)
        from requests_routes import notify
        await notify(str(agent["_id"]), "New case assigned",
                     f"{doc['internal_case_id']} · {doc.get('applicant_name')} · {doc.get('client_name')}", str(res.inserted_id), "assignment")
    return core.clean(await core.db.cases.find_one({"_id": res.inserted_id}))


@router.get("/cases/import-template")
async def import_template(ctx=Depends(security.admin_only)):
    from exporters import build_import_template_xlsx
    data = build_import_template_xlsx()
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="checksphere-case-import-template.xlsx"'})


@router.post("/cases/import")
async def import_cases(request: Request, file: UploadFile = File(...), ctx=Depends(security.admin_only)):
    from openpyxl import load_workbook
    content = await file.read()
    try:
        wb = load_workbook(io.BytesIO(content), data_only=True)
    except Exception:
        raise HTTPException(400, "Invalid file. Upload an .xlsx workbook based on the import template.")
    ws = wb.active
    headers = [str(c).strip() if c else "" for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    idx = {h.lower().strip(): i for i, h in enumerate(headers) if h}

    def cell(row, name):
        i = idx.get(name.lower())
        return row[i] if i is not None and i < len(row) else None

    type_by_name = {v["name"].lower(): k for k, v in REPORT_TYPES.items()}
    created, errors = 0, []
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    for n, row in enumerate(rows, start=2):
        if not row or not any(row):
            continue
        try:
            client_name = str(cell(row, "Client Name") or "").strip()
            client = await core.db.clients.find_one({"name": {"$regex": f"^{re.escape(client_name)}$", "$options": "i"}}) if client_name else None
            if not client:
                errors.append(f"Row {n}: client '{client_name}' not found")
                continue
            if client.get("active") is False:
                errors.append(f"Row {n}: client '{client_name}' is deactivated")
                continue
            rt_name = str(cell(row, "Report Type") or "").strip().lower()
            rt = type_by_name.get(rt_name)
            if not rt:
                errors.append(f"Row {n}: unknown report type '{rt_name}'")
                continue
            branch_name = str(cell(row, "Branch Name") or "").strip()
            branch = None
            if branch_name:
                branch = await core.db.branches.find_one({"client_id": str(client["_id"]), "active": {"$ne": False},
                                                          "name": {"$regex": f"^{re.escape(branch_name)}$", "$options": "i"}})
            due_raw = cell(row, "Due Date (YYYY-MM-DD)")
            due_at = None
            if due_raw:
                if isinstance(due_raw, datetime):
                    due_at = due_raw.replace(tzinfo=timezone.utc)
                else:
                    try:
                        due_at = datetime.fromisoformat(str(due_raw)).replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass
            applicant = str(cell(row, "Applicant Name") or "").strip()
            if not applicant:
                errors.append(f"Row {n}: applicant name missing")
                continue
            def opt(name):
                v = cell(row, name)
                return (str(v).strip() or None) if v not in (None, "") else None

            phone = opt("Primary Contact Number")
            if not phone:
                errors.append(f"Row {n}: primary contact number missing")
                continue
            pin = opt("Pincode")
            if pin and not re.fullmatch(r"\d{6}", pin.split(".")[0]):
                errors.append(f"Row {n}: pincode must be 6 digits")
                continue
            body = CaseCreate(
                client_case_id=clean_external_id(cell(row, "Client Case ID")),
                client_id=str(client["_id"]), applicant_name=applicant,
                co_applicant_name=opt("Co-applicant Name"), seller_name=opt("Seller Name"),
                primary_phone=phone.split(".")[0], alt_phone=opt("Alternate Phone"),
                bank_state=opt("Bank State"), pincode=pin.split(".")[0] if pin else None,
                verification_state=opt("State of Verification"), notes=opt("Notes"),
                loan_type=opt("Loan/Product Type"),
                report_type=rt, assigned_address=str(cell(row, "Assigned Address") or "").strip() or "Not provided",
                city=opt("City"), state=opt("State"),
                priority=(str(cell(row, "Priority") or "").strip() or "Medium"), due_at=due_at,
            )
            doc = create_case_doc(body, client, branch, ctx["user"])
            doc["internal_case_id"] = await core.next_internal_case_id()
            doc["timeline"] = [tl("case_created", ctx["user"], {"source": f"excel import row {n}"})]
            doc["source"] = "excel_import"
            await core.db.cases.insert_one(doc)
            created += 1
        except Exception as exc:
            errors.append(f"Row {n}: {exc}")
    await core.audit(ctx["user"], "cases_imported", "case", "bulk", {"created": created, "errors": len(errors)}, request)
    return {"created": created, "errors": errors}


@router.get("/cases")
async def list_cases(request: Request, status: str | None = None, client_id: str | None = None,
                     branch_id: str | None = None, state: str | None = None, city: str | None = None,
                     agent_id: str | None = None, report_type: str | None = None, priority: str | None = None,
                     q: str | None = None, due: str | None = None, sla: str | None = None,
                     from_date: str | None = None, to_date: str | None = None,
                     supervisor_id: str | None = None, flagged: int = 0, client_case_id: str | None = None,
                     internal_case_id: str | None = None, applicant: str | None = None, loan_type: str | None = None,
                     sort: str = "created_at", order: str = "desc",
                     page: int = 1, limit: int = 25, ctx=Depends(security.staff)):
    query = dict(core.LIVE_CASE_FILTER)
    if supervisor_id and ctx["user"]["role"] == "super_admin":
        try:
            sup = await core.db.users.find_one({"_id": ObjectId(supervisor_id), "role": "supervisor"})
        except Exception:
            sup = None
        if sup:
            sq = security.case_scope_query(sup)
            if sq:
                query = {"$and": [query, sq]}
    if flagged:
        query["flags.0"] = {"$exists": True}
    if client_case_id:
        query["client_case_id"] = {"$regex": re.escape(client_case_id), "$options": "i"}
    if internal_case_id:
        query["internal_case_id"] = {"$regex": re.escape(internal_case_id), "$options": "i"}
    if applicant:
        query["applicant_name"] = {"$regex": re.escape(applicant), "$options": "i"}
    if loan_type:
        query["loan_type"] = loan_type
    if status:
        query["status"] = {"$in": [s.strip() for s in status.split(",")]}
    if client_id:
        query["client_id"] = client_id
    if branch_id:
        query["branch_id"] = branch_id
    if state:
        query["state"] = state
    if city:
        query["city"] = city
    if agent_id:
        query["assigned_agent_id"] = agent_id
    if report_type:
        query["report_type"] = report_type
    if priority:
        query["priority"] = priority
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        text_or = [{"applicant_name": rx}, {"internal_case_id": rx}, {"client_case_id": rx}, {"co_applicant_name": rx}]
        # keep supervisor scope ($or) intact: combine with $and instead of overwriting
        query.setdefault("$and", []).append({"$or": text_or})
    if due == "overdue":
        query["due_at"] = {"$lt": core.now()}
        query["status"] = {"$in": core.ACTIVE_STATUSES}
    elif due == "today":
        start = core.now().replace(hour=0, minute=0, second=0, microsecond=0)
        query["due_at"] = {"$gte": start, "$lt": start + timedelta(days=1)}
        query["status"] = {"$in": core.ACTIVE_STATUSES}
    if from_date or to_date:
        rng = {}
        if from_date:
            rng["$gte"] = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
        if to_date:
            rng["$lte"] = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)
        query["created_at"] = rng
    if sla == "overdue":
        query["due_at"] = {"$lt": core.now()}
        query["status"] = {"$in": core.ACTIVE_STATUSES}
    elif sla == "due_24h":
        query["due_at"] = {"$gte": core.now(), "$lt": core.now() + timedelta(hours=24)}
        query["status"] = {"$in": core.ACTIVE_STATUSES}
    elif sla == "within":
        query["$expr"] = {"$or": [{"$eq": ["$due_at", None]}, {"$gte": ["$due_at", core.now()]}]}
    if status == "pending_review":
        query["status"] = {"$in": ["submitted", "under_review"]}
    # Role scope is ANDed last so no filter parameter can widen it (e.g. ?agent_id= from an agent).
    scope = security.case_scope_query(ctx["user"])
    if scope:
        query = {"$and": [query, scope]}

    sort_fields = {"created_at", "due_at", "internal_case_id", "applicant_name", "client_name", "status",
                   "priority", "city", "assigned_agent_name", "report_type", "updated_at"}
    sort_key = sort if sort in sort_fields else "created_at"
    total = await core.db.cases.count_documents(query)
    cursor = core.db.cases.find(query).sort(sort_key, 1 if order == "asc" else -1).skip((page - 1) * limit).limit(min(limit, 100))
    items = []
    async for c in cursor:
        items.append(security.case_public(c))
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/cases/{case_id}")
async def get_case(case_id: str, request: Request, ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    await core.audit(ctx["user"], "case_viewed", "case", str(case["_id"]), {}, request)
    d = security.case_public(case)
    report = await core.current_report(str(case["_id"]))
    d["latest_report"] = core.clean(report) if report else None
    return d


class AssignIn(BaseModel):
    agent_id: str
    reason: str | None = None


@router.post("/cases/{case_id}/assign")
async def assign_case(case_id: str, body: AssignIn, request: Request, ctx=Depends(security.admin_sup)):
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    try:
        agent = await core.db.users.find_one({"_id": ObjectId(body.agent_id), "role": "agent"})
    except Exception:
        agent = await core.db.users.find_one({"agent_id": body.agent_id.upper(), "role": "agent"})
    if not agent or agent.get("disabled"):
        raise HTTPException(400, "Agent not found or inactive")
    reassign = bool(case.get("assigned_agent_id"))
    updates = {
        "assigned_agent_id": str(agent["_id"]), "assigned_agent_name": agent.get("name"),
        "status": "assigned" if case.get("status") in ("new", "assigned", "returned") else case["status"],
        "updated_at": core.now(),
    }
    await core.db.cases.update_one({"_id": case["_id"]}, {"$set": updates, "$push": {
        "timeline": tl("reassigned" if reassign else "assigned", ctx["user"],
                       {"agent": agent["name"], "reason": body.reason or ""})}})
    await core.audit(ctx["user"], "case_reassigned" if reassign else "case_assigned", "case", str(case["_id"]),
                     {"agent": agent["name"]}, request)
    from requests_routes import notify
    await notify(str(agent["_id"]), "Case reassigned to you" if reassign else "New case assigned",
                 f"{case['internal_case_id']} · {case.get('applicant_name')} · {case.get('client_name')}", str(case["_id"]), "assignment")
    await core.db.cases.update_one({"_id": case["_id"]}, {"$set": {"agent_response": None}})
    return core.clean(await core.db.cases.find_one({"_id": case["_id"]}))


class DeleteCaseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


async def _soft_delete_case(case_id: str, reason: str, request: Request, user: dict) -> dict:
    """Super Admin case deletion is a SOFT delete: the record, its reports, call logs, audit history and the evidence
    files in R2 storage are all kept (recoverable and auditable; the retention policy still governs final purging).
    The case only disappears from normal lists, dashboards, search, exports and reports."""
    case = await get_case_or_404(case_id)
    if case.get("is_draft"):
        raise HTTPException(404, "Case not found")
    now = core.now()
    reason = reason.strip()
    info = {"deleted_by": str(user["_id"]), "deleted_by_name": user.get("name"), "deleted_reason": reason,
            "status_at_deletion": case.get("status")}
    res = await core.db.cases.update_one({"_id": case["_id"], "deleted_at": None}, {
        "$set": {"deleted_at": now, "updated_at": now, **info},
        "$push": {"timeline": tl("case_deleted", user, {"reason": reason, "soft_delete": True})}})
    if not res.modified_count:
        raise HTTPException(404, "Case not found")
    await core.audit(user, "case_deleted", "case", str(case["_id"]), {
        "soft_delete": True, "internal_case_id": case.get("internal_case_id"), "client_case_id": case.get("client_case_id"),
        "applicant_name": case.get("applicant_name"), "reason": reason, "deleted_by": str(user["_id"]),
        "deleted_at": now.isoformat(), "status_at_deletion": case.get("status"),
        "evidence_files_kept": await core.db.evidence.count_documents({"case_id": str(case["_id"])})}, request)
    return {"ok": True, "id": str(case["_id"]), "internal_case_id": case.get("internal_case_id"), "deleted_at": now}


@router.post("/cases/{case_id}/delete")
async def delete_case(case_id: str, body: DeleteCaseIn, request: Request, ctx=Depends(security.admin_only)):
    """Super Admin only (enforced here on the server, not just hidden in the UI). A reason is mandatory."""
    return await _soft_delete_case(case_id, body.reason, request, ctx["user"])


@router.delete("/cases/{case_id}")
async def delete_case_legacy(case_id: str, request: Request, reason: str | None = None, ctx=Depends(security.admin_only)):
    if not reason or len(reason.strip()) < 3:
        raise HTTPException(400, "A reason for deletion is required")
    return await _soft_delete_case(case_id, reason, request, ctx["user"])


@router.get("/cases-deleted")
async def list_deleted_cases(limit: int = 100, ctx=Depends(security.admin_only)):
    """Super Admin view of soft-deleted cases (audit and recovery)."""
    q = {"deleted_at": {"$ne": None}, "is_draft": {"$ne": True}}
    items = []
    async for c in core.db.cases.find(q).sort("deleted_at", -1).limit(min(limit, 500)):
        d = security.case_public(c)
        items.append({k: d.get(k) for k in ("id", "internal_case_id", "client_case_id", "applicant_name", "client_name",
                                            "report_type_name", "status", "source", "assigned_agent_name", "created_at",
                                            "deleted_at", "deleted_by", "deleted_by_name", "deleted_reason")})
    return {"items": items, "total": await core.db.cases.count_documents(q)}


class RestoreCaseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/cases/{case_id}/restore")
async def restore_case(case_id: str, body: RestoreCaseIn, request: Request, ctx=Depends(security.admin_only)):
    try:
        case = await core.db.cases.find_one({"_id": ObjectId(case_id)})
    except Exception:
        case = None
    if not case or not case.get("deleted_at") or case.get("is_draft"):
        raise HTTPException(404, "Deleted case not found")
    u = ctx["user"]
    now = core.now()
    await core.db.cases.update_one({"_id": case["_id"]}, {
        "$set": {"deleted_at": None, "updated_at": now, "restored_at": now, "restored_by": str(u["_id"])},
        "$push": {"timeline": tl("case_restored", u, {"reason": body.reason.strip(), "previously_deleted_by": case.get("deleted_by_name"),
                                                       "previous_deletion_reason": case.get("deleted_reason")})}})
    await core.audit(u, "case_restored", "case", str(case["_id"]), {"internal_case_id": case.get("internal_case_id"),
                                                                     "reason": body.reason.strip()}, request)
    return security.case_public(await core.db.cases.find_one({"_id": case["_id"]}))


@router.get("/cases/{case_id}/timeline")
async def case_timeline(case_id: str, ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    return {"items": case.get("timeline") or []}


@router.get("/cases/{case_id}/audit")
async def case_audit(case_id: str, ctx=Depends(security.admin_sup)):
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    rids = [str(r["_id"]) async for r in core.db.reports.find({"case_id": str(case["_id"])}, {"_id": 1})]
    q = {"entity_id": {"$in": [str(case["_id"])] + rids}}
    items = [core.clean(a) async for a in core.db.audit_logs.find(q).sort("created_at", -1).limit(500)]
    exports = [a for a in items if a.get("action") in ("report_exported", "evidence_downloaded")]
    return {"items": items, "exports": exports}


class VisitStartIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy: float | None = None
    mocked: bool | None = None
    fix_at: str | None = None


@router.post("/cases/{case_id}/visit-start")
async def visit_start(case_id: str, body: VisitStartIn, request: Request, ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    # The first recorded visit start is kept; it is not overwritten by later GPS refreshes
    # (a new visit may be recorded only after the report was returned for correction).
    if case.get("visit") and case.get("status") != "returned":
        return core.clean(case)
    updates = {"visit": {"started_at": core.now(), "lat": body.lat, "lon": body.lon, "accuracy": body.accuracy,
                         "mocked": body.mocked, "fix_at": body.fix_at},
               "updated_at": core.now()}
    if case.get("status") in ("assigned", "new"):
        updates["status"] = "in_progress"
    await core.db.cases.update_one({"_id": case["_id"]}, {"$set": updates, "$push": {
        "timeline": tl("visit_started", ctx["user"], {"lat": body.lat, "lon": body.lon, "accuracy": body.accuracy})}})
    await core.audit(ctx["user"], "visit_started", "case", str(case["_id"]), {}, request)
    return core.clean(await core.db.cases.find_one({"_id": case["_id"]}))


class LocationCorrectionIn(BaseModel):
    assigned_address: str | None = Field(default=None, max_length=1000)
    assigned_lat: float | None = Field(default=None, ge=-90, le=90)
    assigned_lon: float | None = Field(default=None, ge=-180, le=180)
    candidate: int | None = Field(default=None, ge=0, le=9)  # confirm one of the case's location_candidates
    reason: str = Field(min_length=3, max_length=500)


_LOC_KEYS = ("assigned_address", "assigned_lat", "assigned_lon", "location_precision", "location_source", "location_status")


@router.post("/cases/{case_id}/location/lookup")
async def lookup_case_location(case_id: str, request: Request, ctx=Depends(security.admin_sup)):
    """Super Admin / Supervisor: look the assigned address up now. A verified match becomes the reference location;
    otherwise the case is marked 'needs_pin' and any unverified candidates are listed for confirmation. Audited."""
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    if case.get("location_status") in ("pinned", "confirmed"):
        raise HTTPException(409, "The reference location was set by a supervisor. Pin a new point or correct the address instead.")
    if not (case.get("assigned_address") or "").strip():
        raise HTTPException(400, "The case has no assigned address to look up")
    if geocoding.PROVIDER == "off":
        raise HTTPException(400, "Automatic address lookup is switched off; pin the location instead")
    try:
        res = await asyncio.to_thread(geocoding.geocode_case_address, case)
    except Exception as exc:
        raise HTTPException(502, f"The address lookup service did not respond ({type(exc).__name__}). Try again or pin the location.")
    upd = geocoding.location_update(res)
    before = {k: case.get(k) for k in _LOC_KEYS}
    after = {k: upd.get(k, case.get(k)) for k in _LOC_KEYS}
    upd["updated_at"] = core.now()
    await core.db.cases.update_one({"_id": case["_id"]}, {"$set": upd, "$push": {"timeline": tl(
        "case_location_lookup", ctx["user"], {"result": upd["location_status"], "precision": upd.get("location_precision"),
                                              "note": upd.get("location_note")})}})
    await core.audit(ctx["user"], "case_location_lookup", "case", str(case["_id"]),
                     {"before": before, "after": after, "note": upd.get("location_note"),
                      "candidates": len(upd.get("location_candidates") or [])}, request)
    return security.case_public(await core.db.cases.find_one({"_id": case["_id"]}))


@router.post("/cases/{case_id}/location")
async def correct_case_location(case_id: str, body: LocationCorrectionIn, request: Request, ctx=Depends(security.admin_sup)):
    """Super Admin / Supervisor correction of the assigned address and/or reference pin. Fully audited."""
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    if (body.assigned_lat is None) != (body.assigned_lon is None):
        raise HTTPException(400, "Provide both latitude and longitude, or neither")
    if body.candidate is not None and body.assigned_lat is not None:
        raise HTTPException(400, "Either confirm a candidate or pin coordinates, not both")
    new_addr = (body.assigned_address or "").strip() or None
    updates, before, after = {}, {}, {}
    if new_addr and new_addr != case.get("assigned_address"):
        updates["assigned_address"] = new_addr
    actor = ctx["user"].get("name") or "supervisor"
    if body.candidate is not None:
        cands = case.get("location_candidates") or []
        if "assigned_address" in updates:
            raise HTTPException(400, "Candidates belong to the old address; look the new address up first")
        if body.candidate >= len(cands):
            raise HTTPException(400, "No such location candidate")
        cand = cands[body.candidate]
        # Confirming keeps the candidate's own precision: a confirmed PIN centre is still only PIN-level.
        updates.update({"assigned_lat": cand["lat"], "assigned_lon": cand["lon"], "location_source": "confirmed_candidate",
                        "location_status": "confirmed", "location_precision": cand.get("precision") or "pincode",
                        "location_note": f"Confirmed by {actor}: {(cand.get('label') or '')[:160]}"})
    elif body.assigned_lat is not None:
        updates.update({"assigned_lat": body.assigned_lat, "assigned_lon": body.assigned_lon,
                        "location_source": "manual", "location_status": "pinned", "location_precision": "exact",
                        "location_note": f"Pinned by {actor}"})
    elif "assigned_address" in updates:
        # address changed without a pin: look the new address up again (old pin is no longer valid)
        updates.update({"assigned_lat": None, "assigned_lon": None, "location_source": None,
                        "location_status": "pending" if geocoding.PROVIDER != "off" else "missing",
                        "location_precision": None, "location_note": None, "location_candidates": []})
    if not updates:
        raise HTTPException(400, "Nothing to change")
    for k in _LOC_KEYS:
        if k in updates:
            before[k], after[k] = case.get(k), updates[k]
    updates["updated_at"] = core.now()
    await core.db.cases.update_one({"_id": case["_id"]}, {"$set": updates, "$push": {"timeline": tl(
        "address_location_corrected", ctx["user"], {"reason": body.reason, "before": before, "after": after})}})
    await core.audit(ctx["user"], "case_location_corrected", "case", str(case["_id"]),
                     {"reason": body.reason, "before": before, "after": after}, request)
    return security.case_public(await core.db.cases.find_one({"_id": case["_id"]}))


class CallLogIn(BaseModel):
    phone_number: str = Field(min_length=1, max_length=30)
    result: str
    person_met: str | None = None
    relationship: str | None = None
    info_confirmed: str | None = None
    notes: str | None = None
    next_attempt_at: str | None = None


@router.post("/cases/{case_id}/call-logs")
async def add_call_log(case_id: str, body: CallLogIn, request: Request, ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    if body.result not in ("Confirmed", "Busy", "No Response", "Switched Off", "Call Later", "Invalid Number", "Refused", "Other"):
        raise HTTPException(400, "Invalid call result")
    doc = {
        "case_id": str(case["_id"]), "agent_id": str(ctx["user"]["_id"]), "agent_name": ctx["user"]["name"],
        "phone_number": body.phone_number, "result": body.result, "person_met": body.person_met,
        "relationship": body.relationship, "info_confirmed": body.info_confirmed, "notes": body.notes,
        "next_attempt_at": body.next_attempt_at, "attempt_at": core.now(),
    }
    res = await core.db.call_logs.insert_one(doc)
    await core.db.cases.update_one({"_id": case["_id"]}, {"$push": {
        "timeline": tl("call_attempt", ctx["user"], {"result": body.result, "to": body.phone_number})}})
    await core.audit(ctx["user"], "call_attempt_logged", "case", str(case["_id"]), {"result": body.result}, request)
    return core.clean(await core.db.call_logs.find_one({"_id": res.inserted_id}))


@router.get("/cases/{case_id}/call-logs")
async def list_call_logs(case_id: str, ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    items = [core.clean(c) async for c in core.db.call_logs.find({"case_id": str(case["_id"])}).sort("attempt_at", -1)]
    return {"items": items}


# ---------------------------------------------------------------- agent "Create New Verification"
# The agent picks a Request Type (same options as Allocate New Verification) and then fills the normal assigned-case
# verification form. Choosing / changing the Request Type does NOT create a case: it only opens a private DRAFT
# workspace (is_draft=True, no Internal Case ID, invisible in every case list, dashboard, search, export and alert) so
# photos, GPS and draft saves have somewhere to live. The case is created - and its unique Internal Case ID generated -
# only when the agent presses the final Submit (reports_routes.submit_report -> promote_agent_draft).
# Supervisor-assigned cases and Allocate New Verification are not affected by any of this.
class AgentCreateIn(BaseModel):
    request_type: str
    draft_key: str | None = Field(default=None, max_length=64)  # client idempotency key (double tap / network retry)


def _req_type_map() -> dict:
    from requests_routes import REQ_TYPES  # same Request Type -> report type mapping as the request workflow
    return REQ_TYPES


async def _agent_created_case_for(case_id: str, user: dict) -> dict:
    case = await get_case_or_404(case_id)
    if case.get("source") != "agent_created" or case.get("created_by") != str(user["_id"]) \
            or case.get("assigned_agent_id") != str(user["_id"]):
        raise HTTPException(403, "Only the agent who created this verification can change it")
    return case


async def _is_untouched_draft(case: dict) -> bool:
    cid = str(case["_id"])
    return not (case.get("visit") or await core.db.evidence.count_documents({"case_id": cid})
                or await core.db.reports.count_documents({"case_id": cid})
                or await core.db.call_logs.count_documents({"case_id": cid}))


@router.post("/cases/agent-create")
async def agent_create_case(body: AgentCreateIn, request: Request, ctx=Depends(security.require_roles("agent"))):
    """Open (or reuse) the agent's DRAFT verification workspace for the chosen Request Type. Creates no case."""
    u = ctx["user"]
    types = _req_type_map()
    if body.request_type not in types:
        raise HTTPException(400, "Choose a request type")
    now = core.now()
    mine = {"is_draft": True, "deleted_at": None, "created_by": str(u["_id"]), "source": "agent_created"}
    reuse = None
    if body.draft_key:  # same visit of the screen (double tap / network retry) -> same draft, never a second one
        reuse = await core.db.cases.find_one({**mine, "draft_key": body.draft_key})
    if reuse:
        sets = {"updated_at": now}
        if body.draft_key:
            sets["draft_key"] = body.draft_key
        if reuse.get("request_type") != body.request_type and await _is_untouched_draft(reuse):
            sets.update({"request_type": body.request_type, "report_type": types[body.request_type]})
        await core.db.cases.update_one({"_id": reuse["_id"]}, {"$set": sets})
        return security.case_public(await core.db.cases.find_one({"_id": reuse["_id"]}))
    oid = ObjectId()
    doc = {
        "_id": oid, "is_draft": True, "draft_key": body.draft_key,
        # placeholder only (the unique index needs a value); replaced by the real CSV-###### Internal Case ID on Submit
        "internal_case_id": f"DRAFT-{oid}", "client_case_id": None, "client_id": None, "client_name": "",
        "branch_id": None, "branch_name": "", "applicant_name": "", "co_applicant_name": None,
        "report_type": types[body.request_type], "request_type": body.request_type, "assigned_address": "",
        "city": None, "state": None, "priority": "Medium", "due_at": None, "status": "assigned",
        "assigned_agent_id": str(u["_id"]), "assigned_agent_name": u["name"], "agent_response": "accept", "agent_response_at": now,
        "created_by": str(u["_id"]), "created_by_role": "agent", "source": "agent_created",
        "assigned_at": now, "flags": [], "created_at": now, "updated_at": now, "deleted_at": None,
        "location_source": None, "location_status": "awaiting_address", "location_precision": None,
        "timeline": [tl("verification_draft_started", u, {"source": "Create New Verification", "request_type": body.request_type})],
    }
    await core.db.cases.insert_one(doc)
    await core.audit(u, "agent_verification_draft_started", "case", str(oid), {"request_type": body.request_type}, request)
    return security.case_public(await core.db.cases.find_one({"_id": oid}))


@router.get("/agent/verification-drafts")  # not under /cases/: the GET /cases/{case_id} route is registered first
async def agent_drafts(ctx=Depends(security.require_roles("agent"))):
    """The agent's own unfinished (never submitted) Create New Verification drafts, to resume or discard."""
    u = ctx["user"]
    items = []
    async for c in core.db.cases.find({"is_draft": True, "deleted_at": None, "created_by": str(u["_id"])}).sort("updated_at", -1).limit(50):
        d = security.case_public(c)
        d["photo_count"] = await core.db.evidence.count_documents({"case_id": str(c["_id"])})
        items.append(d)
    return {"items": items}


async def promote_agent_draft(case: dict, user: dict, request: Request | None, now) -> dict | None:
    """Turn a submitted draft into a real case: generate the mandatory unique Internal Case ID, make it visible and
    notify supervisors. Called by submit_report only after it atomically claimed the submission (so it runs once)."""
    if not case.get("is_draft"):
        return None
    internal_id = await core.next_internal_case_id()
    res = await core.db.cases.update_one({"_id": case["_id"], "is_draft": True}, {
        "$set": {"is_draft": False, "internal_case_id": internal_id, "created_at": now, "updated_at": now,
                 "due_at": case.get("due_at") or now + timedelta(hours=48), "case_created_at": now},
        "$unset": {"draft_key": ""},
        "$push": {"timeline": {"$each": [
            tl("case_created", user, {"source": "agent created (Create New Verification) on final submit",
                                      "request_type": case.get("request_type"), "internal_case_id": internal_id}),
            tl("assigned", user, {"agent": user["name"], "self_created": True})]}}})
    if not res.modified_count:
        return None
    await core.audit(user, "case_created_by_agent", "case", str(case["_id"]),
                     {"internal_case_id": internal_id, "request_type": case.get("request_type"), "on": "final_submit"}, request)
    from requests_routes import notify
    async for sup in core.db.users.find({"role": "supervisor", "disabled": {"$ne": True}}):
        sc = sup.get("scope") or {}
        if not any(sc.get(k) for k in ("client_ids", "states", "cities", "branch_ids", "agent_ids")) or str(user["_id"]) in (sc.get("agent_ids") or []):
            await notify(str(sup["_id"]), "Agent submitted a new verification",
                         f"{user['name']} created and submitted {internal_id} ({case.get('request_type')})", str(case["_id"]), "request")
    return await core.db.cases.find_one({"_id": case["_id"]})


@router.post("/cases/{case_id}/request-type")
async def change_request_type(case_id: str, body: AgentCreateIn, request: Request, ctx=Depends(security.require_roles("agent"))):
    u = ctx["user"]
    case = await _agent_created_case_for(case_id, u)
    types = _req_type_map()
    if body.request_type not in types:
        raise HTTPException(400, "Choose a request type")
    if case.get("status") not in ("new", "assigned", "in_progress"):
        raise HTTPException(400, "The request type cannot be changed after submission")
    if await core.db.evidence.count_documents({"case_id": str(case["_id"])}):
        raise HTTPException(400, "The request type cannot be changed after photos have been captured")
    if await core.db.reports.count_documents({"case_id": str(case["_id"]), "status": {"$ne": "draft"}}):
        raise HTTPException(400, "The request type cannot be changed after submission")
    await core.db.reports.delete_many({"case_id": str(case["_id"]), "status": "draft"})  # draft belonged to the old form
    await core.db.cases.update_one({"_id": case["_id"]}, {
        "$set": {"report_type": types[body.request_type], "request_type": body.request_type, "updated_at": core.now()},
        "$push": {"timeline": tl("request_type_changed", u, {"from": case.get("request_type"), "to": body.request_type})}})
    await core.audit(u, "agent_case_request_type_changed", "case", str(case["_id"]), {"to": body.request_type}, request)
    return security.case_public(await core.db.cases.find_one({"_id": case["_id"]}))


@router.post("/cases/{case_id}/discard")
async def discard_agent_case(case_id: str, request: Request, ctx=Depends(security.require_roles("agent"))):
    """An agent may discard a verification they created themselves, only before it was ever submitted (soft delete)."""
    u = ctx["user"]
    case = await _agent_created_case_for(case_id, u)
    if case.get("status") not in ("new", "assigned", "in_progress") or \
            await core.db.reports.count_documents({"case_id": str(case["_id"]), "status": {"$ne": "draft"}}):
        raise HTTPException(400, "Only an unsubmitted verification can be discarded")
    await core.db.cases.update_one({"_id": case["_id"]}, {"$set": {"deleted_at": core.now(), "updated_at": core.now()},
                                                          "$push": {"timeline": tl("discarded_by_agent", u, {})}})
    await core.audit(u, "agent_case_discarded", "case", str(case["_id"]), {"soft_delete": True}, request)
    return {"ok": True}


AGENT_SYNC_FIELDS = ("applicant_name", "co_applicant_name", "client_name", "branch_name", "client_case_id", "assigned_address")


async def sync_agent_created_case(case: dict, data: dict, user: dict) -> dict:
    """For agent-created verifications the agent supplies the case details in the verification form; mirror them onto
    the case record (supervisor-assigned cases never take case details from the agent)."""
    if case.get("source") != "agent_created" or user.get("role") != "agent":
        return case
    updates = {}
    for k in AGENT_SYNC_FIELDS:
        v = str((data or {}).get(k) or "").strip()[:500]
        if v and v != (case.get(k) or ""):
            updates[k] = v
    if not updates:
        return case
    if "client_name" in updates:
        client = await core.db.clients.find_one({"name": {"$regex": f"^{re.escape(updates['client_name'])}$", "$options": "i"}})
        updates["client_id"] = str(client["_id"]) if client else None
    if "assigned_address" in updates:
        updates.update({"assigned_lat": None, "assigned_lon": None, "location_source": None, "location_precision": None,
                        "location_note": None, "location_candidates": [],
                        "location_status": "pending" if geocoding.PROVIDER != "off" else "missing"})
    updates["updated_at"] = core.now()
    await core.db.cases.update_one({"_id": case["_id"]}, {"$set": updates, "$push": {"timeline": tl(
        "agent_case_details_updated", user, {"fields": sorted(k for k in updates if k in AGENT_SYNC_FIELDS)})}})
    return await core.db.cases.find_one({"_id": case["_id"]})
