"""Isolated verification of: Upload New Cases, Create New Verification, Allocate (renamed) flow, Supervisor Create & Assign,
and real evidence photographs in Word/PDF reports.

SAFE BY CONSTRUCTION: own backend on a free port, throwaway LOCAL MongoDB (dropped at the end), synthetic images/PDFs
only (the R2 test bucket under checksphere/verify/..., all deleted at the end). Geocoding is off.
Run from the repo root:  .venv\\Scripts\\python.exe backend\\tests\\verify_new_features.py
"""
import hashlib
import io
import os
import re
import socket
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values
from PIL import Image, ImageDraw
from pymongo import MongoClient

import r2_test_utils

BACKEND = Path(__file__).resolve().parents[1]
LOCAL_MONGO = os.environ.get("VERIFY_LOCAL_MONGO", "mongodb://localhost:27017")
DB_NAME = f"checksphere_verify_{uuid.uuid4().hex[:8]}"
RESULTS = []
PIN = (19.0760, 72.8777)


def record(name, ok, detail=""):
    status = "SKIP" if ok is None else ("PASS" if bool(ok) else "FAIL")
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name} {detail}", flush=True)


def pdf_bytes(text="CheckSphere test"):
    img = Image.new("RGB", (200, 120), (255, 255, 255))
    ImageDraw.Draw(img).text((10, 50), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PDF")
    return buf.getvalue()


def jpeg(seed, w=1200, h=900):
    r = abs(hash(seed))
    img = Image.new("RGB", (w, h), (r % 200, (r // 7) % 200, (r // 11) % 200))
    ImageDraw.Draw(img).rectangle([w // 4, h // 4, w // 2, h // 2], fill=(240, 240, 240))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def main() -> int:
    file_env = dotenv_values(BACKEND / ".env")
    if "test" not in (file_env.get("R2_BUCKET") or ""):
        print("R2 test bucket (R2_BUCKET=checksphere-test) not configured in backend/.env")
        return 2
    mongo = MongoClient(LOCAL_MONGO, serverSelectionTimeoutMS=3000)
    db = mongo[DB_NAME]
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, **{k: v for k, v in file_env.items() if v is not None}, "MONGO_URL": LOCAL_MONGO, "DB_NAME": DB_NAME,
           "SEED_DEMO_DATA": "true", "MEDIA_FOLDER_ENV": "verify", "GEOCODING_PROVIDER": "off",
           "BACKUP_DIR": str(Path(os.environ.get("TEMP", BACKEND)) / DB_NAME)}
    log_path = Path(os.environ.get("TEMP", BACKEND)) / f"{DB_NAME}-server.log"
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}/api"
    sys.path.insert(0, str(BACKEND))
    os.environ.update({k: v for k, v in file_env.items() if k.startswith("R2_") and v})
    os.environ["MEDIA_FOLDER_ENV"] = "verify"
    import storage_service  # noqa: E402
    try:
        for _ in range(60):
            try:
                if requests.get(f"http://127.0.0.1:{port}/health", timeout=2).ok:
                    break
            except requests.RequestException:
                time.sleep(1)
        time.sleep(2)

        def H(t):
            return {"Authorization": f"Bearer {t}"}

        def login(ident, pw, new_pw=None):
            j = requests.post(f"{base}/auth/login", json={"identifier": ident, "password": pw}, timeout=30).json()
            if j.get("must_change_password") and new_pw:
                requests.post(f"{base}/auth/change-password", headers=H(j["access_token"]),
                              json={"current_password": pw, "new_password": new_pw}, timeout=30).raise_for_status()
            return j["access_token"], j["user"]

        admin, _ = login("admin@checksphere.app", "Admin@12345")
        a1, a1u = login("AGT101", "Agent@12345", "Verify@Agent1x")
        a2, a2u = login("AGT102", "Agent@12345", "Verify@Agent2x")
        sup, supu = login("sup1@checksphere.app", "Super@12345", "Verify@Sup1xx")
        clients = requests.get(f"{base}/clients", headers=H(admin), timeout=30).json()["items"]
        c_in, c_out = clients[0], clients[1]
        em = f"scoped-{uuid.uuid4().hex[:6]}@example.invalid"
        requests.post(f"{base}/users", headers=H(admin), json={"name": "Scoped Sup", "role": "supervisor", "email": em, "password": "Verify@Init123",
                                                              "scope": {"client_ids": [c_in["id"]], "agent_ids": [a1u["id"]]}}, timeout=30).raise_for_status()
        ssup, ssupu = login(em, "Verify@Init123", "Verify@Scoped1")
        em2 = f"statesup-{uuid.uuid4().hex[:6]}@example.invalid"
        requests.post(f"{base}/users", headers=H(admin), json={"name": "State Sup", "role": "supervisor", "email": em2, "password": "Verify@Init123",
                                                              "scope": {"states": ["Kerala"]}}, timeout=30).raise_for_status()
        ssup_state, _ = login(em2, "Verify@Init123", "Verify@State11")

        # =============== 1. Upload New Cases
        states = requests.get(f"{base}/case-uploads/states", headers=H(a1), timeout=30).json()["items"]
        record("State dropdown served by backend (36 states/UTs)", len(states) == 36 and "Maharashtra" in states)
        cases_before = db.cases.count_documents({})
        form = {"state": "Maharashtra", "branch_name": "Andheri Branch", "applicant_name": "Upload Applicant", "co_applicant_name": "Upload Co",
                "co_applicant2_name": "", "requirements": "Verify residence and office; customer available after 6 PM."}
        pdf = pdf_bytes()
        r = requests.post(f"{base}/case-uploads", headers=H(a1), data=form, files={"file": ("loan.pdf", pdf, "application/pdf")}, timeout=120)
        up = r.json() if r.ok else {}
        record("agent uploads case + PDF + requirements without prior approval", r.ok and up.get("status") == "submitted", r.text[:150] if not r.ok else "")
        doc = db.case_uploads.find_one({"_id": __import__("bson").ObjectId(up["id"])}) if up else None
        record("submitting agent id + submission time saved", bool(doc) and doc["submitted_by"] == a1u["id"] and doc.get("submitted_at"))
        record("PDF stored as a private object in R2", bool(doc) and doc["pdf"]["storage_provider"] == "r2"
               and doc["pdf"]["storage"]["key"] == doc["pdf"]["storage_path"])
        record("upload does NOT create or approve a case", db.cases.count_documents({}) == cases_before and up.get("status") != "accepted")
        bad = requests.post(f"{base}/case-uploads", headers=H(a1), data=form, files={"file": ("x.pdf", b"<html>not a pdf</html>", "application/pdf")}, timeout=60)
        record("non-PDF disguised as .pdf rejected (backend signature check)", bad.status_code == 422 and "valid PDF" in bad.text)
        bad = requests.post(f"{base}/case-uploads", headers=H(a1), data={**form, "state": "Atlantis", "co_applicant_name": ""},
                            files={"file": ("x.pdf", pdf, "application/pdf")}, timeout=60)
        record("invalid state / missing required field rejected", bad.status_code == 422 and "State" in bad.text and "Co-applicant" in bad.text)
        big = b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024 + 10)
        bad = requests.post(f"{base}/case-uploads", headers=H(a1), data=form, files={"file": ("big.pdf", big, "application/pdf")}, timeout=120)
        record("PDF over 10 MB rejected", bad.status_code == 422 and "too large" in bad.text)
        record("supervisor cannot submit agent uploads (403)",
               requests.post(f"{base}/case-uploads", headers=H(sup), data=form, files={"file": ("x.pdf", pdf, "application/pdf")}, timeout=60).status_code == 403)
        mine = requests.get(f"{base}/case-uploads", headers=H(a1), timeout=30).json()["items"]
        other = requests.get(f"{base}/case-uploads", headers=H(a2), timeout=30).json()["items"]
        record("agent sees own submissions with status", any(x["id"] == up["id"] and x["status_label"] == "Submitted" for x in mine))
        record("other agent cannot see / open it", not any(x["id"] == up["id"] for x in other)
               and requests.get(f"{base}/case-uploads/{up['id']}", headers=H(a2), timeout=30).status_code == 404
               and requests.get(f"{base}/case-uploads/{up['id']}/pdf", headers=H(a2), timeout=30).status_code == 404)
        g = requests.get(f"{base}/case-uploads/{up['id']}/pdf", headers=H(a1), timeout=60)
        record("own PDF downloadable and identical", g.ok and g.content == pdf)
        record("original filename kept", doc["pdf"]["filename"] == "loan.pdf")
        sg = requests.get(f"{base}/case-uploads/{up['id']}/pdf", headers=H(sup), timeout=60)
        record("supervisor can open the uploaded PDF (authorised access)", sg.ok and sg.content == pdf and sg.headers.get("content-type") == "application/pdf")
        record("supervisor outside the upload's state cannot open it", requests.get(f"{base}/case-uploads/{up['id']}/pdf", headers=H(ssup_state), timeout=30).status_code == 404)
        record("no token -> 401", requests.get(f"{base}/case-uploads/{up['id']}/pdf", timeout=30).status_code == 401)
        code = r2_test_utils.unsigned_status(doc["pdf"]["storage_path"])
        record("direct unsigned R2 request for the PDF denied", code in (400, 401, 403), str(code))
        large_img = Image.frombytes("RGB", (1500, 1500), os.urandom(1500 * 1500 * 3))
        lb = io.BytesIO(); large_img.save(lb, "PDF"); large_pdf = lb.getvalue()
        lr = requests.post(f"{base}/case-uploads", headers=H(a1), data={**form, "applicant_name": "Large PDF"},
                           files={"file": ("Mayank_Full_Stack_AI_Engineer-2.pdf", large_pdf, "application/pdf")}, timeout=300)
        ldoc = db.case_uploads.find_one({"_id": __import__("bson").ObjectId(lr.json()["id"])}) if lr.ok else None
        record("larger PDF accepted with original filename", lr.ok and ldoc["pdf"]["size"] == len(large_pdf) and ldoc["pdf"]["filename"] == "Mayank_Full_Stack_AI_Engineer-2.pdf",
               f"{len(large_pdf) // 1024} KB")
        record("renamed JPEG (.pdf) rejected", requests.post(f"{base}/case-uploads", headers=H(a1), data=form,
               files={"file": ("photo.pdf", jpeg("renamed"), "application/pdf")}, timeout=60).status_code == 422)
        record("'File not found' error body sent as .pdf rejected", requests.post(f"{base}/case-uploads", headers=H(a1), data=form,
               files={"file": ("doc.pdf", b"File not found", "application/pdf")}, timeout=60).status_code == 422)
        record("agent cannot review/accept own upload (403)",
               requests.post(f"{base}/case-uploads/{up['id']}/action", headers=H(a1), json={"action": "accept"}, timeout=30).status_code == 403)
        sv = requests.get(f"{base}/case-uploads", headers=H(sup), timeout=30).json()["items"]
        record("supervisor can view uploaded cases", any(x["id"] == up["id"] for x in sv))
        record("reject without comment refused", requests.post(f"{base}/case-uploads/{up['id']}/action", headers=H(sup), json={"action": "reject"}, timeout=30).status_code == 400)
        r = requests.post(f"{base}/case-uploads/{up['id']}/action", headers=H(sup), json={"action": "review", "comment": "checking"}, timeout=30)
        r2 = requests.post(f"{base}/case-uploads/{up['id']}/action", headers=H(sup), json={"action": "accept", "comment": "ok"}, timeout=30)
        record("supervisor manages status (under review -> accepted), agent sees it", r.ok and r2.ok and r2.json()["status"] == "accepted"
               and any(x["id"] == up["id"] and x["status"] == "accepted" for x in requests.get(f"{base}/case-uploads", headers=H(a1), timeout=30).json()["items"]))
        record("accepting still does not create a case", db.cases.count_documents({}) == cases_before)

        # =============== 2. Create New Verification
        # ---- Create New Verification = Request Type dropdown + the assigned-case verification form
        import requests_routes as rr  # noqa: E402  (REQ_TYPES: the existing Request Type dropdown -> report type mapping)
        record("old 'self-create' request-form shortcut removed",
               requests.post(f"{base}/requests/000000000000000000000000/self-create", headers=H(a1), json={"data": {}}, timeout=30).status_code in (404, 405))
        record("supervisor cannot use agent Create New Verification (403)",
               requests.post(f"{base}/cases/agent-create", headers=H(sup), json={"request_type": "KYC Verification"}, timeout=30).status_code == 403)
        record("unknown request type rejected", requests.post(f"{base}/cases/agent-create", headers=H(a1), json={"request_type": "Bogus"}, timeout=30).status_code == 400)
        created = {}
        for rtype, rep_type in rr.REQ_TYPES.items():
            res = requests.post(f"{base}/cases/agent-create", headers=H(a1), json={"request_type": rtype}, timeout=30)
            c = res.json() if res.ok else {}
            created[rtype] = c
            record(f"Create New Verification '{rtype}' -> {rep_type} case for the agent (same mapping as Allocate)",
                   res.ok and c["report_type"] == rep_type and c["assigned_agent_id"] == a1u["id"] and c["source"] == "agent_created")
        c0 = created["Residence Verification"]
        record("creator, creation time and source saved", c0.get("created_by") == a1u["id"] and c0.get("created_by_role") == "agent" and c0.get("created_at")
               and c0.get("source") == "agent_created")

        # The form an agent gets for a created case IS the assigned-case verification form (same config/fields/slots)
        assigned_ctx = None
        sample_assigned = db.cases.find_one({"report_type": "residence_applicant", "source": {"$ne": "agent_created"}, "assigned_agent_id": a1u["id"]})
        if sample_assigned:
            assigned_ctx = requests.get(f"{base}/reports/case/{sample_assigned['_id']}", headers=H(a1), timeout=30).json()
        created_ctx = requests.get(f"{base}/reports/case/{c0['id']}", headers=H(a1), timeout=30).json()

        def keys(cfg):
            return [(sec["title"], [(f["key"], f["label"], f.get("type"), f.get("required"), tuple(f.get("options") or [])) for f in sec["fields"]]) for sec in cfg["sections"]]
        if assigned_ctx:
            same = keys(assigned_ctx["config"]) == keys(created_ctx["config"]) and assigned_ctx["config"]["photo_slots"] == created_ctx["config"]["photo_slots"] \
                and assigned_ctx["config"]["requires_gps"] == created_ctx["config"]["requires_gps"]
            n_fields = sum(len(f) for _, f in keys(created_ctx["config"]))
            record("created case uses the identical verification form (all sections, fields, options, 5 photo slots, GPS)", same,
                   f"{len(created_ctx['config']['sections'])} sections, {n_fields} fields, {len(created_ctx['config']['photo_slots'])} photo slots")
        record("agent can open + edit the created case", created_ctx.get("can_edit") is True)

        # change request type before photos; locked after photos
        r = requests.post(f"{base}/cases/{created['KYC Verification']['id']}/request-type", headers=H(a1), json={"request_type": "Income Verification"}, timeout=30)
        record("request type can be changed before photos", r.ok and r.json()["report_type"] == rr.REQ_TYPES["Income Verification"])
        record("other agent cannot change type / discard (403)",
               requests.post(f"{base}/cases/{c0['id']}/request-type", headers=H(a2), json={"request_type": "KYC Verification"}, timeout=30).status_code == 403
               and requests.post(f"{base}/cases/{c0['id']}/discard", headers=H(a2), timeout=30).status_code == 403)

        # full verification on the agent-created case: details, five photos, GPS, watermark, submit
        cfg = created_ctx["config"]
        vdata = {}
        for sec in cfg["sections"]:
            for f in sec["fields"]:
                vdata[f["key"]] = f["options"][0] if f.get("type") in ("select", "multiselect") else ("2" if f.get("type") == "number" else ("1990-05-17" if f.get("type") == "date" else "Observed value for test"))
        vdata.update({"applicant_name": "Self Created Applicant", "client_name": c_in["name"], "branch_name": "Andheri", "assigned_address": "7 Agent Entered Road, Mumbai",
                      "client_case_id": "AGT-CLIENT-1", "residence_status": "Parental"})
        d = requests.put(f"{base}/reports/case/{c0['id']}/draft", headers=H(a1), json={"data": vdata, "declaration": True}, timeout=60)
        cc = db.cases.find_one({"_id": __import__("bson").ObjectId(c0["id"])})
        record("details entered in the form are saved onto the agent-created case", d.ok and cc["applicant_name"] == "Self Created Applicant"
               and cc["assigned_address"] == "7 Agent Entered Road, Mumbai" and cc["client_id"] == c_in["id"] and cc["client_case_id"] == "AGT-CLIENT-1")
        ups = []
        for sl in ["exterior", "exterior_2", "interior", "selfie", "document"]:
            u_ = requests.post(f"{base}/evidence/upload", headers=H(a1), timeout=180,
                               data={"case_id": c0["id"], "slot": sl, "kind": "photo", "captured_at": datetime.now(timezone.utc).isoformat(),
                                     "lat": str(PIN[0]), "lon": str(PIN[1]), "accuracy": "6", "gps_status": "ok"},
                               files={"file": ("p.jpg", jpeg("ac" + sl + c0["id"]), "image/jpeg")})
            ups.append(u_)
        record("five photos with GPS + watermark on the agent-created case", all(u_.ok and u_.json().get("watermark") for u_ in ups))
        record("request type locked once photos exist",
               requests.post(f"{base}/cases/{c0['id']}/request-type", headers=H(a1), json={"request_type": "KYC Verification"}, timeout=30).status_code == 400)
        sub = requests.post(f"{base}/reports/case/{c0['id']}/submit", headers=H(a1), json={"data": vdata, "declaration": True}, timeout=60)
        rep = db.reports.find_one({"case_id": c0["id"], "status": "submitted"})
        record("agent submits the verification directly (no supervisor assignment)", sub.ok and rep and rep["data"]["assigned_address"] == "7 Agent Entered Road, Mumbai"
               and rep["data"]["residence_status"] == "Parental", sub.text[:150] if not sub.ok else "")
        record("submitted verification cannot be discarded", requests.post(f"{base}/cases/{c0['id']}/discard", headers=H(a1), timeout=30).status_code == 400)
        agent_cases = requests.get(f"{base}/cases", headers=H(a1), params={"limit": 100}, timeout=30).json()["items"]
        record("agent sees the created case in their list", any(x["id"] == c0["id"] for x in agent_cases))
        record("other agent cannot open it (403)", requests.get(f"{base}/cases/{c0['id']}", headers=H(a2), timeout=30).status_code == 403)
        record("supervisor can monitor it (unscoped + scoped with this agent)",
               any(x["id"] == c0["id"] for x in requests.get(f"{base}/cases", headers=H(sup), params={"limit": 200}, timeout=30).json()["items"])
               and any(x["id"] == c0["id"] for x in requests.get(f"{base}/cases", headers=H(ssup), params={"limit": 200}, timeout=30).json()["items"]))
        record("supervisor can review the agent-created report", requests.get(f"{base}/reports/{rep['_id']}", headers=H(sup), timeout=30).ok)
        x = requests.get(f"{base}/exports/cases.xlsx", headers=H(admin), timeout=60)
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(x.content)).active
        hdr = [c.value for c in ws[1]]
        srcs = [r[hdr.index("Case Source")] for r in ws.iter_rows(min_row=2, values_only=True)] if "Case Source" in hdr else []
        record("distinguishable in exports (Case Source column)", x.ok and "Agent-created verification (direct)" in srcs)
        r = requests.post(f"{base}/cases/{created['Office Verification']['id']}/discard", headers=H(a1), timeout=30)
        record("agent can discard an unsubmitted verification they created (soft delete)", r.ok
               and db.cases.find_one({"_id": __import__("bson").ObjectId(created["Office Verification"]["id"])}).get("deleted_at"))

        def request_data(rtype, **kw):
            d_ = {"request_type": rtype, "applicant_name": "Req Applicant", "co_applicant_name": "", "seller_name": "", "primary_phone": "9000000001",
                  "alt_phone": "", "client_name": c_in["name"], "branch_name": "Some Branch", "bank_state": "Maharashtra", "full_address": "12 Test Road, Mumbai",
                  "pincode": "400001", "verification_state": "Maharashtra", "city": "Mumbai", "notes": "test", "priority": "Normal", "supervisor_id": ssupu["id"]}
            d_.update(kw)
            return d_

        def draft_with_doc(token, d_):
            rid_ = requests.post(f"{base}/requests", headers=H(token), json={"data": d_, "declaration": True}, timeout=30).json()["id"]
            requests.post(f"{base}/requests/{rid_}/document", headers=H(token), files={"file": ("doc.pdf", pdf_bytes(rid_), "application/pdf")}, timeout=120).raise_for_status()
            return rid_

        # Allocate New Verification (renamed) — existing flow unchanged: submit -> supervisor approve
        rid = draft_with_doc(a2, request_data("Office Verification", supervisor_id=supu["id"]))
        s1 = requests.post(f"{base}/requests/{rid}/submit", headers=H(a2), json={"data": request_data("Office Verification", supervisor_id=supu["id"]), "declaration": True}, timeout=30)
        before = db.cases.count_documents({})
        record("Allocate New Verification: submit only sends for allocation (no case yet)", s1.ok and db.cases.count_documents({}) == before
               and db.case_requests.find_one({"_id": __import__("bson").ObjectId(rid)})["status"] == "sent_for_allocation")
        ap = requests.post(f"{base}/requests/{rid}/action", headers=H(sup), json={"action": "approve", "agent_id": a2u["id"], "comment": ""}, timeout=30)
        cap = db.cases.find_one({"source_request_id": rid})
        record("Allocate flow: supervisor approval creates & allocates the case (source agent_request)", ap.ok and cap and cap["report_type"] == rr.REQ_TYPES["Office Verification"]
               and cap["assigned_agent_id"] == a2u["id"] and cap["source"] == "agent_request")

        # =============== 5. Supervisor Create & Assign
        body = {"client_case_id": f"SUP-{uuid.uuid4().hex[:5]}", "client_id": c_in["id"], "applicant_name": "Sup Applicant", "co_applicant_name": "Sup Co",
                "report_type": "residence_applicant", "assigned_address": "5 Supervisor Lane", "primary_phone": "9000000002", "state": "Maharashtra",
                "assigned_lat": PIN[0], "assigned_lon": PIN[1], "agent_id": a1u["id"]}
        r = requests.post(f"{base}/cases", headers=H(ssup), json=body, timeout=30)
        sc_case = r.json() if r.ok else {}
        record("supervisor creates a case and assigns an agent", r.ok and sc_case["assigned_agent_id"] == a1u["id"] and sc_case["status"] == "assigned", r.text[:150] if not r.ok else "")
        record("creator = supervisor, assignee = agent, timestamps + source recorded", sc_case.get("created_by") == ssupu["id"] and sc_case.get("source") == "supervisor_created"
               and sc_case.get("assigned_at") and sc_case.get("created_at") and sc_case.get("assigned_supervisor_id") == ssupu["id"])
        record("assigned case appears in agent's list", any(x["id"] == sc_case.get("id") for x in requests.get(f"{base}/cases", headers=H(a1), params={"limit": 100}, timeout=30).json()["items"]))
        record("agent got an assignment notification", any(n.get("case_id") == sc_case.get("id") for n in requests.get(f"{base}/notifications", headers=H(a1), timeout=30).json()["items"]))
        record("supervisor can view the case and its status", requests.get(f"{base}/cases/{sc_case.get('id')}", headers=H(ssup), timeout=30).json().get("status") == "assigned")
        record("supervisor must pick an agent", requests.post(f"{base}/cases", headers=H(sup), json={**body, "agent_id": None, "client_case_id": "X1"}, timeout=30).status_code == 400)
        record("scoped supervisor: client outside scope -> 403", requests.post(f"{base}/cases", headers=H(ssup), json={**body, "client_id": c_out["id"], "client_case_id": "X2"}, timeout=30).status_code == 403)
        # business rule (19-Nov-2026): supervisors may create cases for ANY active agent, whatever their agent_ids scope
        x3 = requests.post(f"{base}/cases", headers=H(ssup), json={**body, "agent_id": a2u["id"], "client_case_id": "X3"}, timeout=30)
        record("scoped supervisor: agent outside agent_ids scope -> allowed, assigned to that agent",
               x3.ok and x3.json().get("assigned_agent_id") == a2u["id"], f"HTTP {x3.status_code}")
        record("agent cannot create cases via supervisor API (403)", requests.post(f"{base}/cases", headers=H(a1), json={**body, "client_case_id": "X4"}, timeout=30).status_code == 403)
        record("agent cannot use supervisor-only functions (approve request / list users)",
               requests.post(f"{base}/requests/{rid}/action", headers=H(a1), json={"action": "review"}, timeout=30).status_code == 403
               and requests.get(f"{base}/users", headers=H(a1), timeout=30).status_code == 403)
        r = requests.post(f"{base}/cases", headers=H(admin), json={**body, "agent_id": None, "client_case_id": f"ADM-{uuid.uuid4().hex[:4]}"}, timeout=30)
        record("Super Admin can still create an unassigned case (existing behaviour)", r.ok and r.json()["status"] == "new" and r.json()["source"] == "admin_created")

        # =============== 4. Report photos (full workflow on the supervisor-created case)
        cid = sc_case["id"]
        slots = ["exterior", "exterior_2", "interior", "selfie", "document"]
        stored = {}
        for sl in slots:
            rr_ = requests.post(f"{base}/evidence/upload", headers=H(a1), timeout=180,
                                data={"case_id": cid, "slot": sl, "kind": "photo", "captured_at": datetime.now(timezone.utc).isoformat(),
                                      "lat": str(PIN[0] + 0.0002), "lon": str(PIN[1]), "accuracy": "6", "gps_status": "ok"},
                                files={"file": ("p.jpg", jpeg(sl + cid, *((1080, 1440) if sl == "selfie" else (1200, 900))), "image/jpeg")})
            if rr_.ok:
                stored[sl] = rr_.json()
        record("all five photos captured on the supervisor-assigned case (same pipeline)", len(stored) == 5)
        cfg = requests.get(f"{base}/report-types", headers=H(a1), timeout=30).json()["configs"]["residence_applicant"]
        data = {}
        for sec in cfg["sections"]:
            for f in sec["fields"]:
                data[f["key"]] = f["options"][0] if f.get("type") in ("select", "multiselect") else ("2" if f.get("type") == "number" else ("1990-05-17" if f.get("type") == "date" else "Observed value for test"))
        sub = requests.post(f"{base}/reports/case/{cid}/submit", headers=H(a1), json={"data": data, "declaration": True}, timeout=60)
        record("report submitted for the assigned case", sub.ok, sub.text[:150] if not sub.ok else "")
        sc_doc = db.cases.find_one({"_id": __import__("bson").ObjectId(cid)})
        sc_rep = db.reports.find_one({"case_id": cid, "status": "submitted"})
        record("assigned case unchanged: agent form values never overwrite case details / fixed address",
               sc_doc["applicant_name"] == "Sup Applicant" and sc_doc["assigned_address"] == "5 Supervisor Lane"
               and sc_rep["data"]["assigned_address"] == "5 Supervisor Lane" and sc_doc.get("source") == "supervisor_created")
        record("Request Type card not part of assigned cases (source is not agent_created)",
               requests.get(f"{base}/reports/case/{cid}", headers=H(a1), timeout=30).json()["case"].get("source") != "agent_created"
               and requests.post(f"{base}/cases/{cid}/request-type", headers=H(a1), json={"request_type": "KYC Verification"}, timeout=30).status_code == 403)
        rep_id = sub.json()["id"] if sub.ok else None
        requests.post(f"{base}/reports/{rep_id}/review", headers=H(ssup), json={"action": "approve"}, timeout=30)
        wm = {sl: hashlib.sha256(requests.get(f"{base}/files/{e['id']}", headers=H(admin), timeout=60).content).hexdigest() for sl, e in stored.items()}

        docx = requests.get(f"{base}/exports/case/{cid}/docx", headers=H(ssup), timeout=180)
        z = zipfile.ZipFile(io.BytesIO(docx.content))
        media = {hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith("word/media/")}
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
        record("Word report embeds all 5 stored watermarked photos byte-for-byte", docx.ok and set(wm.values()) <= media, f"{len(media)} media files")
        # 14-Nov-2026: residence reports use the approved VEE red-only format; the Evidence Photo References table
        # (slot / file name / time / GPS) was removed on request. Time and GPS are on each photo's watermark.
        record("Word report: VEE format with the five category labels; no Evidence Photo References table",
               all(t in xml for t in ("Exterior – Front", "Exterior – Second Angle", "Interior", "Selfie", "Supporting Document",
                                      "RESIDENCE VERIFICATION PHOTO", 'w:val="FF0000"'))
               and "Evidence Photo References" not in xml and "Captured At" not in xml)
        pdfr = requests.get(f"{base}/exports/case/{cid}/pdf", headers=H(ssup), timeout=180)
        record("PDF report embeds the same 5 photos byte-for-byte (JPEG passthrough)", pdfr.ok and all(
            hashlib.sha256(m.group(1)).hexdigest() in wm.values() or True for m in []) and _pdf_images_match(pdfr.content, stored, base, H(admin), wm))
        from pdf_text import pdf_text
        ptxt = pdf_text(pdfr.content)
        record("PDF report: same layout as Word (5 labelled photos + header image, no reference table)",
               len(_pdf_image_payloads(pdfr.content)) == 6 and "Evidence Photo References" not in ptxt
               and all(t in ptxt for t in ("Exterior – Front", "Exterior – Second Angle", "Interior", "Selfie", "Supporting Document")))
        # aspect ratio preserved in PDF: image placement w/h ratio equals photo ratio
        record("photo aspect ratios preserved (no stretching)", _pdf_ratios_ok(pdfr.content))
        record("agent cannot export reports (supervisor/admin only)", requests.get(f"{base}/exports/case/{cid}/pdf", headers=H(a1), timeout=60).status_code == 403)
        record("supervisor outside scope cannot export another case", requests.get(f"{base}/exports/case/{cap['_id']}/pdf", headers=H(ssup), timeout=60).status_code == 403)

        # missing image handling: a case with only 3 of 5 photos + one stored photo made unreadable
        body2 = {**body, "client_case_id": f"MISS-{uuid.uuid4().hex[:4]}"}
        c2 = requests.post(f"{base}/cases", headers=H(ssup), json=body2, timeout=30).json()
        got = []
        for sl in slots[:3]:
            rr_ = requests.post(f"{base}/evidence/upload", headers=H(a1), timeout=180,
                                data={"case_id": c2["id"], "slot": sl, "kind": "photo", "captured_at": datetime.now(timezone.utc).isoformat(),
                                      "lat": str(PIN[0]), "lon": str(PIN[1]), "accuracy": "6", "gps_status": "ok"},
                                files={"file": ("p.jpg", jpeg("m" + sl + c2["id"]), "image/jpeg")})
            got.append(rr_.json())
        db.reports.insert_one({"case_id": c2["id"], "version": 1, "status": "draft", "report_type": "residence_applicant", "data": {}, "gps": {}})
        bogus = got[0]["storage_path"]
        db.evidence.update_one({"_id": __import__("bson").ObjectId(got[0]["id"])}, {"$set": {"storage_path": "checksphere/verify/evidence/missing/none.jpg"}})
        d2 = requests.get(f"{base}/exports/case/{c2['id']}/docx", headers=H(admin), timeout=180)
        x2 = zipfile.ZipFile(io.BytesIO(d2.content)).read("word/document.xml").decode("utf-8", "ignore")
        record("missing slots shown as 'Image unavailable' notices (Word)", d2.ok and x2.count("Image unavailable") == 3, f"{x2.count('Image unavailable')} notices")
        p2 = requests.get(f"{base}/exports/case/{c2['id']}/pdf", headers=H(admin), timeout=180)
        record("missing slots shown as 'Image unavailable' notices (PDF), only the 2 real photos embedded",
               p2.ok and pdf_text(p2.content).count("Image unavailable") == 3 and len(_pdf_image_payloads(p2.content)) == 3,
               f"{pdf_text(p2.content).count('Image unavailable')} notices, {len(_pdf_image_payloads(p2.content))} images")
        db.evidence.update_one({"_id": __import__("bson").ObjectId(got[0]["id"])}, {"$set": {"storage_path": bogus}})
    finally:
        try:
            left, paths = 0, []
            for e in db.evidence.find({"storage_provider": "r2"}):
                paths.append(e["storage_path"])
                if (e.get("original") or {}).get("storage_path"):
                    paths.append(e["original"]["storage_path"])
            for r_ in db.case_requests.find({}):
                paths += [d["path"] for d in r_.get("documents", []) if d.get("storage_provider") == "r2"]
            for u_ in db.case_uploads.find({}):
                paths.append(u_["pdf"]["storage_path"])
            for p in paths:
                try:
                    storage_service.delete_object(p, "r2")
                except Exception:
                    left += 1
            left += r2_test_utils.sweep()
            record("cleanup: all test files deleted from the R2 test bucket", left == 0, f"{len(paths)} assets")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
            log.close()
            for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "Traceback" in line or " ERROR " in line:
                    print("  server:", line[:220])
            log_path.unlink(missing_ok=True)
            mongo.drop_database(DB_NAME)
            print(f"dropped throwaway database {DB_NAME}")
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    print(f"\n{len(RESULTS) - len(fails)} passed/skipped, {len(fails)} failed")
    return 1 if fails else 0


def _pdf_streams(pdf: bytes):
    import base64
    import zlib
    for m in re.finditer(rb"<<(.*?)>>\s*stream\r?\n(.*?)endstream", pdf, re.S):
        yield m.group(1), m.group(2)


def _pdf_text(pdf: bytes) -> str:
    import base64
    import zlib
    out = b""
    for hdr, body in _pdf_streams(pdf):
        body = body.strip()
        try:
            if b"ASCII85Decode" in hdr:
                body = base64.a85decode(body[:-2] if body.endswith(b"~>") else body)
            if b"FlateDecode" in hdr:
                body = zlib.decompress(body)
        except Exception:
            continue
        if b"/Subtype /Image" not in hdr:
            out += body
    return out.decode("latin-1", "ignore")


def _pdf_image_payloads(pdf: bytes):
    import base64
    imgs = []
    for hdr, body in _pdf_streams(pdf):
        if b"/Subtype /Image" in hdr and b"DCTDecode" in hdr:
            body = body.strip()
            if b"ASCII85Decode" in hdr:
                body = base64.a85decode(body[:-2] if body.endswith(b"~>") else body)
            w = int(re.search(rb"/Width (\d+)", hdr).group(1))
            h = int(re.search(rb"/Height (\d+)", hdr).group(1))
            imgs.append((body, w, h))
    return imgs


def _pdf_images_match(pdf, stored, base, headers, wm) -> bool:
    found = {hashlib.sha256(b).hexdigest() for b, _, _ in _pdf_image_payloads(pdf)}
    return set(wm.values()) <= found


def _pdf_ratios_ok(pdf: bytes) -> bool:
    # each placed photo: "q <w> 0 0 <h> x y cm /FormXob.. Do" ; compare w/h with intrinsic Width/Height
    placements = [(float(a), float(b)) for a, b in re.findall(r"q\s+([\d.]+)\s+0\s+0\s+([\d.]+)\s+[\d.]+\s+[\d.]+\s+cm\s+/FormXob", _pdf_text(pdf))]
    intrinsic = sorted(round(w / h, 3) for _, w, h in _pdf_image_payloads(pdf) if w > 200)
    placed = sorted(round(a / b, 3) for a, b in placements if a > 100)
    return bool(placed) and all(any(abs(p - i) < 0.01 for i in intrinsic) for p in placed)


if __name__ == "__main__":
    sys.exit(main())
