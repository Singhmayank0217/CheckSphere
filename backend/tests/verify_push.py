"""Isolated verification of remote push notifications (new case assigned / case reassigned) and assignment rules.

SAFE BY CONSTRUCTION:
  * own backend on a free port against a throwaway LOCAL MongoDB (dropped at the end);
  * Expo push delivery goes to a FAKE Expo server on 127.0.0.1 started by this script - nothing is ever sent to the
    real Expo/Firebase services (the script refuses to run if the push URLs are not local);
  * no file storage is used (R2 disabled).

Run from the repo root:  .venv\\Scripts\\python.exe backend\\tests\\verify_push.py
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
from dotenv import dotenv_values
from pymongo import MongoClient

BACKEND = Path(__file__).resolve().parents[1]
DB_NAME = f"checksphere_verify_{uuid.uuid4().hex[:8]}"
LOCAL = os.environ.get("VERIFY_LOCAL_MONGO", "mongodb://localhost:27017")
RESULTS = []
TITLE_NEW, TITLE_RE = "New Case Assigned", "Case Reassigned"
BODY_NEW = "A new verification task has been assigned to you. Open CheckSphere to view it."
BODY_RE = "A verification task has been reassigned to you. Open CheckSphere to view it."
# distinctive personal details put into every test case; none may ever appear in a push or a notification
SECRETS = ["Zephyrine Quartermaine", "Obadiah Fenwick", "9876012345", "Lantern Street 77", "Moonvale Apartments", "700777"]


def record(name, ok, detail=""):
    RESULTS.append("PASS" if ok else "FAIL")
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


# ---------------------------------------------------------------- fake Expo push service
class FakeExpo:
    def __init__(self):
        self.sends: list[list[dict]] = []      # one entry per HTTP request (a batch of messages)
        self.receipt_calls: list[dict] = []
        self.fail_next = 0                     # answer the next N send requests with HTTP 500
        self.not_registered: set[str] = set()  # tokens answered with DeviceNotRegistered tickets
        self.receipt_errors: dict[str, str] = {}
        self.lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
                if self.path == "/send":
                    with fake.lock:
                        if fake.fail_next > 0:
                            fake.fail_next -= 1
                            self.send_response(500); self.end_headers(); return
                        msgs = body if isinstance(body, list) else [body]
                        fake.sends.append(msgs)
                        data = [{"status": "error", "message": "not registered", "details": {"error": "DeviceNotRegistered"}}
                                if m["to"] in fake.not_registered else {"status": "ok", "id": f"tkt-{uuid.uuid4().hex[:10]}"}
                                for m in msgs]
                    out = {"data": data}
                elif self.path == "/receipts":
                    with fake.lock:
                        fake.receipt_calls.append(body)
                        out = {"data": {i: ({"status": "error", "details": {"error": fake.receipt_errors[i]}}
                                            if i in fake.receipt_errors else {"status": "ok"}) for i in body.get("ids", [])}}
                else:
                    self.send_response(404); self.end_headers(); return
                raw = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def messages(self):
        with self.lock:
            return [m for batch in self.sends for m in batch]

    def wait_for(self, count, timeout=12.0):
        end = time.time() + timeout
        while time.time() < end:
            if len(self.messages()) >= count:
                return True
            time.sleep(0.2)
        return len(self.messages()) >= count


def main() -> int:
    fake = FakeExpo()
    push_url, receipts_url = f"{fake.url}/send", f"{fake.url}/receipts"
    assert push_url.startswith("http://127.0.0.1:") and receipts_url.startswith("http://127.0.0.1:"), "push URLs must be local"
    env = {**os.environ, **{k: v for k, v in dotenv_values(BACKEND / ".env").items() if v},
           "MONGO_URL": LOCAL, "DB_NAME": DB_NAME, "SEED_DEMO_DATA": "true", "APP_ENV": "verify", "MEDIA_FOLDER_ENV": "verify",
           "GEOCODING_PROVIDER": "off", "R2_BUCKET": "", "BACKUP_DIR": str(Path(os.environ.get("TEMP", ".")) / DB_NAME),
           "PUSH_ENABLED": "true", "EXPO_PUSH_URL": push_url, "EXPO_RECEIPTS_URL": receipts_url, "EXPO_ACCESS_TOKEN": "",
           "SERVERLESS_MODE": "true"}  # no timer-driven jobs: the test drives the retry/receipt pass itself
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    log_path = Path(os.environ.get("TEMP", ".")) / f"{DB_NAME}.log"
    log = open(log_path, "w")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT)
    api = f"http://127.0.0.1:{port}/api"
    mongo = MongoClient(LOCAL)
    db = mongo[DB_NAME]
    try:
        for _ in range(60):
            try:
                if requests.get(f"http://127.0.0.1:{port}/health", timeout=2).ok:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        time.sleep(2)

        def login(ident, pw, new_pw=None):
            j = requests.post(f"{api}/auth/login", json={"identifier": ident, "password": pw, "device_id": uuid.uuid4().hex},
                              timeout=30).json()
            h = {"Authorization": f"Bearer {j['access_token']}"}
            if j.get("must_change_password") and new_pw:
                requests.post(f"{api}/auth/change-password", headers=h,
                              json={"current_password": pw, "new_password": new_pw}, timeout=30).raise_for_status()
            return h, j["user"]

        def post(path, h, body, key=None):
            hh = {**h, **({"Idempotency-Key": key} if key else {})}
            return requests.post(f"{api}{path}", headers=hh, json=body, timeout=30)

        def tok():
            return f"ExponentPushToken[{uuid.uuid4().hex[:22]}]"

        A, _ = login("admin@checksphere.app", "Admin@12345")
        S, su = login("sup1@checksphere.app", "Super@12345", "Verify@Sup1xx")
        clients = requests.get(f"{api}/clients", headers=A, timeout=30).json()
        clients = clients.get("items", clients) if isinstance(clients, dict) else clients
        client_id = clients[0]["id"]

        # Supervisor limited to West Bengal; agents in other regions / teams
        r = requests.put(f"{api}/users/{su['id']}", headers=A, json={"scope": {"states": ["West Bengal"]}}, timeout=30)
        record("supervisor scoped to West Bengal", r.ok)

        def new_agent(name, region, team):
            r = post("/users", A, {"name": name, "role": "agent", "password": "Temp@Agent123", "scope": {"states": [region], "team": team}})
            r.raise_for_status()
            return r.json()

        ag1 = new_agent("Push Agent One", "West Bengal", "East")
        ag2 = new_agent("Push Agent Two", "Kerala", "South")
        ag3 = new_agent("Push Agent Three", "Maharashtra", "West")
        ag_off = new_agent("Inactive Agent", "Punjab", "North")
        H1a, _ = login(ag1["agent_id"], "Temp@Agent123", "Verify@Agent1x")
        H1b, _ = login(ag1["agent_id"], "Verify@Agent1x")          # same agent, second phone
        H2, _ = login(ag2["agent_id"], "Temp@Agent123", "Verify@Agent2x")
        H3, _ = login(ag3["agent_id"], "Temp@Agent123", "Verify@Agent3x")
        post(f"/users/{ag_off['id']}/set-active", A, {"active": False}).raise_for_status()

        # ---- registration rules
        T1a, T1b, T2, T3 = tok(), tok(), tok(), tok()
        record("supervisor cannot register a push token", post("/push/register", S, {"token": tok()}).status_code == 403)
        record("super admin cannot register a push token", post("/push/register", A, {"token": tok()}).status_code == 403)
        record("unauthenticated registration refused", requests.post(f"{api}/push/register", json={"token": tok()}, timeout=30).status_code == 401)
        record("malformed token refused", post("/push/register", H1a, {"token": "not-a-token-at-all"}).status_code == 400)
        ok = all(post("/push/register", h, {"token": t, "device_id": d, "platform": "android"}).ok
                 for h, t, d in ((H1a, T1a, "phone-1a"), (H1b, T1b, "phone-1b"), (H2, T2, "phone-2"), (H3, T3, "phone-3")))
        record("agents register tokens (agent 1 on two phones)", ok)
        record("re-registering the same token is idempotent", post("/push/register", H1a, {"token": T1a}).ok
               and db.push_devices.count_documents({"token": T1a}) == 1)
        before = db.push_devices.find_one({"token": T1a})["updated_at"]
        burst = [post("/push/register", H1a, {"token": T1a}).status_code for _ in range(20)]
        record("repeated identical registrations within a minute are acknowledged without a database write",
               burst == [200] * 20 and db.push_devices.find_one({"token": T1a})["updated_at"] == before)
        r = post("/push/register", H1a, {"token": T1a, "device_id": "phone-1a-new"})
        record("changed device details are written even inside the throttle window",
               r.ok and db.push_devices.find_one({"token": T1a}).get("device_id") == "phone-1a-new")
        post("/push/register", H1a, {"token": T1a, "device_id": "phone-1a", "platform": "android"}).raise_for_status()
        devs = list(db.push_devices.find({}, {"user_id": 1, "token": 1}))
        record("each token bound to its own logged-in agent",
               {d["token"]: d["user_id"] for d in devs} == {T1a: ag1["id"], T1b: ag1["id"], T2: ag2["id"], T3: ag3["id"]})

        def case_body(**extra):
            return {"client_id": client_id, "applicant_name": SECRETS[0], "co_applicant_name": SECRETS[1],
                    "report_type": "residence_applicant", "loan_type": "Home Loan", "primary_phone": SECRETS[2],
                    "assigned_address": f"{SECRETS[3]}, {SECRETS[4]}", "pincode": SECRETS[5], "state": "West Bengal", **extra}

        def to(m):
            return m["to"]

        # ---- 1. new case created with an agent
        n0 = len(fake.messages())
        c1 = post("/cases", A, case_body(agent_id=ag1["id"]))
        record("admin creates a case assigned to agent 1", c1.ok, f"HTTP {c1.status_code}")
        c1 = c1.json()
        fake.wait_for(n0 + 2)
        new = fake.messages()[n0:]
        record("'New Case Assigned' pushed to both of agent 1's phones only",
               sorted(map(to, new)) == sorted([T1a, T1b]) and all(m["title"] == TITLE_NEW and m["body"] == BODY_NEW for m in new),
               f"{len(new)} message(s)")
        m = new[0] if new else {}
        record("push data is only {type, case_id, notification_id}, channel 'assignments'",
               set(m.get("data", {})) == {"type", "case_id", "notification_id"} and m["data"]["type"] == "case_assigned"
               and m["data"]["case_id"] == c1["id"] and m.get("channelId") == "assignments")
        nid = (m.get("data") or {}).get("notification_id")
        note = db.notifications.find_one({"_id": __import__("bson").ObjectId(nid)}) if nid else None
        record("in-app notification still created for the agent and linked to the push",
               bool(note) and note["user_id"] == ag1["id"] and note.get("push_queued") is True)
        out = db.push_outbox.find_one({"case_id": c1["id"]})
        record("outbox entry marked sent", bool(out) and out["status"] == "sent" and out["attempts"] == 1)

        # ---- 2. unassigned case, then assigned -> 'New Case Assigned'
        c2 = post("/cases", A, case_body()).json()
        time.sleep(1)
        n0 = len(fake.messages())
        record("creating an unassigned case sends no push", len(fake.messages()) == n0)
        r = post(f"/cases/{c2['id']}/assign", S, {"agent_id": ag2["id"]})
        fake.wait_for(n0 + 1)
        new = fake.messages()[n0:]
        record("supervisor (West Bengal) assigns to agent 2 (Kerala, team South): allowed", r.ok, f"HTTP {r.status_code}")
        record("'New Case Assigned' pushed to agent 2 only", [to(x) for x in new] == [T2] and new[0]["title"] == TITLE_NEW)

        # ---- 3. reassignment -> only the new agent
        n0 = len(fake.messages())
        r = post(f"/cases/{c2['id']}/assign", S, {"agent_id": ag3["id"], "reason": "workload"})
        fake.wait_for(n0 + 1)
        time.sleep(1)
        new = fake.messages()[n0:]
        record("supervisor reassigns to agent 3 (Maharashtra, team West): allowed", r.ok, f"HTTP {r.status_code}")
        record("'Case Reassigned' pushed to agent 3 only; previous agent 2 not notified",
               [to(x) for x in new] == [T3] and new[0]["title"] == TITLE_RE and new[0]["body"] == BODY_RE
               and new[0]["data"]["type"] == "case_reassigned")
        prev_notes = db.notifications.count_documents({"user_id": ag2["id"], "case_id": c2["id"], "title": "Case reassigned to you"})
        record("no reassignment notification for the previous agent", prev_notes == 0)

        # ---- 4. same agent again -> no push (in-app notification behaviour unchanged)
        n0 = len(fake.messages())
        before = db.notifications.count_documents({"user_id": ag3["id"], "case_id": c2["id"]})
        r = post(f"/cases/{c2['id']}/assign", S, {"agent_id": ag3["id"]})
        time.sleep(1.5)
        record("re-assigning to the same agent sends no push", r.ok and len(fake.messages()) == n0)
        record("in-app notification for same-agent assign kept as before",
               db.notifications.count_documents({"user_id": ag3["id"], "case_id": c2["id"]}) == before + 1)

        # ---- 5. retried request with the same Idempotency-Key -> one push
        n0 = len(fake.messages())
        key = str(uuid.uuid4())
        r1 = post(f"/cases/{c2['id']}/assign", A, {"agent_id": ag1["id"]}, key=key)
        r2 = post(f"/cases/{c2['id']}/assign", A, {"agent_id": ag1["id"]}, key=key)
        fake.wait_for(n0 + 2)
        time.sleep(1.5)
        new = fake.messages()[n0:]
        record("retry with the same Idempotency-Key replays the first answer", r1.ok and r2.ok and r2.headers.get("Idempotent-Replay"))
        record("retried assignment pushed exactly once (to agent 1's two phones)", sorted(map(to, new)) == sorted([T1a, T1b]),
               f"{len(new)} message(s)")

        # ---- 6. supervisor creates a case for an agent outside its own region
        n0 = len(fake.messages())
        r = post("/cases", S, case_body(agent_id=ag2["id"]))
        fake.wait_for(n0 + 1)
        record("supervisor creates a case for agent 2 in another region/team: allowed", r.ok, f"HTTP {r.status_code}")
        record("... and agent 2 gets 'New Case Assigned'", [to(x) for x in fake.messages()[n0:]] == [T2])

        # ---- 6b. supervisor WITH an agent_ids scope (and a state scope) creates cases for agents outside it
        r = post("/users", A, {"name": "Scoped Supervisor", "role": "supervisor", "email": f"sup-{uuid.uuid4().hex[:6]}@example.test",
                               "password": "Temp@Super123", "scope": {"agent_ids": [ag1["id"]], "states": ["West Bengal"]}})
        r.raise_for_status()
        s2 = r.json()
        S2, _ = login(s2["email"], "Temp@Super123", "Verify@Sup2xxx")
        record("scoped supervisor has agent_ids configured (agent 1 only)",
               db.users.find_one({"_id": __import__("bson").ObjectId(s2["id"])})["scope"]["agent_ids"] == [ag1["id"]])
        for ag, token, region in ((ag2, T2, "Kerala/South"), (ag3, T3, "Maharashtra/West")):
            n0 = len(fake.messages())
            r = post("/cases", S2, case_body(agent_id=ag["id"]))
            record(f"scoped supervisor creates a case for an agent outside agent_ids ({region}): allowed", r.ok, f"HTTP {r.status_code}")
            cid = r.json().get("id") if r.ok else None
            fake.wait_for(n0 + 1)
            time.sleep(1.5)
            mine = [x for x in fake.messages()[n0:] if x["data"]["case_id"] == cid]
            record(f"... exactly one 'New Case Assigned' push to that agent ({region})",
                   len(mine) == 1 and mine[0]["to"] == token and mine[0]["title"] == TITLE_NEW
                   and db.push_outbox.count_documents({"case_id": cid}) == 1, f"{len(mine)} push(es)")
            saved = db.cases.find_one({"_id": __import__("bson").ObjectId(cid)}) if cid else None
            record(f"... case saved as assigned to that agent, with audit and in-app notification ({region})",
                   bool(saved) and saved["assigned_agent_id"] == ag["id"] and saved["status"] == "assigned"
                   and db.audit_logs.count_documents({"action": "case_assigned", "entity_id": cid}) == 1
                   and db.notifications.count_documents({"user_id": ag["id"], "case_id": cid, "kind": "assignment"}) == 1)
            record(f"... the creating supervisor can still open the case ({region})",
                   requests.get(f"{api}/cases/{cid}", headers=S2, timeout=30).ok)
        n0 = len(fake.messages())
        admin_id = db.users.find_one({"role": "super_admin"})["_id"]
        refused = [("inactive agent", ag_off["id"]), ("supervisor account", su["id"]), ("super admin account", str(admin_id)),
                   ("unknown id", "64b000000000000000000000"), ("malformed id", "not-an-object-id")]
        for label, target in refused:
            r = post("/cases", S2, case_body(agent_id=target))
            record(f"scoped supervisor creating a case for {label} refused", r.status_code == 400, f"HTTP {r.status_code}")
        r = post("/cases", H2, case_body(agent_id=ag3["id"]))
        record("an agent cannot create a case for another agent", r.status_code == 403, f"HTTP {r.status_code}")
        r = requests.post(f"{api}/cases", json=case_body(agent_id=ag2["id"]), timeout=30)
        record("unauthenticated case creation refused", r.status_code == 401, f"HTTP {r.status_code}")
        time.sleep(1)
        record("refused case creations sent no push and created no case",
               len(fake.messages()) == n0 and db.cases.count_documents({"created_by": s2["id"]}) == 2)

        # ---- 7. invalid assignments are refused, and push nothing
        n0 = len(fake.messages())
        bad = [("inactive agent", post(f"/cases/{c2['id']}/assign", S, {"agent_id": ag_off["id"]}), 400),
               ("supervisor account", post(f"/cases/{c2['id']}/assign", S, {"agent_id": su["id"]}), 400),
               ("unknown id", post(f"/cases/{c2['id']}/assign", S, {"agent_id": "64b000000000000000000000"}), 400),
               ("create with inactive agent", post("/cases", S, case_body(agent_id=ag_off["id"])), 400)]
        for label, resp, code in bad:
            record(f"assignment to {label} refused", resp.status_code == code, f"HTTP {resp.status_code}")
        record("agent cannot assign cases", post(f"/cases/{c2['id']}/assign", H2, {"agent_id": ag2["id"]}).status_code == 403)
        record("unauthenticated assign refused",
               requests.post(f"{api}/cases/{c2['id']}/assign", json={"agent_id": ag2["id"]}, timeout=30).status_code == 401)
        time.sleep(1)
        record("refused assignments sent no push", len(fake.messages()) == n0)

        # ---- 8. case request approved and allocated
        now_doc = {"request_type": "Residence Verification", "applicant_name": SECRETS[0], "primary_phone": SECRETS[2],
                   "full_address": SECRETS[3], "branch_name": "Main", "pincode": SECRETS[5], "verification_state": "West Bengal",
                   "bank_state": "West Bengal", "client_name": clients[0]["name"], "supervisor_id": su["id"],
                   "status": "sent_for_allocation", "requested_by": ag3["id"], "requested_by_name": "Push Agent Three",
                   "documents": [{"id": "d1"}], "history": [], "comments": [], "declaration": True}
        rid = str(db.case_requests.insert_one(now_doc).inserted_id)
        n0 = len(fake.messages())
        r = post(f"/requests/{rid}/action", S, {"action": "approve", "agent_id": ag2["id"]})
        fake.wait_for(n0 + 1)
        new = fake.messages()[n0:]
        record("supervisor approves a request and allocates agent 2", r.ok, f"HTTP {r.status_code} {r.text[:120] if not r.ok else ''}")
        record("allocated agent gets 'New Case Assigned'", [to(x) for x in new] == [T2] and new and new[0]["title"] == TITLE_NEW)

        # ---- 9. logout stops pushes to that phone
        r = post("/auth/logout", H1a, {})
        record("agent 1 logs out on phone A; its token is removed", r.ok and db.push_devices.count_documents({"token": T1a}) == 0)
        n0 = len(fake.messages())
        post("/cases", A, case_body(agent_id=ag1["id"])).raise_for_status()
        fake.wait_for(n0 + 1)
        time.sleep(1)
        record("next assignment reaches only agent 1's remaining phone", [to(x) for x in fake.messages()[n0:]] == [T1b])

        # ---- 10. revoked session (e.g. remote logout / deactivation) gets nothing
        db.sessions.update_many({"user_id": ag3["id"]}, {"$set": {"revoked_at": db.command("isMaster")["localTime"]}})
        n0 = len(fake.messages())
        c3 = post("/cases", A, case_body(agent_id=ag3["id"])).json()
        time.sleep(2)
        out = db.push_outbox.find_one({"case_id": c3["id"]})
        record("agent with only revoked sessions receives no push", len(fake.messages()) == n0 and out and out["status"] == "no_devices")
        record("... but the in-app notification is still created",
               db.notifications.count_documents({"user_id": ag3["id"], "case_id": c3["id"]}) == 1)

        # ---- 11. DeviceNotRegistered disables the token
        fake.not_registered.add(T2)
        n0 = len(fake.messages())
        c4 = post("/cases", A, case_body(agent_id=ag2["id"])).json()
        fake.wait_for(n0 + 1)
        time.sleep(1)
        d2 = db.push_devices.find_one({"token": T2})
        record("DeviceNotRegistered ticket switches the token off", bool(d2) and d2.get("disabled_at") is not None
               and d2.get("last_error") == "DeviceNotRegistered")
        n0 = len(fake.messages())
        post("/cases", A, case_body(agent_id=ag2["id"])).raise_for_status()
        time.sleep(2)
        record("disabled token is not used again", len(fake.messages()) == n0)
        fake.not_registered.clear()
        record("re-registering after reinstall re-enables the token", post("/push/register", H2, {"token": T2}).ok
               and db.push_devices.find_one({"token": T2}).get("disabled_at") is None)

        # ---- 12. transport failure -> pending, retried by the background pass; never fails the assignment
        fake.fail_next = 5
        c5 = post("/cases", A, case_body(agent_id=ag1["id"]))
        time.sleep(2)
        out = db.push_outbox.find_one({"case_id": c5.json()["id"]})
        record("assignment succeeds even when the push service is down", c5.ok)
        record("failed send stays pending for retry", bool(out) and out["status"] == "pending" and out["attempts"] == 1,
               f"{out and out['status']}/{out and out['attempts']}")
        record("in-app notification created although the push failed",
               db.notifications.count_documents({"user_id": ag1["id"], "case_id": c5.json()["id"]}) == 1)

        # drive the background job in-process (same throwaway DB, same fake server)
        os.environ.update({"MONGO_URL": LOCAL, "DB_NAME": DB_NAME, "PUSH_ENABLED": "true", "EXPO_PUSH_URL": push_url,
                           "EXPO_RECEIPTS_URL": receipts_url, "EXPO_ACCESS_TOKEN": "", "JWT_SECRET": "x" * 48})
        sys.path.insert(0, str(BACKEND))
        import push_service  # noqa: E402  (reads the variables above)
        assert push_service.EXPO_PUSH_URL == push_url and push_service.ENABLED

        async def job(fn, *a):
            import core
            core.client = __import__("motor.motor_asyncio", fromlist=["x"]).AsyncIOMotorClient(LOCAL, tz_aware=True)
            core.db = core.client[DB_NAME]
            return await fn(*a)

        fake.fail_next = 0
        db.push_outbox.update_one({"_id": out["_id"]}, {"$set": {"locked_until": None}})
        n0 = len(fake.messages())
        asyncio.run(job(push_service.push_pass))
        out = db.push_outbox.find_one({"_id": out["_id"]})
        record("background pass retries and delivers the pending push", out["status"] == "sent" and out["attempts"] == 2
               and [to(x) for x in fake.messages()[n0:]] == [T1b])
        n0 = len(fake.messages())
        asyncio.run(job(push_service.push_pass))
        record("a second background pass does not resend", len(fake.messages()) == n0)

        # ---- 13. duplicate protection at the outbox level
        async def twice():
            a = await push_service.queue_assignment_push("case_assigned", c1["id"], ag1["id"], "fixed-key", None)
            b = await push_service.queue_assignment_push("case_assigned", c1["id"], ag1["id"], "fixed-key", None)
            await asyncio.sleep(1.5)
            return a, b
        n0 = len(fake.messages())
        a, b = asyncio.run(job(twice))
        record("same assignment queued twice is pushed once", a is True and b is False
               and db.push_outbox.count_documents({"dedupe_key": f"case_assigned:{c1['id']}:{ag1['id']}:fixed-key"}) == 1
               and len(fake.messages()) - n0 == 1)

        # ---- 14. delivery receipts: DeviceNotRegistered after delivery switches the token off
        sent = db.push_outbox.find_one({"case_id": c5.json()["id"]})
        tid = next(t["id"] for t in sent["tickets"] if t["status"] == "ok")
        fake.receipt_errors[tid] = "DeviceNotRegistered"
        db.push_outbox.update_many({"status": "sent"}, {"$set": {"sent_at": db.command("isMaster")["localTime"] - timedelta(minutes=20)}})
        asyncio.run(job(push_service.check_receipts))
        record("receipts are read and an uninstalled app's token is switched off",
               bool(fake.receipt_calls) and db.push_devices.find_one({"token": T1b}).get("disabled_at") is not None)

        # ---- 15. a phone that changes hands moves to the new agent; unregister works
        T9 = tok()
        H1c, _ = login(ag1["agent_id"], "Verify@Agent1x")
        post("/push/register", H1c, {"token": T9}).raise_for_status()
        H2b, _ = login(ag2["agent_id"], "Verify@Agent2x")
        post("/push/register", H2b, {"token": T9}).raise_for_status()
        record("token re-registered by another agent now belongs only to that agent",
               db.push_devices.count_documents({"token": T9}) == 1 and db.push_devices.find_one({"token": T9})["user_id"] == ag2["id"])
        r = post("/push/unregister", H1c, {"token": T9})
        record("an agent cannot unregister another agent's token", r.ok and r.json()["removed"] == 0
               and db.push_devices.count_documents({"token": T9}) == 1)
        r = post("/push/unregister", H2b, {"token": T9})
        record("the owner can unregister it", r.ok and r.json()["removed"] == 1)

        # ---- 16. privacy: nothing personal in any push or in-app notification
        blob = json.dumps(fake.messages())
        record("no applicant name, phone, address or pincode in any push", not any(x in blob for x in SECRETS),
               f"{len(fake.messages())} pushes checked")
        notes = json.dumps([{"t": n["title"], "b": n["body"]} for n in db.notifications.find({}, {"title": 1, "body": 1})])
        record("no applicant name, phone, address or pincode in any in-app notification", not any(x in notes for x in SECRETS))
        record("only the two approved push titles were ever sent", {m["title"] for m in fake.messages()} <= {TITLE_NEW, TITLE_RE})
        record("nothing was sent anywhere except the local fake server", all(m["to"].startswith("ExponentPushToken[") for m in fake.messages()))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        fake.server.shutdown()
        mongo.drop_database(DB_NAME)
        print(f"dropped throwaway database {DB_NAME}; server log {log_path}")
    fails = RESULTS.count("FAIL")
    print(f"SUMMARY: {RESULTS.count('PASS')} pass, {fails} fail")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
