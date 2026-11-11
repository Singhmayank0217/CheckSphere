"""Case routes: create, Excel import, list, detail, assign, timeline, visit start, call logs."""
import io
import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field

import core
import security
from report_config import REPORT_TYPES

router = APIRouter()


def tl(action: str, user, details: dict | None = None) -> dict:
    return {"action": action, "by": str(user.get("_id") or ""), "by_name": (user or {}).get("name") or "system",
            "at": core.now(), "details": details or {}}


async def can_access_case(user: dict, case: dict) -> bool:
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


class CaseCreate(BaseModel):
    client_case_id: str = Field(min_length=1, max_length=120)
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


def create_case_doc(body: CaseCreate, client: dict, branch: dict | None, user) -> dict:
    doc = {
        "client_case_id": body.client_case_id, "client_id": str(client["_id"]), "client_name": client["name"],
        "branch_id": (str(branch["_id"]) if branch else None), "branch_name": (branch or {}).get("name"),
        "applicant_name": body.applicant_name, "co_applicant_name": body.co_applicant_name,
        "loan_type": body.loan_type, "report_type": body.report_type,
        "assigned_address": body.assigned_address, "city": body.city or (branch or {}).get("city"),
        "state": body.state or (branch or {}).get("state"), "priority": body.priority or "Medium",
        "due_at": body.due_at, "assigned_lat": body.assigned_lat, "assigned_lon": body.assigned_lon,
        "seller_name": body.seller_name, "primary_phone": body.primary_phone, "alt_phone": body.alt_phone,
        "bank_state": body.bank_state, "pincode": body.pincode, "verification_state": body.verification_state, "notes": body.notes,
        "status": "new", "created_by": str(user["_id"]), "flags": [], "timeline": [],
        "created_at": core.now(), "updated_at": core.now(),
    }
    return doc


@router.post("/cases")
async def create_case(body: CaseCreate, request: Request, ctx=Depends(security.admin_only)):
    client = await core.db.clients.find_one({"_id": ObjectId(body.client_id)})
    if not client:
        raise HTTPException(400, "Client not found")
    if body.report_type not in REPORT_TYPES:
        raise HTTPException(400, "Unknown report type")
    if not (body.primary_phone or "").strip():
        raise HTTPException(400, "Primary contact number is required")
    if body.pincode and not re.fullmatch(r"\d{6}", body.pincode.strip()):
        raise HTTPException(400, "Pincode must be 6 digits")
    branch = None
    if body.branch_id:
        branch = await core.db.branches.find_one({"_id": ObjectId(body.branch_id)})
    seq = await core.next_seq("case_seq")
    doc = create_case_doc(body, client, branch, ctx["user"])
    doc["internal_case_id"] = f"CSV-{seq:06d}"
    doc["timeline"] = [tl("case_created", ctx["user"], {"source": "manual"})]
    res = await core.db.cases.insert_one(doc)
    await core.audit(ctx["user"], "case_created", "case", str(res.inserted_id), {"internal_case_id": doc["internal_case_id"]}, request)
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
            rt_name = str(cell(row, "Report Type") or "").strip().lower()
            rt = type_by_name.get(rt_name)
            if not rt:
                errors.append(f"Row {n}: unknown report type '{rt_name}'")
                continue
            branch_name = str(cell(row, "Branch Name") or "").strip()
            branch = None
            if branch_name:
                branch = await core.db.branches.find_one({"client_id": str(client["_id"]),
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
                client_case_id=str(cell(row, "Client Case ID") or f"IMP-{n}"),
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
            seq = await core.next_seq("case_seq")
            doc = create_case_doc(body, client, branch, ctx["user"])
            doc["internal_case_id"] = f"CSV-{seq:06d}"
            doc["timeline"] = [tl("case_created", ctx["user"], {"source": f"excel import row {n}"})]
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
    query = {"deleted_at": None}
    query.update(security.case_scope_query(ctx["user"]))
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
    report = await core.db.reports.find_one({"case_id": str(case["_id"])}, sort=[("version", -1)])
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


@router.delete("/cases/{case_id}")
async def delete_case(case_id: str, request: Request, ctx=Depends(security.admin_only)):
    case = await get_case_or_404(case_id)
    await core.db.cases.update_one({"_id": case["_id"]}, {"$set": {"deleted_at": core.now(), "updated_at": core.now()}})
    await core.audit(ctx["user"], "case_deleted", "case", str(case["_id"]), {"soft_delete": True}, request)
    return {"ok": True}


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
    lat: float
    lon: float
    accuracy: float | None = None


@router.post("/cases/{case_id}/visit-start")
async def visit_start(case_id: str, body: VisitStartIn, request: Request, ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if ctx["user"]["role"] == "agent" and case.get("assigned_agent_id") != str(ctx["user"]["_id"]):
        raise HTTPException(403, "Not allowed")
    updates = {"visit": {"started_at": core.now(), "lat": body.lat, "lon": body.lon, "accuracy": body.accuracy},
               "updated_at": core.now()}
    if case.get("status") in ("assigned", "new"):
        updates["status"] = "in_progress"
    await core.db.cases.update_one({"_id": case["_id"]}, {"$set": updates, "$push": {
        "timeline": tl("visit_started", ctx["user"], {"lat": body.lat, "lon": body.lon, "accuracy": body.accuracy})}})
    await core.audit(ctx["user"], "visit_started", "case", str(case["_id"]), {}, request)
    return core.clean(await core.db.cases.find_one({"_id": case["_id"]}))


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
    if ctx["user"]["role"] == "agent" and case.get("assigned_agent_id") != str(ctx["user"]["_id"]):
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
