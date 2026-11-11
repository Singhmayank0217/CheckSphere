"""Immutable audit log access (Super Admin)."""
import re

from fastapi import APIRouter, Depends

import core
import security

router = APIRouter()


@router.get("/audit")
async def list_audit(user_id: str | None = None, action: str | None = None, entity: str | None = None,
                     q: str | None = None, page: int = 1, limit: int = 50, ctx=Depends(security.admin_only)):
    query = {}
    if user_id:
        query["user_id"] = user_id
    if action:
        query["action"] = {"$regex": re.escape(action), "$options": "i"}
    if entity:
        query["entity"] = entity
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"user_name": rx}, {"action": rx}, {"entity_id": rx}]
    total = await core.db.audit_logs.count_documents(query)
    cursor = core.db.audit_logs.find(query).sort("created_at", -1).skip((page - 1) * limit).limit(min(limit, 200))
    items = [core.clean(a) async for a in cursor]
    return {"items": items, "total": total, "page": page, "limit": limit}
