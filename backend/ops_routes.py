"""Operations: sessions, activation links, user activity, incidents, backups, retention."""
import asyncio
import hashlib
import json
import logging
import secrets
from datetime import timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import core
import security
import storage_service

router = APIRouter()
logger = logging.getLogger(__name__)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- sessions
@router.get("/sessions")
async def all_sessions(active: int = 1, ctx=Depends(security.admin_only)):
    q = {"revoked_at": None, "expires_at": {"$gt": core.now()}} if active else {}
    users = {str(u["_id"]): u async for u in core.db.users.find({}, {"name": 1, "role": 1, "agent_id": 1})}
    items = []
    async for s in core.db.sessions.find(q).sort("last_seen_at", -1).limit(500):
        d = core.clean(s)
        u = users.get(s.get("user_id")) or {}
        d.update({"user_name": u.get("name"), "user_role": u.get("role"), "agent_id": u.get("agent_id")})
        items.append(d)
    return {"items": items}


@router.post("/users/{user_id}/revoke-all")
async def revoke_all(user_id: str, request: Request, ctx=Depends(security.admin_only)):
    res = await core.db.sessions.update_many({"user_id": user_id, "revoked_at": None}, {"$set": {"revoked_at": core.now()}})
    await core.audit(ctx["user"], "sessions_revoked_all", "user", user_id, {"count": res.modified_count}, request)
    return {"revoked": res.modified_count}


@router.get("/users/{user_id}/activity")
async def user_activity(user_id: str, ctx=Depends(security.admin_only)):
    items = [core.clean(a) async for a in core.db.audit_logs.find({"user_id": user_id}).sort("created_at", -1).limit(100)]
    return {"items": items}


# ---------------------------------------------------------------- activation link
@router.post("/users/{user_id}/activation-link")
async def activation_link(user_id: str, request: Request, ctx=Depends(security.admin_only)):
    u = await core.db.users.find_one({"_id": ObjectId(user_id)})
    if not u:
        raise HTTPException(404, "User not found")
    token = secrets.token_urlsafe(32)
    await core.db.activation_tokens.insert_one({
        "token_hash": _hash(token), "user_id": user_id, "created_at": core.now(),
        "expires_at": core.now() + timedelta(hours=72), "used_at": None})
    await core.audit(ctx["user"], "activation_link_created", "user", user_id, {}, request)
    return {"token": token, "path": f"/activate?token={token}", "expires_in_hours": 72}


class ActivateIn(BaseModel):
    token: str = Field(min_length=10)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/auth/activate")
async def activate(body: ActivateIn, request: Request):
    t = await core.db.activation_tokens.find_one({"token_hash": _hash(body.token), "used_at": None})
    if not t or t["expires_at"] <= core.now():
        raise HTTPException(400, "Activation link is invalid or expired")
    await core.db.users.update_one({"_id": ObjectId(t["user_id"])}, {"$set": {
        "password_hash": security.hash_password(body.new_password), "must_change_password": False,
        "password_changed_at": core.now()}})
    await core.db.activation_tokens.update_one({"_id": t["_id"]}, {"$set": {"used_at": core.now()}})
    await core.db.sessions.update_many({"user_id": t["user_id"], "revoked_at": None}, {"$set": {"revoked_at": core.now()}})
    await core.audit({"_id": t["user_id"], "name": "activation", "role": "user"}, "account_activated", "user", t["user_id"], {}, request)
    return {"ok": True}


# ---------------------------------------------------------------- incidents
class IncidentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    severity: str = Field(pattern="^(Low|Medium|High|Critical)$")
    description: str = ""
    status: str = "Open"


@router.get("/incidents")
async def list_incidents(ctx=Depends(security.admin_only)):
    return {"items": [core.clean(i) async for i in core.db.incidents.find().sort("created_at", -1)]}


@router.post("/incidents")
async def create_incident(body: IncidentIn, request: Request, ctx=Depends(security.admin_only)):
    doc = {**body.model_dump(), "reported_by": ctx["user"]["name"], "created_at": core.now()}
    res = await core.db.incidents.insert_one(doc)
    await core.audit(ctx["user"], "incident_logged", "incident", str(res.inserted_id), {"severity": body.severity}, request)
    return core.clean(await core.db.incidents.find_one({"_id": res.inserted_id}))


@router.post("/incidents/{iid}/close")
async def close_incident(iid: str, request: Request, ctx=Depends(security.admin_only)):
    await core.db.incidents.update_one({"_id": ObjectId(iid)}, {"$set": {"status": "Closed", "closed_at": core.now()}})
    await core.audit(ctx["user"], "incident_closed", "incident", iid, {}, request)
    return {"ok": True}


# ---------------------------------------------------------------- backups
BACKUP_COLLECTIONS = ["users", "clients", "branches", "cases", "reports", "evidence", "call_logs", "settings", "audit_logs", "incidents"]


async def run_backup(trigger: str, user=None) -> dict:
    payload = {}
    for name in BACKUP_COLLECTIONS:
        docs = await core.db[name].find({}, {"password_hash": 0}).to_list(100000)
        payload[name] = docs
    data = json.dumps(payload, default=str).encode()
    path = f"{storage_service.STORAGE_APP}/backups/backup-{core.now().strftime('%Y%m%d-%H%M%S')}.json"
    await storage_service.put_object_async(path, data, "application/json")
    rec = {"path": path, "size": len(data), "trigger": trigger, "created_at": core.now(),
           "counts": {k: len(v) for k, v in payload.items()}}
    await core.db.backups.insert_one(rec)
    await core.audit(user or {"name": "system", "role": "system"}, "backup_completed", "backup", path, {"size": len(data), "trigger": trigger})
    return rec


async def daily_backup_loop():
    while True:
        try:
            last = await core.db.backups.find_one({}, sort=[("created_at", -1)])
            if not last or core.now() - last["created_at"] > timedelta(hours=24):
                await run_backup("scheduled")
        except Exception as exc:
            logger.error("daily backup failed: %s", exc)
        await asyncio.sleep(3600)


@router.get("/backups")
async def list_backups(ctx=Depends(security.admin_only)):
    return {"items": [core.clean(b) async for b in core.db.backups.find().sort("created_at", -1).limit(60)]}


@router.post("/backups/run")
async def backup_now(request: Request, ctx=Depends(security.admin_only)):
    rec = await run_backup("manual", ctx["user"])
    return core.clean(rec)


# ---------------------------------------------------------------- retention
async def _retention_query():
    settings = await core.get_settings()
    cutoff = core.now() - timedelta(days=int(settings.get("retention_days", 3650)))
    return {"status": {"$in": ["approved", "exported", "inconclusive", "exception"]},
            "updated_at": {"$lt": cutoff}, "purged_at": None}, cutoff


@router.get("/retention/preview")
async def retention_preview(ctx=Depends(security.admin_only)):
    q, cutoff = await _retention_query()
    return {"eligible_cases": await core.db.cases.count_documents(q), "cutoff": cutoff,
            "last_runs": [core.clean(r) async for r in core.db.retention_runs.find().sort("created_at", -1).limit(10)]}


@router.post("/retention/run")
async def retention_run(request: Request, ctx=Depends(security.admin_only)):
    q, cutoff = await _retention_query()
    ids = [str(c["_id"]) async for c in core.db.cases.find(q, {"_id": 1})]
    ev = await core.db.evidence.update_many({"case_id": {"$in": ids}}, {"$set": {"storage_path": "", "purged_at": core.now()}})
    await core.db.cases.update_many({"_id": {"$in": [ObjectId(i) for i in ids]}}, {"$set": {"purged_at": core.now()}})
    rec = {"cases": len(ids), "evidence": ev.modified_count, "cutoff": cutoff, "by": ctx["user"]["name"], "created_at": core.now()}
    await core.db.retention_runs.insert_one(rec)
    await core.audit(ctx["user"], "retention_purge", "system", "retention", {"cases": len(ids), "evidence": ev.modified_count}, request)
    return core.clean(rec)
