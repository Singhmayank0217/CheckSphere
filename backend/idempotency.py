"""Idempotency-Key support for POST requests (case creation, allocation, submissions, uploads).

The app sends a random `Idempotency-Key` with every POST and reuses the same key when it retries after a timeout,
a dropped connection or a 502/503 while the server wakes up. The first request runs normally; a successful JSON
response is stored for 24 hours and replayed for any retry with the same key, so a retry can never create a second
case, request or submission. While the first request is still running, a retry gets 409 request_in_progress and the
app waits and retries.

Keys are scoped to the caller's bearer token and the request path, so one user can never see another user's
response. Failed requests (4xx/5xx) are not stored: a retry runs again and gets a fresh answer.
Requests without the header (older app builds, scripts) behave exactly as before.
"""
import hashlib
import json
import logging
from datetime import timedelta

from pymongo.errors import DuplicateKeyError

import core

logger = logging.getLogger(__name__)

TTL = timedelta(hours=24)
STALE_AFTER = timedelta(seconds=180)  # a claim left by a request that died (e.g. container stopped) can be retaken
MAX_STORED_BODY = 512 * 1024


def _send_json(send, status: int, payload: dict, extra_headers=()):
    body = json.dumps(payload).encode()

    async def go():
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                *extra_headers]})
        await send({"type": "http.response.body", "body": body})
    return go()


class IdempotencyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        key = (headers.get(b"idempotency-key") or b"").decode(errors="ignore").strip()[:100]
        auth = headers.get(b"authorization") or b""
        if not key or not auth:  # unauthenticated POSTs (login) are safe to repeat and are not tracked
            return await self.app(scope, receive, send)
        doc_id = hashlib.sha256(auth + b"|" + scope["path"].encode() + b"|" + key.encode()).hexdigest()
        coll = core.db.idempotency_keys
        now = core.now()
        try:
            await coll.insert_one({"_id": doc_id, "state": "in_progress", "path": scope["path"], "created_at": now,
                                   "expires_at": now + TTL})
        except DuplicateKeyError:
            doc = await coll.find_one({"_id": doc_id})
            if doc and doc.get("state") == "done":
                body = doc["body"]
                await send({"type": "http.response.start", "status": doc["status"],
                            "headers": [(b"content-type", doc.get("content_type", "application/json").encode()),
                                        (b"content-length", str(len(body)).encode()), (b"idempotent-replay", b"true")]})
                await send({"type": "http.response.body", "body": body})
                return
            stale = doc and doc.get("created_at") and now - doc["created_at"] > STALE_AFTER
            if not stale or not (await coll.update_one({"_id": doc_id, "state": "in_progress", "created_at": doc["created_at"]},
                                                       {"$set": {"created_at": now}})).modified_count:
                return await _send_json(send, 409, {"detail": {"code": "request_in_progress",
                                                               "message": "This request is still being processed. Please wait."}})

        captured = {"status": 500, "ctype": b"", "body": []}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                captured["ctype"] = dict(message.get("headers") or []).get(b"content-type", b"")
            elif message["type"] == "http.response.body":
                captured["body"].append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException:
            await coll.delete_one({"_id": doc_id, "state": "in_progress"})
            raise
        body = b"".join(captured["body"])
        if 200 <= captured["status"] < 300 and captured["ctype"].startswith(b"application/json") and len(body) <= MAX_STORED_BODY:
            await coll.update_one({"_id": doc_id}, {"$set": {"state": "done", "status": captured["status"], "body": body,
                                                             "content_type": captured["ctype"].decode()}})
        else:
            await coll.delete_one({"_id": doc_id, "state": "in_progress"})
