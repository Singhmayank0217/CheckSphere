"""JWT auth, bcrypt passwords, session management, role guards, case scoping."""
import os
import uuid
from datetime import timedelta
from typing import Optional

import bcrypt
import jwt
from bson import ObjectId
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import core

SECRET = os.environ.get("JWT_SECRET") or ""
ISSUER = "checksphere"
ACCESS_HOURS = int(os.environ.get("ACCESS_HOURS", "12"))
SESSION_DAYS = 30
bearer = HTTPBearer(auto_error=False)

GATE_ALLOWED_SUFFIXES = ("/auth/me", "/auth/change-password", "/auth/logout", "/auth/sessions")


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except (ValueError, TypeError):
        return False


def make_token(user_id: str, sid: str) -> str:
    issued = core.now()
    payload = {
        "sub": user_id, "sid": sid, "jti": str(uuid.uuid4()), "typ": "access",
        "iss": ISSUER, "iat": issued, "exp": issued + timedelta(hours=ACCESS_HOURS),
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=["HS256"], issuer=ISSUER,
                      options={"require": ["sub", "sid", "exp"]})


async def load_session_ctx(request: Request, creds: Optional[HTTPAuthorizationCredentials], token_q: Optional[str] = None):
    token = creds.credentials if creds else token_q
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        p = decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    s = await core.db.sessions.find_one({"_id": p["sid"], "revoked_at": None})
    if not s or s.get("expires_at", core.now()) <= core.now():
        raise HTTPException(401, "Session expired or revoked")
    try:
        uid = ObjectId(p["sub"])
    except Exception:
        raise HTTPException(401, "Invalid token subject")
    u = await core.db.users.find_one({"_id": uid})
    if not u or u.get("disabled"):
        raise HTTPException(401, "User unavailable")
    if core.now() - s.get("last_seen_at", core.now()) > timedelta(minutes=5):
        await core.db.sessions.update_one({"_id": s["_id"]}, {"$set": {"last_seen_at": core.now()}})
    path = request.url.path
    if u.get("must_change_password") and not any(path.endswith(a) for a in GATE_ALLOWED_SUFFIXES):
        raise HTTPException(403, detail={
            "code": "password_change_required",
            "message": "Change your password before continuing.",
        })
    return {"user": u, "session": s}


async def auth_ctx(request: Request, creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)):
    return await load_session_ctx(request, creds)


def require_roles(*roles):
    async def dep(ctx=Depends(auth_ctx)):
        if ctx["user"]["role"] not in roles:
            raise HTTPException(403, "Not allowed for your role")
        return ctx
    return dep


admin_only = require_roles("super_admin")
admin_sup = require_roles("super_admin", "supervisor")
staff = require_roles("super_admin", "supervisor", "agent")


def user_public(u: dict) -> dict:
    return {
        "id": str(u["_id"]),
        "name": u.get("name"),
        "role": u.get("role"),
        "agent_id": u.get("agent_id"),
        "email": u.get("email"),
        "phone": u.get("phone"),
        "must_change_password": u.get("must_change_password", False),
        "disabled": u.get("disabled", False),
        "scope": u.get("scope") or {},
        "created_at": u.get("created_at"),
        "last_login_at": u.get("last_login_at"),
        "last_login_ip": u.get("last_login_ip"),
        "last_login_device": u.get("last_login_device"),
    }


def case_public(c: dict) -> dict:
    from report_config import REPORT_TYPES
    d = core.clean(c)
    d["report_type_name"] = (REPORT_TYPES.get(d.get("report_type")) or {}).get("name", d.get("report_type"))
    d.pop("timeline", None)
    return d


def case_scope_query(user: dict) -> dict:
    role = user["role"]
    if role == "agent":
        return {"assigned_agent_id": str(user["_id"])}
    if role == "supervisor":
        scope = user.get("scope") or {}
        cons = []
        if scope.get("client_ids"):
            cons.append({"client_id": {"$in": scope["client_ids"]}})
        if scope.get("states"):
            cons.append({"state": {"$in": scope["states"]}})
        if scope.get("cities"):
            cons.append({"city": {"$in": scope["cities"]}})
        if scope.get("branch_ids"):
            cons.append({"branch_id": {"$in": scope["branch_ids"]}})
        if scope.get("agent_ids"):
            cons.append({"assigned_agent_id": {"$in": scope["agent_ids"]}})
        if not cons:
            return {}
        return {"$or": cons} if len(cons) > 1 else cons[0]
    return {}
