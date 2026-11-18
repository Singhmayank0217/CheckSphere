"""Isolated verification of: AADITYA ENTERPRISE Word header, Super Admin-only soft delete, mandatory system Internal Case
ID / optional Client (External) Case ID, and Create New Verification creating the case only on final Submit.

SAFE BY CONSTRUCTION: own backend on a free port, throwaway LOCAL MongoDB (dropped at the end; never the MONGO_URL in
backend/.env), synthetic images only (the R2 test bucket under checksphere/verify/..., every asset deleted at the end).
Run from the repo root:  .venv\\Scripts\\python.exe backend\\tests\\verify_three_updates.py [--keep-docx DIR]
"""
import hashlib
import io
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from bson import ObjectId
from dotenv import dotenv_values
from PIL import Image, ImageDraw
from pymongo import MongoClient

import r2_test_utils

BACKEND = Path(__file__).resolve().parents[1]
LOCAL_MONGO = os.environ.get("VERIFY_LOCAL_MONGO", "mongodb://localhost:27017")
DB_NAME = f"checksphere_verify_{uuid.uuid4().hex[:8]}"
RESULTS = []
PIN = (19.0760, 72.8777)
EMU_PER_INCH = 914400


def record(name, ok, detail=""):
    status = "SKIP" if ok is None else ("PASS" if bool(ok) else "FAIL")
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name} {detail}", flush=True)


def jpeg(seed, w=1200, h=900):
    r = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    img = Image.new("RGB", (w, h), (r % 200, (r // 7) % 200, (r // 11) % 200))
    ImageDraw.Draw(img).rectangle([w // 4, h // 4, w // 2, h // 2], fill=(240, 240, 240))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def check_docx_header(content: bytes, label: str):
    """Structural checks of the Word header: supplied artwork embedded byte-for-byte, original proportions, fits the
    margins, used on every page (single default header, no different first page), and the body starts below it."""
    from docx import Document
    asset = (BACKEND / "assets" / "branding" / "aaditya_enterprise_header.jpg").read_bytes()
    with Image.open(io.BytesIO(asset)) as im:
        px_w, px_h = im.size
    z = zipfile.ZipFile(io.BytesIO(content))
    media = [n for n in z.namelist() if n.startswith("word/media/")]
    record(f"{label}: supplied header artwork embedded unchanged (byte-identical)", any(z.read(n) == asset for n in media))
    doc = Document(io.BytesIO(content))
    ok_all = True
    for sec in doc.sections:
        hdr = sec.header
        blips = hdr._element.xpath(".//wp:inline")
        if len(blips) != 1:
            ok_all = False
            continue
        ext = blips[0].xpath("./wp:extent")[0]
        cx, cy = int(ext.get("cx")), int(ext.get("cy"))
        avail = sec.page_width - sec.left_margin - sec.right_margin
        ratio_ok = abs((cx / cy) - (px_w / px_h)) < 0.01
        width_ok = abs(cx - avail) <= EMU_PER_INCH * 0.01
        clear_ok = sec.top_margin >= sec.header_distance + cy
        record(f"{label}: header keeps original proportions ({px_w}x{px_h})", ratio_ok, f"{cx / EMU_PER_INCH:.2f}in x {cy / EMU_PER_INCH:.2f}in")
        record(f"{label}: header fits exactly within the page margins", width_ok and cx <= avail)
        record(f"{label}: body starts below the header (title not covered)", clear_ok,
               f"top margin {sec.top_margin / EMU_PER_INCH:.2f}in >= {(sec.header_distance + cy) / EMU_PER_INCH:.2f}in")
        record(f"{label}: header used on every page (not linked/first-page-only)",
               not sec.different_first_page_header_footer and not hdr.is_linked_to_previous)
    record(f"{label}: header present in every section", ok_all and len(doc.sections) >= 1)
    body_first = doc.paragraphs[0].text if doc.paragraphs else ""
    record(f"{label}: report title is the first body content (header is not in the body)", "AADITYA" not in body_first.upper()
           and bool(body_first.strip()))


def main() -> int:
    keep_dir = None
    if "--keep-docx" in sys.argv:
        keep_dir = Path(sys.argv[sys.argv.index("--keep-docx") + 1])
        keep_dir.mkdir(parents=True, exist_ok=True)
    file_env = dotenv_values(BACKEND / ".env")
    cloud_ok = "test" in (file_env.get("R2_BUCKET") or "")
    if not cloud_ok:
        print("R2 test bucket (R2_BUCKET=checksphere-test) not configured in backend/.env")
        return 2
    mongo = MongoClient(LOCAL_MONGO, serverSelectionTimeoutMS=3000)
    mongo.server_info()
    assert DB_NAME not in mongo.list_database_names()
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
    os.environ.setdefault("MONGO_URL", LOCAL_MONGO)
    os.environ.setdefault("DB_NAME", DB_NAME)
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

        admin, adminu = login("admin@checksphere.app", "Admin@12345")
        a1, a1u = login("AGT101", "Agent@12345", "Verify@Agent1x")
        a2, a2u = login("AGT102", "Agent@12345", "Verify@Agent2x")
        sup, supu = login("sup1@checksphere.app", "Super@12345", "Verify@Sup1xx")
        clients = requests.get(f"{base}/clients", headers=H(admin), timeout=30).json()["items"]
        c_in = clients[0]

        def live_total(token=admin):
            return requests.get(f"{base}/cases", headers=H(token), params={"limit": 1}, timeout=30).json()["total"]

        def dash_total():
            return requests.get(f"{base}/dashboard/stats", headers=H(admin), timeout=60).json()["total"]

        # ================================================== 3. Internal Case ID mandatory / External ID optional
        base_body = {"client_id": c_in["id"], "applicant_name": "IdTest Applicant", "report_type": "residence_applicant",
                     "assigned_address": "1 Id Road, Mumbai", "primary_phone": "9000000101", "state": "Maharashtra",
                     "assigned_lat": PIN[0], "assigned_lon": PIN[1]}
        r1 = requests.post(f"{base}/cases", headers=H(admin), json=base_body, timeout=30)
        r2 = requests.post(f"{base}/cases", headers=H(admin), json={**base_body, "client_case_id": "   "}, timeout=30)
        r3 = requests.post(f"{base}/cases", headers=H(admin), json={**base_body, "client_case_id": "BANK-REF-7781"}, timeout=30)
        r4 = requests.post(f"{base}/cases", headers=H(sup), json={**base_body, "agent_id": a1u["id"]}, timeout=30)
        made = [x.json() for x in (r1, r2, r3, r4) if x.ok]
        record("Super Admin creates a case WITHOUT a Client/External Case ID", r1.ok and r1.json().get("client_case_id") is None, r1.text[:120] if not r1.ok else "")
        record("blank (spaces) External ID is accepted and stored as empty", r2.ok and r2.json().get("client_case_id") is None)
        record("supplied External ID is preserved exactly", r3.ok and r3.json().get("client_case_id") == "BANK-REF-7781")
        record("Supervisor creates + assigns a case WITHOUT an External ID", r4.ok and r4.json().get("client_case_id") is None, r4.text[:120] if not r4.ok else "")
        ids = [m["internal_case_id"] for m in made]
        record("every new case gets a system Internal Case ID (CSV-######)", len(ids) == 4 and all(re.fullmatch(r"CSV-\d{6}", i) for i in ids), ", ".join(ids))
        record("Internal Case IDs are unique", len(set(ids)) == len(ids) and
               not list(db.cases.aggregate([{"$group": {"_id": "$internal_case_id", "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}}])))
        record("External ID never replaces the Internal ID", made[2]["internal_case_id"] != "BANK-REF-7781" if len(made) > 2 else False)
        srch = requests.get(f"{base}/cases", headers=H(admin), params={"q": "BANK-REF-7781"}, timeout=30).json()["items"]
        record("search by External ID finds the case; Internal ID shown", len(srch) == 1 and srch[0]["internal_case_id"] == made[2]["internal_case_id"])
        record("search by Internal ID works", requests.get(f"{base}/cases", headers=H(admin), params={"internal_case_id": ids[0]}, timeout=30).json()["total"] == 1)

        # Excel import: one row without External ID, one with
        from openpyxl import Workbook, load_workbook
        tpl = requests.get(f"{base}/cases/import-template", headers=H(admin), timeout=30)
        hdrs = [c.value for c in load_workbook(io.BytesIO(tpl.content)).active[1]]
        wb = Workbook(); ws = wb.active; ws.append(hdrs)
        rt_name = next(t["name"] for t in requests.get(f"{base}/report-types", headers=H(admin), timeout=30).json()["items"] if t["key"] == "residence_applicant")

        def row(ext, applicant):
            vals = {"Client Case ID": ext, "Client Name": c_in["name"], "Applicant Name": applicant, "Primary Contact Number": "9000000102",
                    "Report Type": rt_name, "Assigned Address": "2 Import Road", "City": "Mumbai", "State": "Maharashtra", "Priority": "Medium"}
            return [vals.get(h, "") for h in hdrs]
        ws.append(row("", "Import NoExt")); ws.append(row("IMP-CLIENT-55", "Import WithExt"))
        buf = io.BytesIO(); wb.save(buf)
        imp = requests.post(f"{base}/cases/import", headers=H(admin), files={"file": ("cases.xlsx", buf.getvalue(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}, timeout=60)
        noext = db.cases.find_one({"applicant_name": "Import NoExt"})
        withext = db.cases.find_one({"applicant_name": "Import WithExt"})
        record("import: row without External ID is created (not rejected)", imp.ok and imp.json()["created"] == 2 and noext and noext.get("client_case_id") is None,
               str(imp.json()) if imp.ok else imp.text[:120])
        record("import: supplied External ID preserved; Internal IDs generated", bool(withext) and withext["client_case_id"] == "IMP-CLIENT-55"
               and re.fullmatch(r"CSV-\d{6}", withext["internal_case_id"] or "") and noext["internal_case_id"] != withext["internal_case_id"])

        # ================================================== 4. Create New Verification: case only on final Submit
        import requests_routes as rr  # noqa: E402
        cases_before = db.cases.count_documents({})
        live_before, dash_before = live_total(), dash_total()
        sup_before = live_total(sup)
        a1_before = requests.get(f"{base}/cases", headers=H(a1), params={"limit": 100}, timeout=30).json()["total"]
        key = uuid.uuid4().hex
        d1 = requests.post(f"{base}/cases/agent-create", headers=H(a1), json={"request_type": "Residence Verification", "draft_key": key}, timeout=30)
        d1b = requests.post(f"{base}/cases/agent-create", headers=H(a1), json={"request_type": "Residence Verification", "draft_key": key}, timeout=30)
        draft = d1.json() if d1.ok else {}
        record("selecting a Request Type opens a draft form, NOT a case (no Internal Case ID)", d1.ok and draft.get("is_draft") is True
               and not re.fullmatch(r"CSV-\d+", draft.get("internal_case_id") or ""))
        record("double tap on Continue reuses the same draft", d1b.ok and d1b.json()["id"] == draft.get("id") and db.cases.count_documents({"is_draft": True}) == 1)
        ch = requests.post(f"{base}/cases/{draft['id']}/request-type", headers=H(a1), json={"request_type": "Office Verification"}, timeout=30)
        ch2 = requests.post(f"{base}/cases/agent-create", headers=H(a1), json={"request_type": "KYC Verification", "draft_key": key}, timeout=30)
        record("changing the Request Type updates the draft only", ch.ok and ch2.ok and ch2.json()["id"] == draft["id"]
               and ch2.json()["report_type"] == rr.REQ_TYPES["KYC Verification"])
        requests.post(f"{base}/cases/{draft['id']}/request-type", headers=H(a1), json={"request_type": "Residence Verification"}, timeout=30).raise_for_status()
        record("no case created by selecting/changing type: admin & supervisor lists unchanged", live_total() == live_before and live_total(sup) == sup_before)
        record("no case in dashboard totals", dash_total() == dash_before)
        record("draft not in the agent's case list", requests.get(f"{base}/cases", headers=H(a1), params={"limit": 100}, timeout=30).json()["total"] == a1_before)
        xl = requests.get(f"{base}/exports/cases.xlsx", headers=H(admin), timeout=60)
        xl_ids = [r_[0] for r_ in load_workbook(io.BytesIO(xl.content)).active.iter_rows(min_row=2, values_only=True)]
        record("draft not in Excel export", xl.ok and not any(str(i or "").startswith("DRAFT-") for i in xl_ids))
        record("Super Admin / Supervisor cannot open someone's draft (403)",
               requests.get(f"{base}/cases/{draft['id']}", headers=H(admin), timeout=30).status_code == 403
               and requests.get(f"{base}/cases/{draft['id']}", headers=H(sup), timeout=30).status_code == 403
               and requests.get(f"{base}/cases/{draft['id']}", headers=H(a2), timeout=30).status_code == 403)
        dl = requests.get(f"{base}/agent/verification-drafts", headers=H(a1), timeout=30).json()["items"]
        record("agent can see and resume their unfinished draft", any(x["id"] == draft["id"] for x in dl)
               and not requests.get(f"{base}/agent/verification-drafts", headers=H(a2), timeout=30).json()["items"])
        ctx = requests.get(f"{base}/reports/case/{draft['id']}", headers=H(a1), timeout=30).json()
        record("the full assigned-case verification form is served for the draft", ctx.get("can_edit") is True and len(ctx["config"]["photo_slots"]) == 5
               and len(ctx["config"]["sections"]) >= 3)
        no_supervisor_notes = db.notifications.count_documents({"case_id": draft["id"]}) == 0
        record("no supervisor notification before submit", no_supervisor_notes)

        cfg = ctx["config"]
        vdata = {}
        for sec in cfg["sections"]:
            for f in sec["fields"]:
                vdata[f["key"]] = f["options"][0] if f.get("type") in ("select", "multiselect") else ("2" if f.get("type") == "number" else ("1990-05-17" if f.get("type") == "date" else "Observed value for test"))
        vdata.update({"applicant_name": "Draft Flow Applicant", "client_name": c_in["name"], "branch_name": "Andheri",
                      "assigned_address": "9 Draft Road, Mumbai", "client_case_id": "", "residence_status": "Parental", "internal_case_id": ""})
        sv = requests.put(f"{base}/reports/case/{draft['id']}/draft", headers=H(a1), json={"data": vdata, "declaration": True}, timeout=60)
        record("saving the draft form still creates no case", sv.ok and live_total() == live_before and db.cases.count_documents({}) == cases_before + 1)
        ups = []
        for sl in ["exterior", "exterior_2", "interior", "selfie", "document"]:
            ups.append(requests.post(f"{base}/evidence/upload", headers=H(a1), timeout=180,
                                     data={"case_id": draft["id"], "slot": sl, "kind": "photo", "captured_at": datetime.now(timezone.utc).isoformat(),
                                           "lat": str(PIN[0]), "lon": str(PIN[1]), "accuracy": "6", "gps_status": "ok"},
                                     files={"file": ("p.jpg", jpeg("draft" + sl + draft["id"]), "image/jpeg")}))
        record("five GPS photos uploaded (watermarked, R2) on the draft", all(u_.ok and u_.json().get("watermark") for u_ in ups),
               "; ".join(u_.text[:80] for u_ in ups if not u_.ok))
        record("photos still create no case", live_total() == live_before)

        # final Submit, sent twice concurrently (double tap / network retry)
        outs = []

        def submit():
            outs.append(requests.post(f"{base}/reports/case/{draft['id']}/submit", headers=H(a1), json={"data": vdata, "declaration": True}, timeout=120))
        th = [threading.Thread(target=submit) for _ in range(2)]
        [t.start() for t in th]
        [t.join() for t in th]
        codes = sorted(o.status_code for o in outs)
        okr = next((o.json() for o in outs if o.ok), {})
        record("repeated Submit: exactly one succeeds, the other gets 409", codes == [200, 409], str(codes) + " " + "; ".join(o.text[:100] for o in outs if o.status_code not in (200, 409)))
        cdoc = db.cases.find_one({"_id": ObjectId(draft["id"])})
        record("final Submit creates the case with a new unique Internal Case ID", okr.get("case_created") is True and cdoc and not cdoc.get("is_draft")
               and re.fullmatch(r"CSV-\d{6}", cdoc["internal_case_id"]) and okr.get("internal_case_id") == cdoc["internal_case_id"]
               and db.cases.count_documents({"internal_case_id": cdoc["internal_case_id"]}) == 1, (cdoc or {}).get("internal_case_id", ""))
        record("only ONE case and ONE submitted report exist (no duplicates)", live_total() == live_before + 1 and db.cases.count_documents({}) == cases_before + 1
               and db.reports.count_documents({"case_id": draft["id"], "status": "submitted"}) == 1)
        rep = db.reports.find_one({"case_id": draft["id"], "status": "submitted"})
        record("submitted report carries the system Internal Case ID; blank External ID accepted",
               rep and rep["data"].get("internal_case_id") == cdoc["internal_case_id"] and cdoc.get("client_case_id") in (None, ""))
        record("submitted case visible to agent, supervisor and admin lists", live_total(sup) == sup_before + 1
               and any(x["id"] == draft["id"] for x in requests.get(f"{base}/cases", headers=H(a1), params={"limit": 100}, timeout=30).json()["items"]))
        record("supervisors notified only after submit", db.notifications.count_documents({"case_id": draft["id"]}) >= 1)
        record("audit trail: draft started + case created on final submit",
               db.audit_logs.count_documents({"entity_id": draft["id"], "action": "agent_verification_draft_started"}) == 1
               and db.audit_logs.count_documents({"entity_id": draft["id"], "action": "case_created_by_agent"}) == 1)

        # agent supplied External ID is preserved on an agent submission
        k2 = uuid.uuid4().hex
        dr2 = requests.post(f"{base}/cases/agent-create", headers=H(a1), json={"request_type": "Telephone Verification", "draft_key": k2}, timeout=30).json()
        record("a new visit opens a NEW draft (submitted one is not reused)", dr2["id"] != draft["id"] and dr2.get("is_draft"))
        requests.post(f"{base}/cases/{dr2['id']}/discard", headers=H(a1), timeout=30).raise_for_status()
        record("agent can discard an unfinished draft; still no case", live_total() == live_before + 1
               and not requests.get(f"{base}/agent/verification-drafts", headers=H(a1), timeout=30).json()["items"])

        # Allocate New Verification still works (request -> supervisor approval -> case)
        rq = {"request_type": "Office Verification", "applicant_name": "Alloc Applicant", "co_applicant_name": "", "seller_name": "", "primary_phone": "9000000103",
              "alt_phone": "", "client_name": c_in["name"], "branch_name": "Some Branch", "bank_state": "Maharashtra", "full_address": "12 Alloc Road, Mumbai",
              "pincode": "400001", "verification_state": "Maharashtra", "city": "Mumbai", "notes": "test", "priority": "Normal", "supervisor_id": supu["id"]}
        rid = requests.post(f"{base}/requests", headers=H(a2), json={"data": rq, "declaration": True}, timeout=30).json()["id"]
        pdf_buf = io.BytesIO(); Image.new("RGB", (100, 100), (255, 255, 255)).save(pdf_buf, "PDF")
        requests.post(f"{base}/requests/{rid}/document", headers=H(a2), files={"file": ("doc.pdf", pdf_buf.getvalue(), "application/pdf")}, timeout=120).raise_for_status()
        s1 = requests.post(f"{base}/requests/{rid}/submit", headers=H(a2), json={"data": rq, "declaration": True}, timeout=30)
        n_before = db.cases.count_documents({})
        record("Allocate New Verification: submitting the request creates no case", s1.ok and db.cases.count_documents({}) == n_before)
        ap = requests.post(f"{base}/requests/{rid}/action", headers=H(sup), json={"action": "approve", "agent_id": a2u["id"], "comment": ""}, timeout=30)
        cap = db.cases.find_one({"source_request_id": rid})
        record("Allocate flow intact: approval creates the case with a system Internal ID (no invented External ID)",
               ap.ok and cap and re.fullmatch(r"CSV-\d{6}", cap["internal_case_id"]) and cap.get("client_case_id") is None
               and cap["assigned_agent_id"] == a2u["id"], ap.text[:120] if not ap.ok else "")

        # ================================================== 1. Word header (real export through the API + multi-page)
        dx = requests.get(f"{base}/exports/case/{draft['id']}/docx", headers=H(admin), timeout=180)
        record("Word export of the new case succeeds", dx.ok and dx.content[:2] == b"PK", dx.text[:120] if not dx.ok else "")
        if dx.ok:
            check_docx_header(dx.content, "API Word export")
            xml = zipfile.ZipFile(io.BytesIO(dx.content)).read("word/document.xml").decode("utf-8", "ignore")
            props = zipfile.ZipFile(io.BytesIO(dx.content)).read("docProps/core.xml").decode("utf-8", "ignore")
            # VEE red-only format: the Internal Case ID is not printed on the page (it is not VEE content); it is in the
            # document properties and the file name. The External ID is simply absent when not provided.
            record("Word report carries the Internal ID (file properties + file name)", cdoc["internal_case_id"] in props
                   and cdoc["internal_case_id"] in dx.headers.get("Content-Disposition", ""))
            embedded = sum(1 for n in zipfile.ZipFile(io.BytesIO(dx.content)).namelist() if n.startswith("word/media/"))
            record("evidence photos still embedded alongside the header", embedded >= 6, f"{embedded} media files")
            if keep_dir:
                (keep_dir / "api_export.docx").write_bytes(dx.content)
        px = requests.get(f"{base}/exports/case/{draft['id']}/pdf", headers=H(admin), timeout=180)
        record("PDF export still works (header unchanged)", px.ok and px.content[:4] == b"%PDF")

        # ================================================== 2. Super Admin-only soft delete
        victim = made[0]
        vid = victim["id"]
        before_live, before_dash = live_total(), dash_total()
        record("Agent cannot delete via API (POST 403)", requests.post(f"{base}/cases/{vid}/delete", headers=H(a1), json={"reason": "agent try"}, timeout=30).status_code == 403)
        record("Agent cannot delete via API (DELETE 403)", requests.delete(f"{base}/cases/{vid}", headers=H(a1), params={"reason": "agent try"}, timeout=30).status_code == 403)
        record("Supervisor cannot delete via API (POST 403)", requests.post(f"{base}/cases/{vid}/delete", headers=H(sup), json={"reason": "sup try"}, timeout=30).status_code == 403)
        record("Supervisor cannot delete via API (DELETE 403)", requests.delete(f"{base}/cases/{vid}", headers=H(sup), params={"reason": "sup try"}, timeout=30).status_code == 403)
        record("no token cannot delete (401)", requests.post(f"{base}/cases/{vid}/delete", json={"reason": "x y z"}, timeout=30).status_code == 401)
        record("Agent/Supervisor cannot list or restore deleted cases (403)",
               requests.get(f"{base}/cases-deleted", headers=H(a1), timeout=30).status_code == 403
               and requests.get(f"{base}/cases-deleted", headers=H(sup), timeout=30).status_code == 403
               and requests.post(f"{base}/cases/{vid}/restore", headers=H(sup), json={"reason": "sup try"}, timeout=30).status_code == 403)
        record("case untouched after refused attempts", db.cases.find_one({"_id": ObjectId(vid)}).get("deleted_at") is None)
        record("delete without a reason is refused", requests.post(f"{base}/cases/{vid}/delete", headers=H(admin), json={}, timeout=30).status_code == 422
               and requests.delete(f"{base}/cases/{vid}", headers=H(admin), timeout=30).status_code == 400)
        dr = requests.post(f"{base}/cases/{vid}/delete", headers=H(admin), json={"reason": "Created by mistake (test)"}, timeout=30)
        record("Super Admin deletes a case", dr.ok and dr.json().get("internal_case_id") == victim["internal_case_id"])
        record("deleted case gone from case list + search", live_total() == before_live - 1
               and not requests.get(f"{base}/cases", headers=H(admin), params={"q": victim["internal_case_id"]}, timeout=30).json()["items"]
               and not requests.get(f"{base}/cases", headers=H(admin), params={"internal_case_id": victim["internal_case_id"]}, timeout=30).json()["items"])
        record("deleted case gone from dashboard", dash_total() == before_dash - 1)
        xl = requests.get(f"{base}/exports/cases.xlsx", headers=H(admin), timeout=60)
        record("deleted case gone from Excel export", xl.ok and victim["internal_case_id"] not in
               [r_[0] for r_ in load_workbook(io.BytesIO(xl.content)).active.iter_rows(min_row=2, values_only=True)])
        record("deleted case cannot be opened / exported / reported (404)",
               requests.get(f"{base}/cases/{vid}", headers=H(admin), timeout=30).status_code == 404
               and requests.get(f"{base}/exports/case/{vid}/docx", headers=H(admin), timeout=30).status_code == 404
               and requests.get(f"{base}/reports/case/{vid}", headers=H(admin), timeout=30).status_code == 404)
        # delete the submitted case too: its report must vanish from review and its evidence stays stored
        ev_before = list(db.evidence.find({"case_id": draft["id"]}))
        rep_id = str(rep["_id"])
        record("Supervisor can open the report before deletion", requests.get(f"{base}/reports/{rep_id}", headers=H(sup), timeout=30).ok)
        requests.post(f"{base}/cases/{draft['id']}/delete", headers=H(admin), json={"reason": "Test cleanup of submitted case"}, timeout=30).raise_for_status()
        record("deleted case's report hidden from review (404) and review actions refused",
               requests.get(f"{base}/reports/{rep_id}", headers=H(sup), timeout=30).status_code == 404
               and requests.post(f"{base}/reports/{rep_id}/review", headers=H(sup), json={"action": "approve"}, timeout=30).status_code == 404)
        record("deleted case not in the agent's list", not any(x["id"] == draft["id"] for x in requests.get(f"{base}/cases", headers=H(a1), params={"limit": 100}, timeout=30).json()["items"]))
        ev_after = list(db.evidence.find({"case_id": draft["id"]}))
        record("evidence records & stored files are NOT removed by deletion", len(ev_after) == len(ev_before) == 5
               and all(e["storage_path"] for e in ev_after))
        f_id = str(ev_after[0]["_id"])
        record("evidence of a deleted case: Super Admin can still retrieve (audit); Agent/Supervisor cannot",
               requests.get(f"{base}/files/{f_id}", headers=H(admin), timeout=60).ok
               and requests.get(f"{base}/files/{f_id}", headers=H(sup), timeout=30).status_code == 404
               and requests.get(f"{base}/files/{f_id}", headers=H(a1), timeout=30).status_code == 404)
        a = db.audit_logs.find_one({"action": "case_deleted", "entity_id": vid})
        record("audit log: deleting Super Admin's user ID, date/time and reason recorded",
               a and a["user_id"] == adminu["id"] and a["user_role"] == "super_admin" and a["details"]["reason"] == "Created by mistake (test)"
               and a.get("created_at") and a["details"]["internal_case_id"] == victim["internal_case_id"] and a["details"]["applicant_name"] == victim["applicant_name"])
        rec = db.cases.find_one({"_id": ObjectId(vid)})
        record("record kept (soft delete) with deleted_by / reason / timeline entry", rec and rec["deleted_at"] and rec["deleted_by"] == adminu["id"]
               and rec["deleted_reason"] == "Created by mistake (test)" and rec["timeline"][-1]["action"] == "case_deleted")
        dl = requests.get(f"{base}/cases-deleted", headers=H(admin), timeout=30).json()
        record("Super Admin sees deleted cases list (auditable)", any(x["id"] == vid and x["deleted_reason"] for x in dl["items"]))
        record("deleting again is refused (404)", requests.post(f"{base}/cases/{vid}/delete", headers=H(admin), json={"reason": "again"}, timeout=30).status_code == 404)
        rs = requests.post(f"{base}/cases/{vid}/restore", headers=H(admin), json={"reason": "Restore test"}, timeout=30)
        record("Super Admin can restore (recoverable) and it returns to lists", rs.ok and any(
            x["id"] == vid for x in requests.get(f"{base}/cases", headers=H(admin), params={"limit": 100}, timeout=30).json()["items"]))
        record("restore recorded in the audit log", db.audit_logs.count_documents({"action": "case_restored", "entity_id": vid, "user_id": adminu["id"]}) == 1)

        # ================================================== 1b. multi-page Word report built in-process (long report)
        from exporters import build_case_docx  # noqa: E402
        from report_config import config_for  # noqa: E402
        cfg_res = config_for("residence_applicant", {})
        long_data = {f["key"]: ("Long observation text. " * 30) for sec in cfg_res["sections"] for f in sec["fields"]}
        ev = [{"id": f"e{i}", "kind": "photo", "slot": sl, "filename": f"{sl}.jpg", "captured_at": datetime.now(timezone.utc),
               "gps": {"lat": PIN[0], "lon": PIN[1], "accuracy": 5}} for i, sl in enumerate(["exterior", "exterior_2", "interior", "selfie", "document"])]
        imgs = {e["id"]: jpeg(e["id"]) for e in ev}
        case_doc = {"_id": "x", "internal_case_id": "CSV-999999", "client_case_id": None, "client_name": "Test Client", "applicant_name": "Multi Page",
                    "report_type": "residence_applicant", "source": "agent_created"}
        rep_doc = {"version": 1, "data": long_data, "gps": {"lat": PIN[0], "lon": PIN[1], "accuracy": 5}, "declaration": True}
        long_docx = build_case_docx(case_doc, rep_doc, ev, cfg_res, {"company_name": "CheckSphere"}, "https://example.invalid/r/x", imgs)
        check_docx_header(long_docx, "multi-page Word report")
        if keep_dir:
            (keep_dir / "multipage.docx").write_bytes(long_docx)
    finally:
        try:
            left, paths = 0, []
            for e in db.evidence.find({"storage_provider": "r2"}):
                paths.append(e["storage_path"])
                if (e.get("original") or {}).get("storage_path"):
                    paths.append(e["original"]["storage_path"])
            for r_ in db.case_requests.find({}):
                paths += [d["path"] for d in r_.get("documents", []) if d.get("storage_provider") == "r2"]
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


if __name__ == "__main__":
    sys.exit(main())
