"""Device registration for remote push notifications (agents only).

The app calls /push/register after an agent logs in (and again when the Expo push token changes), and
/push/unregister before logging out. The owner of a token is always the logged-in user of the request and the device
is tied to that login session, so a push can only reach a phone that is currently logged in as the assigned agent.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

import core
import push_service
import security

router = APIRouter()
REGISTER_THROTTLE_SECONDS = 60


class PushRegisterIn(BaseModel):
    token: str = Field(min_length=10, max_length=250)
    device_id: str | None = Field(default=None, max_length=200)
    platform: str = Field(default="android", max_length=20)
    app_variant: str | None = Field(default=None, max_length=100)


class PushUnregisterIn(BaseModel):
    token: str = Field(min_length=10, max_length=250)


@router.post("/push/register")
async def register_device(body: PushRegisterIn, request: Request, ctx=Depends(security.require_roles("agent"))):
    token = body.token.strip()
    if not push_service.valid_token(token):
        raise HTTPException(400, "Invalid push token")
    user_id, session_id, now = str(ctx["user"]["_id"]), ctx["session"]["_id"], core.now()
    # Throttle: an identical registration (same token, agent, login session and device details, still enabled) that
    # was written less than a minute ago is acknowledged without another database write. A different agent or
    # session, a disabled token (app reinstalled) or changed device details is always written straight away.
    cur = await core.db.push_devices.find_one({"token": token})
    if (cur and cur.get("user_id") == user_id and cur.get("session_id") == session_id and cur.get("disabled_at") is None
            and cur.get("device_id") == body.device_id and cur.get("platform") == body.platform
            and cur.get("app_variant") == body.app_variant
            and cur.get("updated_at") and now - cur["updated_at"] < timedelta(seconds=REGISTER_THROTTLE_SECONDS)):
        return {"ok": True}
    sets = {"user_id": user_id, "session_id": session_id, "device_id": body.device_id, "platform": body.platform,
            "app_variant": body.app_variant, "updated_at": now, "disabled_at": None, "last_error": None}
    for _ in range(2):  # a concurrent first registration of the same token can race on the unique index
        try:
            prev = await core.db.push_devices.find_one_and_update(
                {"token": token}, {"$set": sets, "$setOnInsert": {"token": token, "created_at": now}}, upsert=True)
            break
        except DuplicateKeyError:
            continue
    else:
        raise HTTPException(409, "Please retry")
    if not prev or prev.get("user_id") != user_id:
        await core.audit(ctx["user"], "push_device_registered", "user", user_id,
                         {"device_id": body.device_id, "platform": body.platform, "app_variant": body.app_variant}, request)
    return {"ok": True}


@router.post("/push/unregister")
async def unregister_device(body: PushUnregisterIn, ctx=Depends(security.staff)):
    res = await core.db.push_devices.delete_many({"token": body.token.strip(), "user_id": str(ctx["user"]["_id"])})
    return {"ok": True, "removed": res.deleted_count}
