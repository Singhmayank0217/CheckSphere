"""Admin & master-data routes: users, clients, branches, regions, settings, report types."""
import re

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import core
import security
from report_config import config_for, report_type_choices

router = APIRouter()


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(pattern="^(super_admin|supervisor|agent)$")
    agent_id: str | None = None
    email: str | None = None
    phone: str | None = None
    password: str = Field(min_length=8, max_length=128)
    scope: dict | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    scope: dict | None = None


class ResetPassword(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class SetActive(BaseModel):
    active: bool


@router.get("/users")
async def list_users(role: str | None = None, q: str | None = None, ctx=Depends(security.admin_sup)):
    query = {}
    if role:
        query["role"] = role
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"name": rx}, {"agent_id": rx}, {"email": rx}, {"phone": rx}]
    items = []
    async for u in core.db.users.find(query).sort("name", 1):
        items.append(security.user_public(u))
    return {"items": items}


@router.post("/users")
async def create_user(body: UserCreate, request: Request, ctx=Depends(security.admin_only)):
    if body.role == "agent" and not body.agent_id:
        seq = await core.next_seq("agent_id")
        body.agent_id = f"AGT{seq:03d}"
    if body.agent_id:
        body.agent_id = body.agent_id.upper()
        if await core.db.users.find_one({"agent_id": body.agent_id}):
            raise HTTPException(400, "Agent ID already exists")
    if body.email and await core.db.users.find_one({"email": body.email.lower()}):
        raise HTTPException(400, "Email already exists")
    doc = {
        "role": body.role, "name": body.name, "agent_id": body.agent_id,
        "email": (body.email or "").lower() or None, "phone": body.phone,
        "password_hash": security.hash_password(body.password),
        "must_change_password": True, "disabled": False,
        "scope": body.scope or {}, "created_at": core.now(),
    }
    # sparse unique indexes only skip *missing* fields, not explicit nulls
    for k in ("agent_id", "email"):
        if doc.get(k) is None:
            doc.pop(k)
    res = await core.db.users.insert_one(doc)
    await core.audit(ctx["user"], "user_created", "user", str(res.inserted_id), {"role": body.role}, request)
    return security.user_public(await core.db.users.find_one({"_id": res.inserted_id}))


@router.put("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, request: Request, ctx=Depends(security.admin_only)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    await core.db.users.update_one({"_id": ObjectId(user_id)}, {"$set": updates})
    await core.audit(ctx["user"], "user_updated", "user", user_id, updates, request)
    return security.user_public(await core.db.users.find_one({"_id": ObjectId(user_id)}))


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: str, body: ResetPassword, request: Request, ctx=Depends(security.admin_only)):
    await core.db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {
        "password_hash": security.hash_password(body.password),
        "must_change_password": True, "password_changed_at": core.now()}})
    await core.db.sessions.update_many({"user_id": user_id, "revoked_at": None}, {"$set": {"revoked_at": core.now()}})
    await core.audit(ctx["user"], "password_reset", "user", user_id, {}, request)
    return {"ok": True}


@router.post("/users/{user_id}/set-active")
async def set_active(user_id: str, body: SetActive, request: Request, ctx=Depends(security.admin_only)):
    await core.db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"disabled": not body.active}})
    if not body.active:
        await core.db.sessions.update_many({"user_id": user_id, "revoked_at": None}, {"$set": {"revoked_at": core.now()}})
    await core.audit(ctx["user"], "user_activated" if body.active else "user_deactivated", "user", user_id, {}, request)
    return {"ok": True}


@router.get("/users/{user_id}/sessions")
async def user_sessions(user_id: str, ctx=Depends(security.admin_only)):
    items = []
    async for s in core.db.sessions.find({"user_id": user_id}).sort("created_at", -1).limit(50):
        items.append(core.clean(s))
    return {"items": items}


# --------------------------------------------------------------------------- clients and branches
# Reading is open to all staff (case forms need the lists). Creating, editing, activating and deactivating is
# Super Admin only, enforced here on the server (security.admin_only), not just by hiding buttons.
# There is deliberately no delete: deactivation keeps the history of existing cases intact.
class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=50)


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=50)


class BranchCreate(BaseModel):
    client_id: str
    name: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)


class BranchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)


def _oid(v: str, what: str) -> ObjectId:
    try:
        return ObjectId(v)
    except Exception:
        raise HTTPException(404, f"{what} not found")


def _same_name(name: str) -> dict:
    return {"$regex": f"^{re.escape(name.strip())}$", "$options": "i"}


@router.get("/clients")
async def list_clients(include_inactive: bool = False, ctx=Depends(security.staff)):
    """Active clients for everyone; the Super Admin can also ask for inactive ones (management screen)."""
    query = {} if include_inactive and ctx["user"]["role"] == "super_admin" else {"active": {"$ne": False}}
    items = [core.clean(c) async for c in core.db.clients.find(query).sort("name", 1)]
    return {"items": items}


@router.post("/clients")
async def create_client(body: ClientCreate, request: Request, ctx=Depends(security.admin_only)):
    if await core.db.clients.find_one({"name": _same_name(body.name)}):
        raise HTTPException(400, "Client already exists")
    res = await core.db.clients.insert_one(ClientDocFrom(body))
    await core.audit(ctx["user"], "client_created", "client", str(res.inserted_id), {"name": body.name.strip()}, request)
    return core.clean(await core.db.clients.find_one({"_id": res.inserted_id}))


def ClientDocFrom(body: ClientCreate) -> dict:
    return {"name": body.name.strip(), "code": (body.code or "").strip() or None, "active": True, "created_at": core.now()}


@router.put("/clients/{client_id}")
async def update_client(client_id: str, body: ClientUpdate, request: Request, ctx=Depends(security.admin_only)):
    oid = _oid(client_id, "Client")
    client = await core.db.clients.find_one({"_id": oid})
    if not client:
        raise HTTPException(404, "Client not found")
    updates = {}
    if body.name is not None and body.name.strip() != client.get("name"):
        if await core.db.clients.find_one({"name": _same_name(body.name), "_id": {"$ne": oid}}):
            raise HTTPException(400, "Another client already has this name")
        updates["name"] = body.name.strip()
    if body.code is not None:
        updates["code"] = body.code.strip() or None
    if updates:
        updates["updated_at"] = core.now()
        await core.db.clients.update_one({"_id": oid}, {"$set": updates})
        await core.audit(ctx["user"], "client_updated", "client", client_id,
                         {k: {"from": client.get(k), "to": v} for k, v in updates.items() if k != "updated_at"}, request)
    return core.clean(await core.db.clients.find_one({"_id": oid}))


@router.post("/clients/{client_id}/set-active")
async def set_client_active(client_id: str, body: SetActive, request: Request, ctx=Depends(security.admin_only)):
    oid = _oid(client_id, "Client")
    res = await core.db.clients.update_one({"_id": oid}, {"$set": {"active": body.active, "updated_at": core.now()}})
    if not res.matched_count:
        raise HTTPException(404, "Client not found")
    await core.audit(ctx["user"], "client_activated" if body.active else "client_deactivated", "client", client_id, {}, request)
    return core.clean(await core.db.clients.find_one({"_id": oid}))


@router.get("/branches")
async def list_branches(client_id: str | None = None, include_inactive: bool = False, ctx=Depends(security.staff)):
    """Active branches of active clients for everyone; the Super Admin can also ask for inactive ones."""
    query: dict = {}
    if not (include_inactive and ctx["user"]["role"] == "super_admin"):
        inactive_clients = [str(c["_id"]) async for c in core.db.clients.find({"active": False}, {"_id": 1})]
        query = {"active": {"$ne": False}, "client_id": {"$nin": inactive_clients}}
    if client_id:
        query["client_id"] = {**query.get("client_id", {}), "$eq": client_id}
    items = [core.clean(b) async for b in core.db.branches.find(query).sort("name", 1)]
    return {"items": items}


@router.post("/branches")
async def create_branch(body: BranchCreate, request: Request, ctx=Depends(security.admin_only)):
    client = await core.db.clients.find_one({"_id": _oid(body.client_id, "Client")})
    if not client:
        raise HTTPException(400, "Client not found")
    if client.get("active") is False:
        raise HTTPException(400, "This client is deactivated. Activate it before adding branches.")
    if await core.db.branches.find_one({"client_id": body.client_id, "name": _same_name(body.name)}):
        raise HTTPException(400, "This client already has a branch with this name")
    res = await core.db.branches.insert_one({
        "client_id": body.client_id, "name": body.name.strip(), "city": (body.city or "").strip() or None,
        "state": (body.state or "").strip() or None, "active": True, "created_at": core.now()})
    await core.audit(ctx["user"], "branch_created", "branch", str(res.inserted_id),
                     {"name": body.name.strip(), "client_id": body.client_id}, request)
    return core.clean(await core.db.branches.find_one({"_id": res.inserted_id}))


@router.put("/branches/{branch_id}")
async def update_branch(branch_id: str, body: BranchUpdate, request: Request, ctx=Depends(security.admin_only)):
    oid = _oid(branch_id, "Branch")
    branch = await core.db.branches.find_one({"_id": oid})
    if not branch:
        raise HTTPException(404, "Branch not found")
    updates = {}
    if body.name is not None and body.name.strip() != branch.get("name"):
        if await core.db.branches.find_one({"client_id": branch["client_id"], "name": _same_name(body.name), "_id": {"$ne": oid}}):
            raise HTTPException(400, "This client already has a branch with this name")
        updates["name"] = body.name.strip()
    for k in ("city", "state"):
        v = getattr(body, k)
        if v is not None:
            updates[k] = v.strip() or None
    if updates:
        updates["updated_at"] = core.now()
        await core.db.branches.update_one({"_id": oid}, {"$set": updates})
        await core.audit(ctx["user"], "branch_updated", "branch", branch_id,
                         {k: {"from": branch.get(k), "to": v} for k, v in updates.items() if k != "updated_at"}, request)
    return core.clean(await core.db.branches.find_one({"_id": oid}))


@router.post("/branches/{branch_id}/set-active")
async def set_branch_active(branch_id: str, body: SetActive, request: Request, ctx=Depends(security.admin_only)):
    oid = _oid(branch_id, "Branch")
    res = await core.db.branches.update_one({"_id": oid}, {"$set": {"active": body.active, "updated_at": core.now()}})
    if not res.matched_count:
        raise HTTPException(404, "Branch not found")
    await core.audit(ctx["user"], "branch_activated" if body.active else "branch_deactivated", "branch", branch_id, {}, request)
    return core.clean(await core.db.branches.find_one({"_id": oid}))


@router.get("/regions")
async def list_regions(ctx=Depends(security.staff)):
    states = sorted({s for s in await core.db.branches.distinct("state") if s})
    cities = sorted({c for c in await core.db.branches.distinct("city") if c})
    return {"states": states, "cities": cities}


@router.get("/settings")
async def get_settings_route(ctx=Depends(security.staff)):
    return await core.get_settings()


class SettingsIn(BaseModel):
    updates: dict


@router.put("/settings")
async def put_settings_route(body: SettingsIn, request: Request, ctx=Depends(security.admin_only)):
    updated = await core.save_settings(body.updates or {})
    await core.audit(ctx["user"], "settings_updated", "settings", "app", {"keys": list((body.updates or {}).keys())}, request)
    return updated


@router.get("/report-types")
async def report_types(ctx=Depends(security.staff)):
    settings = await core.get_settings()
    return {"items": report_type_choices(), "configs": {k: config_for(k, settings) for k in
                                                        ["residence_applicant", "residence_coapplicant", "business_applicant",
                                                         "office_coapplicant", "seller", "tel_residence", "tel_office",
                                                         "income", "kyc", "gst", "bank_account", "custom"]}}
