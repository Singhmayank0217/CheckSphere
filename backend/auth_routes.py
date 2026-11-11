"""Auth routes: login, change password, logout, me, sessions."""
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import core
import security

router = APIRouter()


class LoginIn(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=128)
    device_id: str = Field(default="unknown-device", max_length=200)
    device_model: str = Field(default="", max_length=200)
    platform: str = Field(default="", max_length=50)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/auth/login")
async def login(body: LoginIn, request: Request):
    ident = body.identifier.strip()
    u = await core.db.users.find_one({"$or": [
        {"email": ident.lower()}, {"agent_id": ident.upper()}, {"phone": ident},
    ]})
    if not u or not security.verify_password(body.password, u.get("password_hash", "")):
        await core.audit({"name": ident, "role": "anonymous"}, "login_failed", "user", ident, {}, request)
        raise HTTPException(401, "Invalid credentials")
    if u.get("disabled"):
        raise HTTPException(403, "Account is deactivated. Contact your administrator.")

    sid = str(uuid.uuid4())
    t = core.now()
    session_doc = {
        "_id": sid, "user_id": str(u["_id"]), "device_id": body.device_id,
        "device_model": body.device_model, "platform": body.platform,
        "ip": request.client.host if request.client else None,
        "created_at": t, "last_seen_at": t,
        "expires_at": t + timedelta(days=security.SESSION_DAYS), "revoked_at": None,
    }
    await core.db.sessions.insert_one(session_doc)
    token = security.make_token(str(u["_id"]), sid)
    await core.audit(u, "login", "user", str(u["_id"]), {"device_id": body.device_id, "device_model": body.device_model}, request)
    return {
        "access_token": token, "token_type": "bearer",
        "must_change_password": u.get("must_change_password", False),
        "session_id": sid, "user": security.user_public(u),
    }


@router.get("/auth/me")
async def me(ctx=Depends(security.auth_ctx)):
    u = ctx["user"]
    s = ctx["session"]
    return {"user": security.user_public(u),
            "session": {"id": s["_id"], "device_id": s.get("device_id"), "device_model": s.get("device_model"),
                        "created_at": s.get("created_at")}}


@router.post("/auth/change-password")
async def change_password(body: ChangePasswordIn, request: Request, ctx=Depends(security.auth_ctx)):
    u = ctx["user"]
    if not security.verify_password(body.current_password, u.get("password_hash", "")):
        raise HTTPException(400, "Current password is incorrect")
    if body.current_password == body.new_password:
        raise HTTPException(400, "New password must be different")
    await core.db.users.update_one({"_id": u["_id"]}, {"$set": {
        "password_hash": security.hash_password(body.new_password),
        "must_change_password": False, "password_changed_at": core.now()}})
    current_sid = ctx["session"]["_id"]
    await core.db.sessions.update_many(
        {"user_id": str(u["_id"]), "revoked_at": None, "_id": {"$ne": current_sid}},
        {"$set": {"revoked_at": core.now()}})
    await core.audit(u, "password_changed", "user", str(u["_id"]), {}, request)
    return {"ok": True}


@router.post("/auth/logout")
async def logout(request: Request, ctx=Depends(security.auth_ctx)):
    await core.db.sessions.update_one({"_id": ctx["session"]["_id"]}, {"$set": {"revoked_at": core.now()}})
    await core.audit(ctx["user"], "logout", "user", str(ctx["user"]["_id"]), {}, request)
    return {"ok": True}


@router.get("/auth/sessions")
async def my_sessions(ctx=Depends(security.auth_ctx)):
    uid = str(ctx["user"]["_id"])
    items = []
    async for s in core.db.sessions.find({"user_id": uid, "revoked_at": None}).sort("created_at", -1):
        items.append(core.clean(s))
    return {"items": items}


@router.post("/auth/sessions/{sid}/revoke")
async def revoke_session(sid: str, request: Request, ctx=Depends(security.auth_ctx)):
    s = await core.db.sessions.find_one({"_id": sid})
    if not s:
        raise HTTPException(404, "Session not found")
    if str(s.get("user_id")) != str(ctx["user"]["_id"]) and ctx["user"]["role"] != "super_admin":
        raise HTTPException(403, "Not allowed")
    await core.db.sessions.update_one({"_id": sid}, {"$set": {"revoked_at": core.now()}})
    await core.audit(ctx["user"], "session_revoked", "session", sid, {"owner": s.get("user_id")}, request)
    return {"ok": True}
