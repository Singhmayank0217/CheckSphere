"""Report routes: draft save, submission with controls, review workflow, versions, flags."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import core
import security
from cases_routes import can_access_case, get_case_or_404, tl
from report_config import config_for

router = APIRouter()


def validate_submission(data, gps, declaration, config, evidence, call_count, settings):
    missing, problems = [], []
    for section in config.get("sections", []):
        for f in section.get("fields", []):
            if f.get("required") and not str(data.get(f["key"]) or "").strip():
                missing.append(f["label"])
    if config.get("requires_gps"):
        if not gps or gps.get("lat") in (None, "") or gps.get("lon") in (None, ""):
            problems.append("GPS coordinates are required for physical verification")
        elif gps.get("accuracy") in (None, ""):
            problems.append("GPS accuracy is required")
    have = {e.get("slot") for e in evidence if e.get("kind") == "photo"}
    for s in config.get("photo_slots", []):
        if s.get("required") and s["key"] not in have:
            problems.append(f"Required photo missing: {s['label']}")
    if config.get("min_call_attempts", 0) and call_count < config["min_call_attempts"]:
        problems.append(f"Minimum {config['min_call_attempts']} call attempts required ({call_count} logged)")
    if not declaration:
        problems.append("Agent declaration is required before submission")
    blocked = core.scan_data_for_blocked(data, settings.get("blocked_words") or [])
    return missing, problems, blocked


async def compute_flags(case, data, gps, settings):
    flags = []
    if case.get("report_type") and config_for(case["report_type"], settings).get("requires_gps"):
        if not case.get("visit"):
            flags.append("no_visit_started")
    if not gps or not gps.get("lat"):
        flags.append("missing_gps")
    else:
        acc = gps.get("accuracy")
        if acc is not None and float(acc) > float(settings.get("flag_accuracy_m", 150)):
            flags.append("low_gps_accuracy")
        if case.get("assigned_lat") and case.get("assigned_lon"):
            dist = core.haversine_m(case["assigned_lat"], case["assigned_lon"], gps.get("lat"), gps.get("lon"))
            if dist > float(settings.get("flag_distance_m", 500)):
                flags.append("far_from_assigned_address")
    if case.get("due_at") and core.now() > case["due_at"]:
        flags.append("late_submission")
    # Impossible travel / same place-time vs agent's previous submissions
    agent_id = case.get("assigned_agent_id")
    async for prev in core.db.reports.find({"case_id": {"$ne": str(case["_id"])}, "status": {"$in": ["submitted", "under_review", "approved"]},
                                            "submitted_by": agent_id, "gps.lat": {"$type": ["double", "int"]}}).sort("submitted_at", -1).limit(5):
        prev_gps = prev.get("gps") or {}
        prev_at = prev.get("submitted_at")
        if not prev_at or not prev_gps.get("lat"):
            continue
        dist = core.haversine_m(prev_gps.get("lat"), prev_gps.get("lon"), gps.get("lat"), gps.get("lon"))
        gap_h = abs((core.now() - prev_at).total_seconds()) / 3600.0
        if 0 < gap_h <= 12 and dist >= 0:
            speed = (dist / 1000.0) / max(gap_h, 1e-6)
            if speed > float(settings.get("flag_travel_kmh", 500)):
                flags.append("impossible_travel")
        if gap_h * 60 <= float(settings.get("flag_same_place_min", 10)) and 0 <= dist < 100:
            flags.append("multiple_same_place_time")
        break
    return sorted(set(flags))


class DraftIn(BaseModel):
    data: dict = Field(default_factory=dict)
    gps: dict = Field(default_factory=dict)
    declaration: bool = False
    offline_synced: bool = False


async def latest_report(case_id: str):
    return await core.db.reports.find_one({"case_id": case_id}, sort=[("version", -1)])


def agent_can_edit(case: dict) -> bool:
    return case.get("status") in ("new", "assigned", "in_progress", "returned")


@router.get("/reports/case/{case_id}")
async def report_context(case_id: str, reveal: int = 0, ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    settings = await core.get_settings()
    config = config_for(case["report_type"], settings)
    report = await latest_report(str(case["_id"]))
    evidence = [core.clean(e) async for e in core.db.evidence.find({"case_id": str(case["_id"])}).sort("created_at", -1)]
    call_logs = [core.clean(c) async for c in core.db.call_logs.find({"case_id": str(case["_id"])}).sort("attempt_at", -1)]

    blocked_missing, problems, blocked_words = ([], [], {})
    if report and report.get("status") == "draft":
        evidence_for_check = [e for e in evidence if e.get("kind") == "photo"]
        blocked_missing, problems, blocked_words = validate_submission(
            report.get("data") or {}, report.get("gps") or {}, report.get("declaration", False),
            config, evidence_for_check, len(call_logs), settings)

    data = (report or {}).get("data") or {}
    masked = False
    if ctx["user"]["role"] != "agent" and not reveal:
        data = core.mask_mapping(data)
        masked = True
    elif ctx["user"]["role"] != "agent" and reveal:
        await core.audit(ctx["user"], "sensitive_revealed", "case", str(case["_id"]), {}, None)

    d = security.case_public(case)
    d["latest_report"] = None
    return {
        "case": d, "report": (core.clean(report) if report else None),
        "masked_data": data if report else None, "masked": masked,
        "evidence": evidence, "call_logs": call_logs, "config": config,
        "checklist": {"missing_fields": blocked_missing, "problems": problems, "blocked_words": blocked_words},
        "can_edit": agent_can_edit(case) if ctx["user"]["role"] == "agent" else False,
    }


@router.put("/reports/case/{case_id}/draft")
async def save_draft(case_id: str, body: DraftIn, request: Request, ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if ctx["user"]["role"] != "agent" or case.get("assigned_agent_id") != str(ctx["user"]["_id"]):
        raise HTTPException(403, "Only the assigned agent can edit this report")
    if not agent_can_edit(case):
        raise HTTPException(400, "Report cannot be edited unless returned for correction")
    now = core.now()
    report = await latest_report(str(case["_id"]))
    if report and report.get("status") == "draft":
        await core.db.reports.update_one({"_id": report["_id"]}, {"$set": {
            "data": body.data, "gps": body.gps, "declaration": body.declaration,
            "offline_synced": body.offline_synced, "updated_at": now}})
        rid, ver = report["_id"], report["version"]
    else:
        ver = (report or {}).get("version", 0) + 1
        doc = core.ReportDoc(case_id=str(case["_id"]), version=ver, status="draft", report_type=case["report_type"],
                             data=body.data, gps=body.gps, declaration=body.declaration,
                             offline_synced=body.offline_synced, created_at=now, updated_at=now)
        res = await core.db.reports.insert_one(doc.to_mongo())
        rid = res.inserted_id
    if case.get("status") == "assigned":
        await core.db.cases.update_one({"_id": case["_id"]}, {"$set": {"status": "in_progress", "updated_at": now},
                                                             "$push": {"timeline": tl("draft_saved", ctx["user"], {"version": ver})}})
    await core.audit(ctx["user"], "draft_saved", "case", str(case["_id"]), {"version": ver, "offline_synced": body.offline_synced}, request)
    saved = await core.db.reports.find_one({"_id": rid})
    return core.clean(saved)


class SubmitIn(DraftIn):
    pass


@router.post("/reports/case/{case_id}/submit")
async def submit_report(case_id: str, body: SubmitIn, request: Request, ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if ctx["user"]["role"] != "agent" or case.get("assigned_agent_id") != str(ctx["user"]["_id"]):
        raise HTTPException(403, "Only the assigned agent can submit this report")
    if not agent_can_edit(case):
        raise HTTPException(400, "Report already submitted and not returned for correction")
    settings = await core.get_settings()
    config = config_for(case["report_type"], settings)
    evidence = [e async for e in core.db.evidence.find({"case_id": str(case["_id"])})]
    call_count = await core.db.call_logs.count_documents({"case_id": str(case["_id"])})
    missing, problems, blocked_words = validate_submission(
        body.data, body.gps, body.declaration, config, [e for e in evidence if e.get("kind") == "photo"], call_count, settings)
    if missing or problems or blocked_words:
        raise HTTPException(422, detail={"code": "validation_error", "missing_fields": missing,
                                         "problems": problems, "blocked_words": blocked_words})
    now = core.now()
    flags = await compute_flags(case, body.data, body.gps, settings)
    evidence_flags = [f for f in (case.get("flags") or []) if f in ("duplicate_photo_cross_case", "same_evidence_reused")]
    flags = sorted(set(flags + evidence_flags))
    prev = await latest_report(str(case["_id"]))
    ver = (prev or {}).get("version", 0) if (prev or {}).get("status") == "draft" else (prev or {}).get("version", 0) + 1
    doc = core.ReportDoc(
        case_id=str(case["_id"]), version=ver, status="submitted", report_type=case["report_type"],
        data=body.data, gps=body.gps, declaration=body.declaration, flags=flags,
        offline_synced=body.offline_synced, submitted_by=str(ctx["user"]["_id"]),
        submitted_by_name=ctx["user"]["name"], submitted_at=now, created_at=now, updated_at=now)
    await core.db.reports.update_many({"case_id": str(case["_id"]), "status": "draft"}, {"$set": {"status": "superseded"}})
    res = await core.db.reports.insert_one(doc.to_mongo())
    await core.db.cases.update_one({"_id": case["_id"]}, {"$set": {
        "status": "submitted", "last_submitted_at": now, "last_gps": body.gps, "flags": flags, "updated_at": now},
        "$push": {"timeline": tl("report_submitted", ctx["user"], {"version": ver, "flags": flags})}})
    await core.audit(ctx["user"], "report_submitted", "case", str(case["_id"]), {"version": ver, "flags": flags}, request)
    return core.clean(await core.db.reports.find_one({"_id": res.inserted_id}))


@router.get("/reports/case/{case_id}/versions")
async def report_versions(case_id: str, ctx=Depends(security.staff)):
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    items = []
    async for r in core.db.reports.find({"case_id": str(case["_id"])}).sort("version", -1):
        items.append({"id": str(r["_id"]), "version": r.get("version"), "status": r.get("status"),
                      "submitted_by_name": r.get("submitted_by_name"), "submitted_at": r.get("submitted_at"),
                      "reviewed_by_name": r.get("reviewed_by_name"), "reviewed_at": r.get("reviewed_at"),
                      "review_comment": r.get("review_comment"), "flags": r.get("flags") or []})
    return {"items": items}


async def get_report_or_404(report_id: str) -> dict:
    try:
        r = await core.db.reports.find_one({"_id": __import__("bson").ObjectId(report_id)})
    except Exception:
        raise HTTPException(404, "Report not found")
    if not r:
        raise HTTPException(404, "Report not found")
    return r


class ReviewIn(BaseModel):
    action: str = Field(pattern="^(approve|return|inconclusive|exception|escalate)$")
    comment: str | None = None


@router.get("/reports/{report_id}")
async def review_payload(report_id: str, reveal: int = 0, request: Request = None, ctx=Depends(security.admin_sup)):
    r = await get_report_or_404(report_id)
    case = await core.db.cases.find_one({"_id": __import__("bson").ObjectId(r["case_id"])})
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    settings = await core.get_settings()
    config = config_for(case["report_type"], settings)
    evidence = [core.clean(e) async for e in core.db.evidence.find({"case_id": r["case_id"]}).sort("created_at", -1)]
    call_logs = [core.clean(c) async for c in core.db.call_logs.find({"case_id": r["case_id"]}).sort("attempt_at", -1)]
    if case.get("status") == "submitted":
        await core.db.cases.update_one({"_id": case["_id"]}, {"$set": {"status": "under_review", "updated_at": core.now()},
                                                             "$push": {"timeline": tl("review_started", ctx["user"], {})}})
        await core.db.reports.update_one({"_id": r["_id"]}, {"$set": {"status": "under_review"}})
        r["status"] = "under_review"
        case["status"] = "under_review"
        await core.audit(ctx["user"], "review_started", "case", r["case_id"], {}, request)

    data = r.get("data") or {}
    masked = False
    if not reveal:
        data = core.mask_mapping(data)
        masked = True
    else:
        await core.audit(ctx["user"], "sensitive_revealed", "report", report_id, {}, request)

    versions = []
    async for v in core.db.reports.find({"case_id": r["case_id"]}).sort("version", -1):
        versions.append({"id": str(v["_id"]), "version": v.get("version"), "status": v.get("status"),
                         "submitted_by_name": v.get("submitted_by_name"), "submitted_at": v.get("submitted_at"),
                         "review_comment": v.get("review_comment")})

    return {"case": security.case_public(case), "report": core.clean(r), "masked_data": data, "masked": masked,
            "config": config, "evidence": evidence, "call_logs": call_logs, "versions": versions,
            "timeline": case.get("timeline") or []}


@router.post("/reports/{report_id}/review")
async def review_report(report_id: str, body: ReviewIn, request: Request, ctx=Depends(security.admin_sup)):
    r = await get_report_or_404(report_id)
    case = await core.db.cases.find_one({"_id": __import__("bson").ObjectId(r["case_id"])})
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    if r.get("status") not in ("submitted", "under_review"):
        raise HTTPException(400, f"Report in status '{r.get('status')}' cannot be reviewed")
    if body.action == "return" and not (body.comment or "").strip():
        raise HTTPException(400, "Correction comments are mandatory when returning a report")
    now = core.now()
    u = ctx["user"]
    status_map = {"approve": ("approved", "approved"), "return": ("returned", "returned"),
                  "inconclusive": ("inconclusive", "inconclusive"), "exception": ("exception", "exception")}
    if body.action == "escalate":
        await core.db.cases.update_one({"_id": case["_id"]}, {"$set": {"escalated": True, "updated_at": now},
                                                             "$push": {"timeline": tl("escalated_to_super_admin", u, {"comment": body.comment or ""})}})
        await core.audit(u, "report_escalated", "report", report_id, {}, request)
        return {"ok": True}
    r_status, c_status = status_map[body.action]
    await core.db.reports.update_one({"_id": r["_id"]}, {"$set": {
        "status": r_status, "reviewed_by": str(u["_id"]), "reviewed_by_name": u["name"],
        "reviewed_at": now, "review_comment": body.comment, "updated_at": now}})
    case_updates = {"status": c_status, "updated_at": now,
                    "reviewed_by": str(u["_id"]), "reviewed_by_name": u["name"], "reviewed_at": now}
    if body.action == "approve":
        case_updates["approved_at"] = now
        case_updates["approved_by"] = u["name"]
    await core.db.cases.update_one({"_id": case["_id"]}, {"$set": case_updates, "$push": {
        "timeline": tl(f"report_{body.action}", u, {"comment": body.comment or ""})}})
    await core.audit(u, f"report_{body.action}", "report", report_id, {"comment": body.comment or ""}, request)
    return core.clean(await core.db.reports.find_one({"_id": r["_id"]}))
