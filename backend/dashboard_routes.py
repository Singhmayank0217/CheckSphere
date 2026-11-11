"""Dashboard stats and map data."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request

import core
import security
from requests_routes import scoped_query as requests_scope

router = APIRouter()

STATUS_ORDER = ["new", "assigned", "in_progress", "submitted", "under_review", "returned",
                "approved", "inconclusive", "exception", "exported"]


def _base_query(ctx, from_date, to_date, client_id, branch_id, state, city, agent_id, report_type):
    query = {"deleted_at": None}
    query.update(security.case_scope_query(ctx["user"]))
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
    if from_date or to_date:
        rng = {}
        if from_date:
            rng["$gte"] = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
        if to_date:
            rng["$lte"] = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)
        query["created_at"] = rng
    return query


@router.get("/dashboard/stats")
async def stats(request: Request, from_date: str | None = None, to_date: str | None = None,
                client_id: str | None = None, branch_id: str | None = None, state: str | None = None,
                city: str | None = None, agent_id: str | None = None, report_type: str | None = None,
                ctx=Depends(security.admin_sup)):
    query = _base_query(ctx, from_date, to_date, client_id, branch_id, state, city, agent_id, report_type)
    cases = await core.db.cases.find(query).limit(5000).to_list(5000)
    now = core.now()
    counts = defaultdict(int)
    for c in cases:
        counts[c.get("status", "new")] += 1
    unassigned = sum(1 for c in cases if not c.get("assigned_agent_id") and c.get("status") == "new")
    overdue_cases = [c for c in cases if c.get("due_at") and c["due_at"] < now and c.get("status") in core.ACTIVE_STATUSES]
    tats = [(c["approved_at"] - c["created_at"]).total_seconds() / 3600.0
            for c in cases if c.get("approved_at") and c.get("created_at")]
    avg_tat = sum(tats) / len(tats) if tats else None

    def group(key):
        out = defaultdict(lambda: {"total": 0, "approved": 0, "overdue": 0, "submitted": 0})
        for c in cases:
            k = c.get(key) or "-"
            out[k]["total"] += 1
            if c.get("status") == "approved":
                out[k]["approved"] += 1
            if c.get("status") in ("submitted", "under_review"):
                out[k]["submitted"] += 1
            if c in overdue_cases:
                out[k]["overdue"] += 1
        return [{"name": k, **v} for k, v in sorted(out.items())]

    agents = group("assigned_agent_name")
    clients = group("client_name")
    branches = group("branch_name")
    states = group("state")
    cities = group("city")

    sup_stats = defaultdict(lambda: {"approved": 0, "returned": 0, "inconclusive": 0, "exception": 0})
    async for r in core.db.reports.find({"status": {"$in": ["approved", "returned", "inconclusive", "exception"]}}):
        name = r.get("reviewed_by_name")
        if name:
            key = {"approved": "approved", "returned": "returned", "inconclusive": "inconclusive", "exception": "exception"}.get(r["status"])
            if key:
                sup_stats[name][key] += 1
    supervisors = [{"name": k, **v} for k, v in sorted(sup_stats.items())]

    # Case volume (last 14 days), status distribution, flags, TAT by agent, pending review
    volume = defaultdict(int)
    start_day = (now - timedelta(days=13)).date()
    for c in cases:
        if c.get("created_at") and c["created_at"].date() >= start_day:
            volume[c["created_at"].date().isoformat()] += 1
    volume_series = [{"date": (start_day + timedelta(days=i)).isoformat(),
                      "count": volume.get((start_day + timedelta(days=i)).isoformat(), 0)} for i in range(14)]
    flag_summary = defaultdict(int)
    for c in cases:
        for f in c.get("flags") or []:
            flag_summary[f] += 1
    tat_agent = defaultdict(list)
    for c in cases:
        if c.get("approved_at") and c.get("created_at"):
            tat_agent[c.get("assigned_agent_name") or "-"].append((c["approved_at"] - c["created_at"]).total_seconds() / 3600.0)
    pending = sorted([c for c in cases if c.get("status") in ("submitted", "under_review")],
                     key=lambda c: c.get("last_submitted_at") or c["created_at"])

    return {
        "volume": volume_series,
        "flag_summary": dict(flag_summary),
        "flagged_cases": sum(1 for c in cases if c.get("flags")),
        "tat_by_agent": [{"name": k, "hours": round(sum(v) / len(v), 1)} for k, v in sorted(tat_agent.items())],
        "pending_review": [security.case_public(c) for c in pending[:10]],
        "escalated": sum(1 for c in cases if c.get("escalated")),
        "counts": {k: counts.get(k, 0) for k in STATUS_ORDER},
        "total": len(cases),
        "unassigned": unassigned,
        "overdue": len(overdue_cases),
        "pending_24h": sum(1 for c in cases if c.get("status") in core.ACTIVE_STATUSES and c.get("updated_at") and c["updated_at"] < now - timedelta(hours=24)),
        "pending_48h": sum(1 for c in cases if c.get("status") in core.ACTIVE_STATUSES and c.get("updated_at") and c["updated_at"] < now - timedelta(hours=48)),
        "requests_pending": await core.db.case_requests.count_documents(
            {"$and": [await requests_scope(ctx["user"]), {"status": {"$in": ["sent_for_allocation", "under_review"]}}]}),
        "avg_tat_hours": avg_tat,
        "agents": agents,
        "supervisors": supervisors,
        "clients": clients,
        "branches": branches,
        "states": states,
        "cities": cities,
        "overdue_cases": [security.case_public(c) for c in overdue_cases[:50]],
    }


@router.get("/dashboard/map")
async def map_data(request: Request, client_id: str | None = None, state: str | None = None,
                   city: str | None = None, status: str | None = None,
                   flagged: int = 0, ctx=Depends(security.admin_sup)):
    query = _base_query(ctx, None, None, client_id, None, state, city, None, None)
    if status:
        query["status"] = {"$in": [s.strip() for s in status.split(",")]}
    items = []
    async for c in core.db.cases.find(query).sort("created_at", -1).limit(1000):
        gps = c.get("last_gps") or {}
        lat = gps.get("lat") or c.get("assigned_lat")
        lon = gps.get("lon") or c.get("assigned_lon")
        if lat is None or lon is None:
            continue
        if flagged and not (c.get("flags") or []):
            continue
        items.append({
            "id": str(c["_id"]), "internal_case_id": c.get("internal_case_id"),
            "applicant_name": c.get("applicant_name"), "status": c.get("status"),
            "report_type": c.get("report_type"), "flags": c.get("flags") or [],
            "lat": lat, "lon": lon,
            "accuracy": gps.get("accuracy"),
        })
    return {"items": items}
