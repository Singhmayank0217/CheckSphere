"""Isolated verification of R2 storage (the only provider) and the Railway readiness changes.

SAFE BY CONSTRUCTION:
* Own backend processes on free ports, against a throwaway LOCAL MongoDB that is dropped at the end. The real Atlas
  database is never contacted.
* R2: only a bucket whose name contains "test" is accepted, and only keys under checksphere/verify-r2-<run>/ are written;
  all of them are deleted at the end.

Part A runs without R2 (health/readiness, idempotency, serverless mode, cold start, reports).
Part B needs R2 test credentials in backend/.env (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
R2_BUCKET=checksphere-test); it is reported as SKIP when they are missing.

Run from the repo root:  .venv\\Scripts\\python.exe backend\\tests\\verify_r2_storage.py
"""
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values
from PIL import Image, ImageDraw
from pymongo import MongoClient

BACKEND = Path(__file__).resolve().parents[1]
LOCAL_MONGO = os.environ.get("VERIFY_LOCAL_MONGO", "mongodb://localhost:27017")
RUN = uuid.uuid4().hex[:8]
DB_NAME = f"checksphere_verify_{RUN}"
MEDIA_ENV = f"verify-r2-{RUN}"
PREFIX = f"checksphere/{MEDIA_ENV}/"
TMP = Path(tempfile.gettempdir()) / DB_NAME
PIN = (22.623888, 88.353012)
RESULTS = []


def record(name, ok, detail=""):
    status = "SKIP" if ok is None else ("PASS" if bool(ok) else "FAIL")
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name} {detail}", flush=True)


def photo(seed: str, size=(1200, 900)) -> bytes:
    img = Image.new("RGB", size, (230, 226, 218))
    d = ImageDraw.Draw(img)
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    for i in range(0, size[0], 40):
        d.rectangle([i, size[1] // 3, i + 20, size[1]], fill=((h + i) % 200, 80, 60))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def tiny_pdf(text: str) -> bytes:
    body = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offs.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + o + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for o in offs:
        out.write(f"{o:010d} 00000 n \n".encode())
    out.write(f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Server:
    def __init__(self, env: dict, name: str):
        self.port, self.env, self.name = free_port(), env, name
        self.log_path = TMP / f"{name}.log"
        self.proc = None

    def start(self, wait=True) -> float:
        t0 = time.monotonic()
        self.log = open(self.log_path, "a", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(self.port),
                                      "--timeout-graceful-shutdown", "25"],
                                     cwd=BACKEND, env=self.env, stdout=self.log, stderr=subprocess.STDOUT, text=True)
        if wait:
            for _ in range(240):
                try:
                    if requests.get(f"{self.root}/health", timeout=2).ok:
                        break
                except requests.RequestException:
                    time.sleep(0.25)
        return time.monotonic() - t0

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if getattr(self, "log", None):
            self.log.close()

    @property
    def root(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def api(self):
        return f"{self.root}/api"

    def logtext(self):
        return self.log_path.read_text(encoding="utf-8", errors="ignore")


def H(t, **extra):
    return {"Authorization": f"Bearer {t}", **extra}


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    file_env = {k: v for k, v in dotenv_values(BACKEND / ".env").items() if v is not None}
    have_r2 = all(file_env.get(k) for k in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")) and \
        bool(file_env.get("R2_ACCOUNT_ID") or file_env.get("R2_ENDPOINT"))
    if have_r2 and "test" not in file_env["R2_BUCKET"].lower():
        print(f"Refusing: R2_BUCKET={file_env['R2_BUCKET']!r} is not a test bucket (name must contain 'test').")
        return 2
    base_env = {**os.environ, **file_env, "MONGO_URL": LOCAL_MONGO, "DB_NAME": DB_NAME, "SEED_DEMO_DATA": "true",
                "MEDIA_FOLDER_ENV": MEDIA_ENV, "APP_ENV": MEDIA_ENV, "GEOCODING_PROVIDER": "off",
                "BACKUP_DIR": str(TMP / "backups"), "SERVERLESS_MODE": "false"}
    if not have_r2:
        for k in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_ACCOUNT_ID", "R2_ENDPOINT", "STORAGE_PROVIDER"):
            base_env.pop(k, None)
    # in-process access to storage for setup/inspection/cleanup (same test credentials)
    os.environ.update({k: v for k, v in base_env.items() if k.startswith(("R2_", "MEDIA_FOLDER_ENV", "MONGO_URL",
                                                                           "DB_NAME"))})
    sys.path.insert(0, str(BACKEND))
    import r2_storage  # noqa: E402

    mongo = MongoClient(LOCAL_MONGO, serverSelectionTimeoutMS=3000)
    db = mongo[DB_NAME]
    srv = Server(base_env, "main")
    try:
        boot = srv.start()
        api = srv.api

        def login(ident, pw, new_pw=None):
            j = requests.post(f"{api}/auth/login", json={"identifier": ident, "password": pw}, timeout=30).json()
            if j.get("must_change_password") and new_pw:
                requests.post(f"{api}/auth/change-password", headers=H(j["access_token"]),
                              json={"current_password": pw, "new_password": new_pw}, timeout=30).raise_for_status()
            return j["access_token"], j["user"]

        # ---------------------------------------------------------------- A: no R2 needed
        r = requests.get(f"{srv.root}/health", timeout=10)
        record("10a health endpoint", r.ok and r.json().get("status") == "ok", f"{r.json()} boot {boot:.1f}s")
        r = requests.get(f"{srv.root}/health/ready", timeout=15)
        j = r.json()
        record("10b readiness reports DB + storage", j.get("database") == "ok" and "write_provider" in j.get("storage", {}),
               f"HTTP {r.status_code} {j.get('storage')}")
        record("10c write provider", True, f"new uploads go to: {j.get('storage', {}).get('write_provider')}")

        admin, _ = login("admin@checksphere.app", "Admin@12345")
        a1, a1u = login("AGT101", "Agent@12345", "Verify@Agent1x")
        a2, _ = login("AGT102", "Agent@12345", "Verify@Agent2x")
        sup, _ = login("sup1@checksphere.app", "Super@12345", "Verify@Sup1xx")
        clients = requests.get(f"{api}/clients", headers=H(admin), timeout=30).json()["items"]

        def new_case(tag):
            body = {"client_case_id": f"R2T-{tag}-{uuid.uuid4().hex[:5].upper()}", "client_id": clients[0]["id"],
                    "applicant_name": f"R2 Test {tag}", "report_type": "residence_applicant", "assigned_address": "TEST ADDRESS 1",
                    "primary_phone": "9000000000", "assigned_lat": PIN[0], "assigned_lon": PIN[1]}
            return body

        # 12a idempotent submission: same Idempotency-Key twice -> one case, same id, replay header
        key = str(uuid.uuid4())
        body = new_case("IDEM")
        r1 = requests.post(f"{api}/cases", headers=H(admin, **{"Idempotency-Key": key}), json=body, timeout=30)
        r2 = requests.post(f"{api}/cases", headers=H(admin, **{"Idempotency-Key": key}), json=body, timeout=30)
        n = db.cases.count_documents({"client_case_id": body["client_case_id"]})
        record("12a idempotent case creation (same key twice)", r1.ok and r2.ok and r1.json()["id"] == r2.json()["id"] and n == 1
               and r2.headers.get("idempotent-replay") == "true", f"ids equal={r1.json().get('id') == r2.json().get('id')} cases={n}")
        r3 = requests.post(f"{api}/cases", headers=H(a1, **{"Idempotency-Key": key}), json=new_case("OTHERUSER"), timeout=30)
        record("12b key is scoped per user (other user's replay not served)", r3.json().get("id") != r1.json().get("id"),
               f"HTTP {r3.status_code}")

        cid = r1.json()["id"]
        requests.post(f"{api}/cases/{cid}/assign", headers=H(admin), json={"agent_id": a1u["id"]}, timeout=30).raise_for_status()

        def up(slot, data, token=a1, upload_id=None, case_id=None):
            f = {"case_id": case_id or cid, "slot": slot, "kind": "photo", "captured_at": datetime.now(timezone.utc).isoformat(),
                 "lat": str(PIN[0] + 0.0003), "lon": str(PIN[1] + 0.0002), "accuracy": "8", "gps_status": "ok"}
            if upload_id:
                f["upload_id"] = upload_id
            return requests.post(f"{api}/evidence/upload", headers=H(token), data=f,
                                 files={"file": (f"{slot}.jpg", data, "image/jpeg")}, timeout=120)

        # ---------------------------------------------------------------- B: R2
        if not have_r2:
            for t in ("1 image upload to R2", "2 PDF upload to R2", "3 private access + roles", "4 watermark + original in R2",
                      "5 downloads", "6 reports embed R2 photos", "8 checksum validation",
                      "12c direct upload idempotency"):
                record(t, None, "R2 test credentials not in backend/.env")
        else:
            raw = photo("exterior")
            r = up("exterior", raw, upload_id=f"api-{RUN}-1")
            ev = r.json()
            rec = db.evidence.find_one({"upload_id": f"api-{RUN}-1"})
            wm_head = r2_storage.head_object(rec["storage_path"]) if rec else None
            or_head = r2_storage.head_object(rec["original"]["storage_path"]) if rec else None
            record("1 image upload to R2 (API path)", r.ok and rec and rec["storage_provider"] == "r2" and wm_head and or_head,
                   f"HTTP {r.status_code} provider={rec and rec.get('storage_provider')}")
            record("4 watermarked + original stored privately, checksums match",
                   bool(rec and or_head["size"] == len(raw) and rec["original"]["sha256"] == sha(raw)
                        and wm_head["metadata"].get("sha256") == rec["watermark"]["sha256"]
                        and rec["original"]["storage_provider"] == "r2"),
                   f"original {or_head and or_head['size']} B, watermarked {wm_head and wm_head['size']} B")
            record("4b original filename + case metadata on object",
                   bool(wm_head and wm_head["metadata"].get("case-id") == cid and "original-filename" in wm_head["metadata"]),
                   str(wm_head and wm_head["metadata"]))

            # 12c same upload_id via API -> same record, no new objects
            before = len(r2_storage.client().list_objects_v2(Bucket=r2_storage.bucket(), Prefix=f"{PREFIX}evidence/{cid}/").get("Contents", []))
            r_again = up("exterior", raw, upload_id=f"api-{RUN}-1")
            after = len(r2_storage.client().list_objects_v2(Bucket=r2_storage.bucket(), Prefix=f"{PREFIX}evidence/{cid}/").get("Contents", []))
            record("12c repeated upload_id (API) -> same evidence, no duplicate objects",
                   r_again.json().get("id") == ev.get("id") and before == after and db.evidence.count_documents({"case_id": cid}) == 1,
                   f"objects {before}->{after}")

            # direct upload: authorise -> PUT -> complete
            raw2 = photo("interior")
            uid = f"direct-{RUN}-1"
            grant = requests.post(f"{api}/evidence/upload-url", headers=H(a1), json={
                "case_id": cid, "slot": "interior", "kind": "photo", "upload_id": uid, "size": len(raw2), "sha256": sha(raw2),
                "content_type": "image/jpeg", "filename": "interior.jpg"}, timeout=30)
            g = grant.json()
            r_early = requests.post(f"{api}/evidence/complete", headers=H(a1), data={
                "upload_id": uid, "lat": str(PIN[0]), "lon": str(PIN[1]), "accuracy": "6", "gps_status": "ok"}, timeout=60)
            record("12d complete before PUT -> 409 upload_missing (nothing recorded)",
                   r_early.status_code == 409 and r_early.json()["detail"]["code"] == "upload_missing", f"HTTP {r_early.status_code}")
            bad = requests.put(g["url"], headers=g["headers"], data=raw2[:-10] + b"0123456789", timeout=60)
            record("8a R2 rejects a PUT whose bytes do not match the signed SHA-256", bad.status_code >= 400, f"HTTP {bad.status_code}")
            wrong_user = requests.post(f"{api}/evidence/upload-url", headers=H(a2), json={
                "case_id": cid, "slot": "interior", "kind": "photo", "upload_id": f"x-{RUN}", "size": 10, "sha256": "0" * 64,
                "content_type": "image/jpeg"}, timeout=30)
            record("3a upload authorisation refused for an agent not on the case", wrong_user.status_code == 403,
                   f"HTTP {wrong_user.status_code}")
            put = requests.put(g["url"], headers=g["headers"], data=raw2, timeout=60)
            fields = {"upload_id": uid, "captured_at": datetime.now(timezone.utc).isoformat(), "lat": str(PIN[0] + 0.0002),
                      "lon": str(PIN[1] + 0.0001), "accuracy": "6", "gps_status": "ok"}
            c1 = requests.post(f"{api}/evidence/complete", headers=H(a1), data=fields, timeout=120)
            c2 = requests.post(f"{api}/evidence/complete", headers=H(a1), data=fields, timeout=60)
            g2 = requests.post(f"{api}/evidence/upload-url", headers=H(a1), json={
                "case_id": cid, "slot": "interior", "kind": "photo", "upload_id": uid, "size": len(raw2), "sha256": sha(raw2),
                "content_type": "image/jpeg"}, timeout=30).json()
            drec = db.evidence.find_one({"upload_id": uid})
            incoming_left = r2_storage.client().list_objects_v2(Bucket=r2_storage.bucket(), Prefix=f"{PREFIX}incoming/").get("KeyCount", 0)
            record("1b direct phone->R2 upload (signed PUT, verify, watermark, record)",
                   grant.ok and put.ok and c1.ok and drec and drec["storage_provider"] == "r2" and drec["original"]["sha256"] == sha(raw2)
                   and bool(drec.get("watermark")), f"grant {grant.status_code} put {put.status_code} complete {c1.status_code}")
            record("12e direct upload retries are idempotent", c2.json().get("id") == c1.json().get("id") and g2.get("already_uploaded")
                   and db.evidence.count_documents({"upload_id": uid}) == 1, "")
            record("8b temporary incoming object removed after verification", incoming_left == 0, f"left={incoming_left}")
            record("3b no permanent credential in the grant; URL expires",
                   r2_storage.client()._request_signer._credentials.secret_key not in json.dumps(g) and "X-Amz-Expires=600" in g["url"],
                   "")

            # 8c tampered incoming object (written server-side with different bytes) -> checksum_mismatch
            raw3 = photo("tamper")
            uid3 = f"direct-{RUN}-2"
            g3 = requests.post(f"{api}/evidence/upload-url", headers=H(a1), json={
                "case_id": cid, "slot": "exterior_2", "kind": "photo", "upload_id": uid3, "size": len(raw3), "sha256": sha(raw3),
                "content_type": "image/jpeg"}, timeout=30).json()
            pending = db.pending_uploads.find_one({"upload_id": uid3})
            other = raw3[:-1] + bytes([raw3[-1] ^ 1])
            r2_storage.client().put_object(Bucket=r2_storage.bucket(), Key=pending["key"], Body=other)
            c3 = requests.post(f"{api}/evidence/complete", headers=H(a1), data={"upload_id": uid3, "gps_status": "ok",
                                                                               "lat": str(PIN[0]), "lon": str(PIN[1]), "accuracy": "5"}, timeout=60)
            record("8c server re-verifies SHA-256 after the PUT (tampered object rejected, not recorded)",
                   c3.status_code == 400 and c3.json()["detail"]["code"] == "checksum_mismatch"
                   and not db.evidence.find_one({"upload_id": uid3}), f"HTTP {c3.status_code}")
            _ = g3

            # private access
            unsigned = requests.get(f"{r2_storage.endpoint()}/{r2_storage.bucket()}/{rec['storage_path']}", timeout=30)
            record("3c object not readable without a signature", unsigned.status_code in (400, 401, 403), f"HTTP {unsigned.status_code}")
            r403 = requests.get(f"{api}/files/{ev['id']}", headers=H(a2), timeout=30)
            record("3d other agent cannot download the evidence via the API", r403.status_code == 403, f"HTTP {r403.status_code}")
            ro_agent = requests.get(f"{api}/files/{ev['id']}?variant=original", headers=H(a1), timeout=30)
            record("3e agent cannot download the unwatermarked original", ro_agent.status_code == 403, f"HTTP {ro_agent.status_code}")

            # downloads
            d1 = requests.get(f"{api}/files/{ev['id']}", headers=H(a1), timeout=60)
            d2 = requests.get(f"{api}/files/{ev['id']}?variant=original", headers=H(sup), timeout=60)
            record("5 downloads: watermarked (agent) + original (supervisor) byte-exact",
                   d1.ok and sha(d1.content) == rec["watermark"]["sha256"] and d2.ok and sha(d2.content) == sha(raw),
                   f"{len(d1.content)} B / {len(d2.content)} B")

            # 2 PDF upload (agent 'Upload New Cases') to R2 + download
            pdf = tiny_pdf("CheckSphere R2 test document")
            form = {"state": "West Bengal", "branch_name": "Test Branch", "applicant_name": "PDF Test", "co_applicant_name": "Co Test",
                    "client_name": "Test", "address": "Test address", "pincode": "711202"}
            up_pdf = requests.post(f"{api}/case-uploads", headers=H(a1, **{"Idempotency-Key": f"pdf-{RUN}"}), data=form,
                                   files={"file": ("doc.pdf", pdf, "application/pdf")}, timeout=60)
            up_pdf2 = requests.post(f"{api}/case-uploads", headers=H(a1, **{"Idempotency-Key": f"pdf-{RUN}"}), data=form,
                                    files={"file": ("doc.pdf", pdf, "application/pdf")}, timeout=60)
            if up_pdf.ok:
                urec = db.case_uploads.find_one({"_id": __import__("bson").ObjectId(up_pdf.json()["id"])})
                got = requests.get(f"{api}/case-uploads/{up_pdf.json()['id']}/pdf", headers=H(sup), timeout=60)
                record("2 PDF upload stored in R2 and downloads byte-exact",
                       urec["pdf"]["storage_provider"] == "r2" and got.ok and sha(got.content) == sha(pdf), f"{len(pdf)} B")
                record("12f PDF submission retried with same key -> one submission",
                       up_pdf2.json().get("id") == up_pdf.json()["id"] and db.case_uploads.count_documents({"applicant_name": "PDF Test"}) == 1, "")
            else:
                record("2 PDF upload stored in R2", False, f"HTTP {up_pdf.status_code} {up_pdf.text[:300]}")

            # complete the five mandatory photos (selfie via the direct path, the rest via the API) and submit the report
            raw_s = photo("selfie")
            uid_s = f"direct-{RUN}-selfie"
            gs = requests.post(f"{api}/evidence/upload-url", headers=H(a1), json={
                "case_id": cid, "slot": "selfie", "kind": "photo", "upload_id": uid_s, "size": len(raw_s), "sha256": sha(raw_s),
                "content_type": "image/jpeg"}, timeout=30).json()
            requests.put(gs["url"], headers=gs["headers"], data=raw_s, timeout=60)
            requests.post(f"{api}/evidence/complete", headers=H(a1), data={**fields, "upload_id": uid_s}, timeout=120)
            for sl in ("exterior_2", "document"):
                up(sl, photo(sl), upload_id=f"api-{RUN}-{sl}")
            rctx = requests.get(f"{api}/reports/case/{cid}", headers=H(a1), timeout=30).json()
            vdata = {}
            for sec in rctx["config"]["sections"]:
                for f in sec["fields"]:
                    vdata[f["key"]] = f["options"][0] if f.get("type") in ("select", "multiselect") else (
                        "2" if f.get("type") == "number" else ("1990-05-17" if f.get("type") == "date" else "Observed value for test"))
            requests.post(f"{api}/cases/{cid}/visit-start", headers=H(a1), json={"lat": PIN[0], "lon": PIN[1], "accuracy": 6}, timeout=30)
            sub = requests.post(f"{api}/reports/case/{cid}/submit", headers=H(a1, **{"Idempotency-Key": f"sub-{RUN}"}),
                                json={"data": vdata, "declaration": True}, timeout=120)
            sub2 = requests.post(f"{api}/reports/case/{cid}/submit", headers=H(a1, **{"Idempotency-Key": f"sub-{RUN}"}),
                                 json={"data": vdata, "declaration": True}, timeout=120)
            record("12g report submission retried with the same key -> one submitted report",
                   sub.ok and sub2.status_code == 200 and sub2.headers.get("idempotent-replay") == "true"
                   and db.reports.count_documents({"case_id": cid, "status": "submitted"}) == 1,
                   f"HTTP {sub.status_code}/{sub2.status_code} {'' if sub.ok else sub.text[:300]}")
            photo_shas = [e["watermark"]["sha256"] for e in db.evidence.find({"case_id": cid, "kind": "photo"})]

            # 6 report embeds the actual stored photo
            docx = requests.get(f"{api}/exports/case/{cid}/docx", headers=H(admin), timeout=120)
            media = []
            if docx.ok:
                with zipfile.ZipFile(io.BytesIO(docx.content)) as z:
                    media = [sha(z.read(n)) for n in z.namelist() if n.startswith("word/media/")]
            pdf_r = requests.get(f"{api}/exports/case/{cid}/pdf", headers=H(admin), timeout=120)
            record("6a Word report embeds all five R2 watermarked photos byte-exact",
                   docx.ok and len(photo_shas) == 5 and all(h in media for h in photo_shas),
                   f"HTTP {docx.status_code}, {len(media)} images in docx, {len(photo_shas)} photos on case")
            record("6b PDF report generated from R2 evidence", pdf_r.ok and pdf_r.content.startswith(b"%PDF") and len(pdf_r.content) > 50000,
                   f"{len(pdf_r.content)} B")

        # 7 offline retry (separate case, still open for photos)
        r_c2 = requests.post(f"{api}/cases", headers=H(admin), json=new_case("OFFLINE"), timeout=30).json()
        requests.post(f"{api}/cases/{r_c2['id']}/assign", headers=H(admin), json={"agent_id": a1u["id"]}, timeout=30).raise_for_status()
        cid = r_c2["id"]
        # upload while server is down fails at the network; after restart, same upload_id succeeds once
        srv.stop()
        try:
            requests.post(f"{api}/evidence/upload", timeout=3)
            offline = False
        except requests.RequestException:
            offline = True
        t_cold = srv.start()
        r_retry = up("exterior_2", photo("offline"), upload_id=f"offline-{RUN}")
        r_retry2 = up("exterior_2", photo("offline"), upload_id=f"offline-{RUN}")
        record("7 offline then retry: request fails while down, same upload_id stores exactly once after restart",
               offline and r_retry.ok and r_retry2.json().get("id") == r_retry.json().get("id")
               and db.evidence.count_documents({"upload_id": f"offline-{RUN}"}) == 1, f"HTTP {r_retry.status_code}")
        record("11a cold start: process start -> /health OK", t_cold < 60, f"{t_cold:.1f}s (app retries for ~59s)")

        # 11b serverless mode: no timers at startup; first API request triggers jobs on demand
        srv.stop()
        db.backups.delete_many({})
        sl = Server({**base_env, "SERVERLESS_MODE": "true"}, "serverless")
        sl.start()
        time.sleep(3)
        none_before = db.backups.count_documents({}) == 0
        requests.get(f"{sl.api}/clients", headers=H(admin), timeout=30)
        for _ in range(40):
            if db.backups.count_documents({}):
                break
            time.sleep(0.5)
        b = db.backups.find_one({})
        record("11b SERVERLESS_MODE: no background job until a real request, then backup runs on demand",
               none_before and b is not None and "background jobs run on demand" in sl.logtext(), b and b.get("path"))
        if have_r2 and b:
            record("11c backup stored in private R2 (not on ephemeral disk)", b["path"].startswith("r2:")
                   and r2_storage.head_object(b["path"][3:]) is not None, b["path"])
        # graceful shutdown: only meaningful where terminate() sends SIGTERM (Linux, as on Railway)
        if os.name == "nt":
            sl.stop()
            record("10d SIGTERM graceful shutdown", None, "Windows terminate() is a hard kill; verify on Railway (Linux)")
        else:
            sl.proc.terminate()
            sl.proc.wait(40)
            record("10d SIGTERM: graceful shutdown completes", "Application shutdown complete" in sl.logtext(), "")
            sl.stop()
    finally:
        srv.stop()
        if have_r2:
            try:
                c = r2_storage.client()
                keys = [o["Key"] for o in c.list_objects_v2(Bucket=r2_storage.bucket(), Prefix=PREFIX).get("Contents", [])]
                for k in keys:
                    c.delete_object(Bucket=r2_storage.bucket(), Key=k)
                left = c.list_objects_v2(Bucket=r2_storage.bucket(), Prefix=PREFIX).get("KeyCount", 0)
                print(f"cleanup: deleted {len(keys)} R2 test objects; left {left}")
            except Exception as exc:
                print(f"cleanup R2 failed: {exc}")
        mongo.drop_database(DB_NAME)
        print(f"cleanup: dropped {DB_NAME}; logs in {TMP}")

    fails = [r for r in RESULTS if r[0] == "FAIL"]
    print(f"\nSUMMARY: {sum(r[0] == 'PASS' for r in RESULTS)} pass, {len(fails)} fail, {sum(r[0] == 'SKIP' for r in RESULTS)} skip")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
