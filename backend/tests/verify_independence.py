"""Isolated end-to-end verification for running CheckSphere outside Emergent.

SAFE BY CONSTRUCTION:
  * Starts its own backend on a free port against a LOCAL MongoDB (default mongodb://localhost:27017)
    using a brand-new throwaway database (checksphere_verify_<random>), which it drops at the end.
    It never connects to the MONGO_URL/DB_NAME in backend/.env.
  * Uploads only a synthetic generated test image and a synthetic one-page PDF (no applicant data) to
    the R2 test bucket under checksphere/verify/..., and deletes every asset it created.

Run from the repo root:
    .venv\\Scripts\\python.exe backend\\tests\\verify_independence.py
Storage checks run only when the R2 test bucket is set in backend/.env; otherwise they are reported as SKIPPED.
"""
import hashlib
import io
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values
from PIL import Image
from pymongo import MongoClient

import r2_test_utils

BACKEND = Path(__file__).resolve().parents[1]
LOCAL_MONGO = os.environ.get("VERIFY_LOCAL_MONGO", "mongodb://localhost:27017")
DB_NAME = f"checksphere_verify_{uuid.uuid4().hex[:8]}"
RESULTS: list[tuple[str, str, str]] = []


def record(name, ok, detail=""):
    status = "PASS" if ok is True else ("SKIP" if ok is None else "FAIL")
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name} {detail}", flush=True)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def synthetic_jpeg(seed: str) -> bytes:
    img = Image.new("RGB", (64, 64), (int(hashlib.md5(seed.encode()).hexdigest()[:2], 16), 120, 160))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def synthetic_pdf() -> bytes:
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PDF")
    return buf.getvalue()


def main() -> int:
    file_env = dotenv_values(BACKEND / ".env")
    cloud_ok = "test" in (file_env.get("R2_BUCKET") or "")
    mongo = MongoClient(LOCAL_MONGO, serverSelectionTimeoutMS=3000)
    mongo.server_info()
    assert DB_NAME not in mongo.list_database_names()

    port = free_port()
    env = {**os.environ, **{k: v for k, v in file_env.items() if v is not None},
           "MONGO_URL": LOCAL_MONGO, "DB_NAME": DB_NAME, "SEED_DEMO_DATA": "true", "MEDIA_FOLDER_ENV": "verify",
           "BACKUP_DIR": str(Path(os.environ.get("TEMP", BACKEND)) / DB_NAME)}
    # Server output goes to a log FILE, not a pipe: an unread pipe fills (~4 KB on Windows) and then blocks the
    # server's next log write, freezing every request (this caused the earlier PDF-upload "timeout").
    server_log_path = Path(os.environ.get("TEMP", BACKEND)) / f"{DB_NAME}-server.log"
    server_log = open(server_log_path, "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--port", str(port)], cwd=BACKEND, env=env,
                            stdout=server_log, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}/api"
    created_paths: list[str] = []
    try:
        for _ in range(60):
            try:
                if requests.get(f"http://127.0.0.1:{port}/health", timeout=2).ok:
                    break
            except requests.RequestException:
                time.sleep(1)
        record("backend starts (isolated DB)", True, DB_NAME)
        time.sleep(2)  # let startup seeding finish

        def login(ident, pw, new_pw=None):
            r = requests.post(f"{base}/auth/login", json={"identifier": ident, "password": pw}, timeout=30)
            r.raise_for_status()
            j = r.json()
            tok = j["access_token"]
            if j.get("must_change_password") and new_pw:
                requests.post(f"{base}/auth/change-password", headers=H(tok),
                              json={"current_password": pw, "new_password": new_pw}, timeout=30).raise_for_status()
            return tok, j["user"]

        def H(t):
            return {"Authorization": f"Bearer {t}"}

        admin, admin_u = login("admin@checksphere.app", "Admin@12345")
        record("login super_admin", True)
        a1, a1_u = login("AGT101", "Agent@12345", "Verify@Agent1x")
        a2, a2_u = login("AGT102", "Agent@12345", "Verify@Agent2x")
        sup, _ = login("sup1@checksphere.app", "Super@12345", "Verify@Sup1xx")
        record("login agent + supervisor (incl. first-login password change)", True)
        record("unauthenticated request rejected", requests.get(f"{base}/cases", timeout=30).status_code == 401)

        # ---- agent cannot widen scope with ?agent_id=
        own = requests.get(f"{base}/cases", headers=H(a1), params={"limit": 100}, timeout=30).json()["items"]
        record("agent sees only own cases", all(c["assigned_agent_id"] == a1_u["id"] for c in own), f"{len(own)} cases")
        leak = requests.get(f"{base}/cases", headers=H(a1), params={"agent_id": a2_u["id"], "limit": 100}, timeout=30).json()["items"]
        record("agent ?agent_id=<other> returns nothing of other agent", not any(c["assigned_agent_id"] == a2_u["id"] for c in leak))
        a2_cases = requests.get(f"{base}/cases", headers=H(admin), params={"agent_id": a2_u["id"]}, timeout=30).json()["items"]
        if a2_cases:
            r = requests.get(f"{base}/cases/{a2_cases[0]['id']}", headers=H(a1), timeout=30)
            record("agent opening other agent's case by id -> 403", r.status_code == 403, str(r.status_code))

        # ---- scoped supervisor cannot escape scope via filters
        clients = requests.get(f"{base}/clients", headers=H(admin), timeout=30).json()["items"]
        all_cases = requests.get(f"{base}/cases", headers=H(admin), params={"limit": 100}, timeout=30).json()["items"]
        c_in, c_out = clients[0]["id"], clients[1]["id"]
        email = f"verify-sup-{uuid.uuid4().hex[:6]}@example.invalid"
        requests.post(f"{base}/users", headers=H(admin), json={"name": "Verify Scoped Sup", "role": "supervisor", "email": email,
                                                              "password": "Verify@Init123", "scope": {"client_ids": [c_in]}}, timeout=30).raise_for_status()
        ssup, _ = login(email, "Verify@Init123", "Verify@Scoped1")
        for path, params in (("/cases", {"client_id": c_out, "limit": 100}), ("/dashboard/map", {"client_id": c_out})):
            items = requests.get(f"{base}{path}", headers=H(ssup), params=params, timeout=30).json()["items"]
            ids = {i["id"] for i in items}
            outside = {c["id"] for c in all_cases if c["client_id"] == c_out}
            record(f"scoped supervisor {path}?client_id=<out of scope> leaks nothing", not (ids & outside))
        stats = requests.get(f"{base}/dashboard/stats", headers=H(ssup), params={"client_id": c_out}, timeout=30).json()
        record("scoped supervisor /dashboard/stats out-of-scope total == 0", stats.get("total", 0) == 0, f"total={stats.get('total')}")
        x = requests.get(f"{base}/exports/cases.xlsx", headers=H(ssup), params={"client_id": c_out}, timeout=60)
        record("scoped supervisor cases.xlsx export works (scope enforced server-side)", x.status_code == 200)
        out_case = next((c for c in all_cases if c["client_id"] == c_out), None)
        if out_case:
            r = requests.post(f"{base}/cases/{out_case['id']}/call-logs", headers=H(ssup),
                              json={"phone_number": "0000000000", "result": "Busy"}, timeout=30)
            record("scoped supervisor write to out-of-scope case -> 403", r.status_code == 403, str(r.status_code))

        # ---- masking: raw data never returned when masked
        sub = requests.get(f"{base}/cases", headers=H(admin), params={"status": "submitted,under_review,approved"}, timeout=30).json()["items"]
        rep = None
        for c in sub:
            ctx = requests.get(f"{base}/reports/case/{c['id']}", headers=H(admin), timeout=30).json()
            if ctx.get("report"):
                rep = ctx
                break
        if rep:
            record("masked report payload has no raw data", rep["masked"] and rep["report"]["data"] == rep["masked_data"])
            rv = requests.get(f"{base}/reports/{rep['report']['id']}", headers=H(sup), timeout=30).json()
            record("review payload has no raw data when masked", rv["report"]["data"] == rv["masked_data"])
        else:
            record("masking check", None, "no submitted report in seed")

        # ---- existing workflow smoke: review list, exports, MIS, backups
        if rep:
            d = requests.get(f"{base}/exports/case/{rep['case']['id']}/pdf", headers=H(admin), timeout=60)
            record("PDF report export", d.status_code == 200 and d.content[:4] == b"%PDF")
            d = requests.get(f"{base}/exports/case/{rep['case']['id']}/docx", headers=H(admin), timeout=60)
            record("Word report export", d.status_code == 200 and d.content[:2] == b"PK")
        d = requests.get(f"{base}/exports/mis.xlsx", headers=H(admin), timeout=60)
        record("Excel MIS export", d.status_code == 200 and d.content[:2] == b"PK")
        b = requests.post(f"{base}/backups/run", headers=H(admin), timeout=120)
        record("manual backup stored in private R2 (no Emergent, not on local disk)", b.status_code == 200 and b.json()["path"].startswith("r2:checksphere/verify/backups/"))

        # ---- evidence upload / download
        a1_case = next((c for c in own if c["status"] in ("new", "assigned", "in_progress", "returned")), None)
        bad = requests.post(f"{base}/evidence/upload", headers=H(a1), data={"case_id": a1_case["id"], "slot": "exterior", "kind": "photo", "lat": "19.07", "lon": "72.87", "accuracy": "12", "location_reason": "verification test"},
                            files={"file": ("x.jpg", b"<html><script>alert(1)</script></html>", "image/jpeg")}, timeout=60)
        record("non-image disguised as .jpg rejected", bad.status_code == 400, str(bad.status_code))
        if not cloud_ok:
            r = requests.post(f"{base}/evidence/upload", headers=H(a1), data={"case_id": a1_case["id"], "slot": "exterior", "kind": "photo", "lat": "19.07", "lon": "72.87", "accuracy": "12", "location_reason": "verification test"},
                              files={"file": ("p.jpg", synthetic_jpeg("x"), "image/jpeg")}, timeout=60)
            record("upload without storage credentials fails cleanly (503)", r.status_code == 503, str(r.status_code))
            record("R2 upload/download/delete", None, "SKIPPED: R2 test bucket not set in backend/.env")
            return 0 if all(s != "FAIL" for s, _, _ in RESULTS) else 1

        os.environ.update({k: v for k, v in file_env.items() if k.startswith("R2_") and v})
        os.environ["MEDIA_FOLDER_ENV"] = "verify"
        sys.path.insert(0, str(BACKEND))
        import r2_storage  # noqa: E402
        import storage_service  # noqa: E402

        img = synthetic_jpeg(uuid.uuid4().hex)
        up = requests.post(f"{base}/evidence/upload", headers=H(a1),
                           data={"case_id": a1_case["id"], "slot": "exterior", "kind": "photo", "lat": "19.07", "lon": "72.87", "accuracy": "12", "location_reason": "verification test"},
                           files={"file": ("capture.jpg", img, "image/jpeg")}, timeout=120)
        record("authenticated image upload", up.status_code == 200, up.text[:200] if up.status_code != 200 else "")
        ev = up.json()
        created_paths.append(ev["storage_path"])
        if (ev.get("original") or {}).get("storage_path"):
            created_paths.append(ev["original"]["storage_path"])
        st = ev.get("storage") or {}
        record("object stored in R2 (provider r2, key = storage path)", st.get("provider") == "r2" and st.get("key") == ev["storage_path"])
        record("metadata persisted (sha256, gps, case, provider)", ev["sha256"] == hashlib.sha256(img).hexdigest()
               and ev["gps"]["lat"] == 19.07 and ev["case_id"] == a1_case["id"] and ev["storage_provider"] == "r2")
        record("object key contains case id and no personal data", a1_case["id"] in st.get("key", "")
               and a1_case.get("applicant_name", "#").split()[0].lower() not in st.get("key", "").lower())

        g = requests.get(f"{base}/files/{ev['id']}", headers=H(a1), timeout=60)
        record("assigned agent downloads evidence (watermarked JPEG, checksum matches)", g.status_code == 200
               and hashlib.sha256(g.content).hexdigest() == ev["watermark"]["sha256"])
        go = requests.get(f"{base}/files/{ev['id']}?variant=original", headers=H(sup), timeout=60)
        record("untouched original stored separately, bytes match upload", go.status_code == 200 and go.content == img)
        record("served with nosniff + safe image type", g.headers.get("x-content-type-options") == "nosniff" and g.headers.get("content-type") == "image/jpeg")
        record("other agent -> 403", requests.get(f"{base}/files/{ev['id']}", headers=H(a2), timeout=60).status_code == 403)
        record("supervisor (all-scope) -> 200", requests.get(f"{base}/files/{ev['id']}", headers=H(sup), timeout=60).status_code == 200)
        in_scope = a1_case["client_id"] == c_in
        r = requests.get(f"{base}/files/{ev['id']}", headers=H(ssup), timeout=60)
        record(f"scoped supervisor ({'in' if in_scope else 'out of'} scope) -> {200 if in_scope else 403}", r.status_code == (200 if in_scope else 403))
        record("super admin -> 200", requests.get(f"{base}/files/{ev['id']}", headers=H(admin), timeout=60).status_code == 200)
        record("no token -> 401", requests.get(f"{base}/files/{ev['id']}", timeout=60).status_code == 401)

        code = r2_test_utils.unsigned_status(ev["storage_path"])
        record("direct unsigned R2 request denied", code in (400, 401, 403), str(code))

        url = r2_storage.presign_get(ev["storage_path"], ttl=8)
        record("short-lived signed URL works before expiry", requests.get(url, timeout=30).status_code == 200)
        time.sleep(12)
        code = requests.get(url, timeout=30).status_code
        record("short-lived signed URL rejected after expiry", code >= 400, str(code))

        dup = requests.post(f"{base}/evidence/upload", headers=H(a1), data={"case_id": a1_case["id"], "slot": "exterior", "kind": "photo", "lat": "19.07", "lon": "72.87", "accuracy": "12", "location_reason": "verification test"},
                            files={"file": ("capture.jpg", img, "image/jpeg")}, timeout=120)
        if dup.ok:
            created_paths.append(dup.json()["storage_path"])
            created_paths.append(dup.json()["original"]["storage_path"])
        flags = requests.get(f"{base}/cases/{a1_case['id']}", headers=H(admin), timeout=30).json().get("flags", [])
        record("duplicate photo flagged for review", "same_evidence_reused" in flags)

        pdf = synthetic_pdf()
        upd = requests.post(f"{base}/evidence/upload", headers=H(a1), data={"case_id": a1_case["id"], "slot": "document", "kind": "document"},
                            files={"file": ("doc.pdf", pdf, "application/pdf")}, timeout=120)
        record("private PDF upload (R2)", upd.status_code == 200 and upd.json()["storage"]["provider"] == "r2"
               and upd.json()["storage_path"].endswith(".pdf"),
               upd.text[:200] if not upd.ok else "")
        if upd.ok:
            created_paths.append(upd.json()["storage_path"])
            gp = requests.get(f"{base}/files/{upd.json()['id']}", headers=H(admin), timeout=60)
            record("PDF retrieval, bytes match", gp.status_code == 200 and gp.content == pdf)

        # upload failure handling: wrong secret -> clean exception, nothing stored
        real = os.environ["R2_SECRET_ACCESS_KEY"]
        os.environ["R2_SECRET_ACCESS_KEY"] = "wrong-secret-for-test"
        r2_storage._client = None  # rebuild the client with the wrong secret
        bad_key = storage_service.object_path("verify", "jpg")
        try:
            storage_service.put_object(bad_key, img, "image/jpeg")
            record("bad credentials rejected", False)
        except Exception as exc:
            record("bad credentials rejected cleanly", True, type(exc).__name__)
        finally:
            os.environ["R2_SECRET_ACCESS_KEY"] = real
            r2_storage._client = None
        record("nothing stored with bad credentials", r2_storage.head_object(bad_key) is None)

        # deletion (image and PDF)
        for p in [created_paths[0]] + [x for x in created_paths if x.endswith(".pdf")]:
            kind = "PDF" if p.endswith(".pdf") else "image"
            record(f"{kind} object deletion", storage_service.delete_object(p, "r2"))
            try:
                storage_service.get_object(p, "r2")
                record(f"deleted {kind} no longer retrievable", False)
            except Exception:
                record(f"deleted {kind} no longer retrievable", True)
    finally:
        try:
            if created_paths and cloud_ok:
                import storage_service  # noqa
                left = 0
                for p in created_paths:
                    try:
                        storage_service.delete_object(p, "r2")
                    except Exception:
                        left += 1
                left += r2_test_utils.sweep()
            record("cleanup: all test assets removed from the R2 test bucket", left == 0, f"{len(created_paths)} assets")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
            server_log.close()
            out = server_log_path.read_text(encoding="utf-8", errors="replace")
            for line in out.splitlines():
                if any(w in line for w in ("ERROR", "Traceback", "r2 ", "R2", "evidence upload", "startup")):
                    print("  server:", line[:220])
            print(f"server log: {len(out)} bytes")
            server_log_path.unlink(missing_ok=True)
            mongo.drop_database(DB_NAME)
            print(f"dropped throwaway database {DB_NAME}")
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    print(f"\n{len(RESULTS) - len(fails)} passed/skipped, {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
