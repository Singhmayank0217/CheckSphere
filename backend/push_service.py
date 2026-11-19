"""Remote push notifications to agents' phones (Expo Push Service -> Firebase Cloud Messaging on Android).

Exactly two events, nothing else:
  * case_assigned   - a case is assigned to an agent (new case with an agent, request approved + allocated, or an
                      unassigned case assigned);
  * case_reassigned - a case moves from one agent to ANOTHER agent; only the new agent is notified.

Privacy: the title and body are fixed text. The only data sent is the event type, the internal case database id and
the in-app notification id (so the app can open the case and avoid showing the same alert twice). No applicant,
address, phone, bank or other case details ever leave the server in a push.

Delivery:
  * A push goes only to devices whose login session is still active (not logged out, revoked or expired), so every
    logout / remote-logout / deactivation path automatically stops pushes to that phone.
  * Every push is written to `push_outbox` first, under a unique `dedupe_key`, so the same assignment is never pushed
    twice (request retries are additionally covered by the Idempotency-Key middleware).
  * Sending happens in the background after the assignment has been saved; a failure never fails the assignment.
    Failed sends are retried by the `push` background job, which also reads Expo's delivery receipts and switches off
    tokens Expo reports as DeviceNotRegistered.
  * The existing in-app notification is always created as before, so the agent still sees the assignment if remote
    delivery fails.

Configuration (environment):
  PUSH_ENABLED=true      turn sending on (default OFF, so development and tests never reach the real service)
  EXPO_ACCESS_TOKEN      optional; required when "Enhanced security for push notifications" is on in Expo
  EXPO_PUSH_URL / EXPO_RECEIPTS_URL   override the Expo endpoints (used by the automated tests' fake server)
"""
import asyncio
import logging
import os
import re
from datetime import timedelta

import requests
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import core

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = os.environ.get("EXPO_PUSH_URL") or "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS_URL = os.environ.get("EXPO_RECEIPTS_URL") or "https://exp.host/--/api/v2/push/getReceipts"
ENABLED = (os.environ.get("PUSH_ENABLED") or "false").strip().lower() == "true"
ACCESS_TOKEN = (os.environ.get("EXPO_ACCESS_TOKEN") or "").strip()

TOKEN_RE = re.compile(r"^Expo(nent)?PushToken\[[A-Za-z0-9_-]{10,200}\]$")
CHANNEL_ID = "assignments"  # created by the app; must match frontend/src/utils/push.ts
MESSAGES = {
    "case_assigned": ("New Case Assigned", "A new verification task has been assigned to you. Open CheckSphere to view it."),
    "case_reassigned": ("Case Reassigned", "A verification task has been reassigned to you. Open CheckSphere to view it."),
}
MAX_ATTEMPTS = 5
LOCK = timedelta(seconds=60)          # a send in progress is not picked up again by the retry pass for this long
RETRY_WINDOW = timedelta(hours=24)    # stop retrying / checking receipts after this
RECEIPT_DELAY = timedelta(minutes=15)  # Expo recommends reading receipts after ~15 minutes
OUTBOX_TTL = timedelta(days=30)
BATCH = 100                           # Expo accepts up to 100 messages per request

_spawned: set = set()


def valid_token(token: str) -> bool:
    return bool(TOKEN_RE.match(token or ""))


async def active_tokens(user_id: str) -> list[str]:
    """Tokens of this user's devices whose login session is still active."""
    devices = [d async for d in core.db.push_devices.find({"user_id": user_id, "disabled_at": None},
                                                          {"token": 1, "session_id": 1})]
    if not devices:
        return []
    live = {s["_id"] async for s in core.db.sessions.find(
        {"_id": {"$in": [d["session_id"] for d in devices]}, "revoked_at": None, "expires_at": {"$gt": core.now()}}, {"_id": 1})}
    user = await core.db.users.find_one({"_id": ObjectId(user_id)}, {"disabled": 1, "role": 1}) if ObjectId.is_valid(user_id) else None
    if not user or user.get("disabled") or user.get("role") != "agent":
        return []
    return [d["token"] for d in devices if d["session_id"] in live]


async def queue_assignment_push(event: str, case_id: str, agent_id: str, assignment_key: str,
                                notification_id: str | None = None) -> bool:
    """Record (once) and send in the background. Call only AFTER the assignment has been saved.
    Returns True when a push was queued for at least one active device."""
    if event not in MESSAGES:
        raise ValueError(f"unsupported push event {event!r}")
    if not ENABLED:
        return False
    now = core.now()
    tokens = await active_tokens(agent_id)
    doc = {"dedupe_key": f"{event}:{case_id}:{agent_id}:{assignment_key}", "event": event, "case_id": case_id,
           "agent_id": agent_id, "notification_id": notification_id, "status": "pending" if tokens else "no_devices",
           "attempts": 0, "tickets": [], "last_error": None, "locked_until": None, "receipts_checked_at": None,
           "created_at": now, "updated_at": now, "expires_at": now + OUTBOX_TTL}
    try:
        res = await core.db.push_outbox.insert_one(doc)
    except DuplicateKeyError:
        logger.info("push %s for case %s already recorded; not sent again", event, case_id)
        return False
    if not tokens:
        return False
    if notification_id and ObjectId.is_valid(notification_id):
        await core.db.notifications.update_one({"_id": ObjectId(notification_id)}, {"$set": {"push_queued": True}})
    task = asyncio.create_task(_safe_send(res.inserted_id))
    _spawned.add(task)
    task.add_done_callback(_spawned.discard)
    return True


async def _safe_send(outbox_id) -> None:
    try:
        await send_outbox(outbox_id)
    except Exception as exc:  # never let a push problem surface in a request
        logger.error("push send %s failed: %s", outbox_id, type(exc).__name__)


def _headers() -> dict:
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if ACCESS_TOKEN:
        h["Authorization"] = f"Bearer {ACCESS_TOKEN}"
    return h


def _post(url: str, payload) -> dict:
    r = requests.post(url, json=payload, headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


async def _disable_token(token: str, reason: str) -> None:
    await core.db.push_devices.update_one({"token": token, "disabled_at": None},
                                          {"$set": {"disabled_at": core.now(), "last_error": reason}})


async def send_outbox(outbox_id) -> str:
    """Send one outbox entry (claimed with a short lock so the retry pass cannot send it at the same time)."""
    now = core.now()
    o = await core.db.push_outbox.find_one_and_update(
        {"_id": outbox_id, "status": "pending", "attempts": {"$lt": MAX_ATTEMPTS},
         "$or": [{"locked_until": None}, {"locked_until": {"$lt": now}}]},
        {"$set": {"locked_until": now + LOCK, "updated_at": now}, "$inc": {"attempts": 1}},
        return_document=ReturnDocument.AFTER)
    if not o:
        return "skipped"
    tokens = await active_tokens(o["agent_id"])
    if not tokens:
        await core.db.push_outbox.update_one({"_id": o["_id"]}, {"$set": {"status": "no_devices", "locked_until": None}})
        return "no_devices"
    title, body = MESSAGES[o["event"]]
    data = {"type": o["event"], "case_id": o["case_id"], "notification_id": o.get("notification_id")}
    messages = [{"to": t, "title": title, "body": body, "data": data, "sound": "default", "priority": "high",
                 "channelId": CHANNEL_ID} for t in tokens]
    tickets, ok, error = [], 0, None
    try:
        for i in range(0, len(messages), BATCH):
            chunk = messages[i:i + BATCH]
            resp = await asyncio.to_thread(_post, EXPO_PUSH_URL, chunk)
            for m, t in zip(chunk, resp.get("data") or []):
                if t.get("status") == "ok":
                    ok += 1
                    tickets.append({"token": m["to"], "id": t.get("id"), "status": "ok"})
                else:
                    err = (t.get("details") or {}).get("error") or "error"
                    tickets.append({"token": m["to"], "status": "error", "error": err})
                    if err == "DeviceNotRegistered":
                        await _disable_token(m["to"], err)
    except Exception as exc:
        error = type(exc).__name__
    if ok:
        status = "sent"
    elif error and o["attempts"] < MAX_ATTEMPTS:
        status = "pending"  # transport problem: the retry pass tries again
    else:
        status = "failed"
    await core.db.push_outbox.update_one({"_id": o["_id"]}, {"$set": {
        "status": status, "tickets": tickets, "last_error": error, "locked_until": None, "updated_at": core.now(),
        **({"sent_at": core.now()} if ok else {})}})
    logger.info("push %s case %s: %d/%d accepted, status %s%s", o["event"], o["case_id"], ok, len(messages), status,
                f" ({error})" if error else "")
    return status


async def check_receipts() -> int:
    """Read Expo delivery receipts for sent pushes and switch off tokens of uninstalled apps."""
    now = core.now()
    checked = 0
    async for o in core.db.push_outbox.find({"status": "sent", "receipts_checked_at": None,
                                             "sent_at": {"$lt": now - RECEIPT_DELAY, "$gt": now - RETRY_WINDOW}}).limit(50):
        ids = {t["id"]: t["token"] for t in o.get("tickets", []) if t.get("status") == "ok" and t.get("id")}
        if ids:
            try:
                resp = await asyncio.to_thread(_post, EXPO_RECEIPTS_URL, {"ids": list(ids)})
            except Exception as exc:
                logger.warning("push receipts for %s not available: %s", o["_id"], type(exc).__name__)
                continue
            for rid, r in (resp.get("data") or {}).items():
                err = (r.get("details") or {}).get("error")
                if r.get("status") == "error" and err == "DeviceNotRegistered" and rid in ids:
                    await _disable_token(ids[rid], err)
        await core.db.push_outbox.update_one({"_id": o["_id"]}, {"$set": {"receipts_checked_at": core.now()}})
        checked += 1
    return checked


async def push_pass() -> None:
    """One pass of the background job: retry pending sends, then read receipts."""
    if not ENABLED:
        return
    now = core.now()
    async for o in core.db.push_outbox.find({"status": "pending", "attempts": {"$lt": MAX_ATTEMPTS},
                                             "created_at": {"$gt": now - RETRY_WINDOW},
                                             "$or": [{"locked_until": None}, {"locked_until": {"$lt": now}}]}, {"_id": 1}).limit(50):
        await send_outbox(o["_id"])
    await check_receipts()


async def push_loop() -> None:
    while True:
        try:
            await push_pass()
        except Exception as exc:
            logger.error("push loop error: %s", exc)
        await asyncio.sleep(60)
