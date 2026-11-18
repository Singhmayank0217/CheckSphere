"""Isolated verification of GPS / distance / capture-time / five-photo / address-lock / Residence Status changes.

SAFE BY CONSTRUCTION (same approach as verify_independence.py):
  * Own backend on a free port against a throwaway LOCAL MongoDB database (dropped at the end).
  * Only synthetic generated images go to the R2 test bucket under checksphere/verify/...; every one is deleted.
  * Geocoding is switched off for the server under test; one direct lookup of a public landmark checks the geocoder.

Run from the repo root:  .venv\\Scripts\\python.exe backend\\tests\\verify_field_capture.py
"""
import concurrent.futures as cf
import io
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bson import ObjectId
from dotenv import dotenv_values
from PIL import Image
from pymongo import MongoClient

import r2_test_utils

BACKEND = Path(__file__).resolve().parents[1]
LOCAL_MONGO = os.environ.get("VERIFY_LOCAL_MONGO", "mongodb://localhost:27017")
DB_NAME = f"checksphere_verify_{uuid.uuid4().hex[:8]}"
RESULTS = []
REF = (19.0760, 72.8777)  # reference pin used for the test case (public coordinates, Mumbai)


def record(name, ok, detail=""):
    status = "SKIP" if ok is None else ("PASS" if bool(ok) else "FAIL")
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name} {detail}", flush=True)


def jpeg(seed: str) -> bytes:
    h = abs(hash(seed))
    img = Image.new("RGB", (48, 48), (h % 255, (h // 7) % 255, (h // 13) % 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def main() -> int:
    file_env = dotenv_values(BACKEND / ".env")
    if "test" not in (file_env.get("R2_BUCKET") or ""):
        print("R2 test bucket (R2_BUCKET=checksphere-test) not configured in backend/.env")
        return 2
    mongo = MongoClient(LOCAL_MONGO, serverSelectionTimeoutMS=3000)
    db = mongo[DB_NAME]
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, **{k: v for k, v in file_env.items() if v is not None},
           "MONGO_URL": LOCAL_MONGO, "DB_NAME": DB_NAME, "SEED_DEMO_DATA": "true", "MEDIA_FOLDER_ENV": "verify",
           "GEOCODING_PROVIDER": "off", "BACKUP_DIR": str(Path(os.environ.get("TEMP", BACKEND)) / DB_NAME)}
    log_path = Path(os.environ.get("TEMP", BACKEND)) / f"{DB_NAME}-server.log"
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--port", str(port)], cwd=BACKEND, env=env,
                            stdout=log, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}/api"
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
        a2, _ = login("AGT102", "Agent@12345", "Verify@Agent2x")
        sup, _ = login("sup1@checksphere.app", "Super@12345", "Verify@Sup1xx")
        settings = requests.get(f"{base}/settings", headers=H(admin), timeout=30).json()
        allowed = float(settings["flag_distance_m"])

        # ---- config: five mandatory photos for field visits, Parental option
        rt = requests.get(f"{base}/report-types", headers=H(admin), timeout=30).json()["configs"]
        for t in ("residence_applicant", "residence_coapplicant", "business_applicant", "office_coapplicant", "seller"):
            slots = rt[t]["photo_slots"]
            record(f"{t}: 5 mandatory photo slots", len(slots) == 5 and all(x["required"] for x in slots),
                   ",".join(x["key"] for x in slots))
        sel = next(x for x in rt["residence_applicant"]["photo_slots"] if x["key"] == "selfie")
        record("selfie slot opens front camera", sel.get("camera") == "front")
        record("5th slot labelled 'Supporting Document'", rt["residence_applicant"]["photo_slots"][4]["label"] == "Supporting Document")
        rs = next(f for sec in rt["residence_applicant"]["sections"] for f in sec["fields"] if f["key"] == "residence_status")
        record("Residence Status shows Parental, not Other", "Parental" in rs["options"] and "Other" not in rs["options"], str(rs["options"]))
        ro = {f["key"] for sec in rt["residence_applicant"]["sections"] for f in sec["fields"] if f.get("readonly")}
        record("assigned address + visit date/time are read-only fields", {"assigned_address", "visit_datetime"} <= ro)
        record("telephone/document types unchanged (1 document slot)", len(rt["tel_residence"]["photo_slots"]) == 1 and len(rt["kyc"]["photo_slots"]) == 1)

        # ---- a fresh residence case for agent 1 with a pinned reference location
        clients = requests.get(f"{base}/clients", headers=H(admin), timeout=30).json()["items"]
        cr = requests.post(f"{base}/cases", headers=H(admin), json={
            "client_case_id": f"VERIFY-{uuid.uuid4().hex[:6]}", "client_id": clients[0]["id"], "applicant_name": "Test Applicant",
            "report_type": "residence_applicant", "assigned_address": "Test address line, Test City", "primary_phone": "9000000000",
            "assigned_lat": REF[0], "assigned_lon": REF[1]}, timeout=30)
        cr.raise_for_status()
        case = cr.json()
        cid = case["id"]
        record("new case with pin -> location_source manual/pinned", case.get("location_status") == "pinned")
        requests.post(f"{base}/cases/{cid}/assign", headers=H(admin), json={"agent_id": a1u["id"]}, timeout=30).raise_for_status()
        cr2 = requests.post(f"{base}/cases", headers=H(admin), json={
            "client_case_id": f"VERIFY-{uuid.uuid4().hex[:6]}", "client_id": clients[0]["id"], "applicant_name": "No Pin",
            "report_type": "residence_applicant", "assigned_address": "Somewhere", "primary_phone": "9000000001"}, timeout=30).json()
        record("new case without pin (geocoding off) -> location_status missing", cr2.get("location_status") == "missing")

        def up(slot, lat=None, lon=None, acc=10.0, captured=None, extra=None, token=a1, case_id=cid, seed=None):
            data = {"case_id": case_id, "slot": slot, "kind": "photo"}
            if lat is not None:
                data.update({"lat": str(lat), "lon": str(lon), "accuracy": str(acc), "gps_status": "ok"})
            if captured is not None:
                data["captured_at"] = captured
            data.update(extra or {})
            return requests.post(f"{base}/evidence/upload", headers=H(token), data=data,
                                 files={"file": ("p.jpg", jpeg(seed or uuid.uuid4().hex), "image/jpeg")}, timeout=120)

        # ---- distance math (haversine): ~0.001 deg latitude = ~111 m
        sys.path.insert(0, str(BACKEND))
        os.environ.setdefault("JWT_SECRET", "x" * 40)
        os.environ.setdefault("MONGO_URL", LOCAL_MONGO); os.environ.setdefault("DB_NAME", DB_NAME)
        import core  # noqa: E402
        d = core.haversine_m(REF[0], REF[1], REF[0] + 0.001, REF[1])
        record("distance formula: 0.001 deg latitude ~ 111 m", 110 < d < 113, f"{d:.1f} m")

        # ---- GPS: within distance
        shot = datetime.now(timezone.utc) - timedelta(minutes=10)
        r = up("exterior", REF[0] + 0.001, REF[1], captured=iso(shot))
        e1 = r.json() if r.ok else {}
        record("within allowed distance -> accepted", r.status_code == 200 and e1.get("distance_m", 9e9) < allowed,
               f"{e1.get('distance_m')} m (allowed {allowed:.0f})")
        record("GPS status ok + accuracy stored", (e1.get("gps") or {}).get("status") == "ok" and e1["gps"]["accuracy"] == 10.0)
        cap = datetime.fromisoformat(e1["captured_at"])
        rec = datetime.fromisoformat(e1["received_at"])
        record("capture time = device shutter time (not upload time)", abs((cap - shot).total_seconds()) < 1 and e1["captured_at_source"] == "device")
        record("server receipt time recorded separately", (rec - cap).total_seconds() > 500, f"skew {e1['clock_skew_s']} s")

        # ---- GPS: outside distance
        far = (REF[0] + 0.05, REF[1])  # ~5.5 km
        r = up("exterior_2", *far, captured=iso(datetime.now(timezone.utc)))
        det = (r.json().get("detail") or {}) if r.status_code == 422 else {}
        record("outside distance without reason -> 422 with actual + allowed distance",
               det.get("code") == "outside_allowed_distance" and det.get("distance_m", 0) > 5000 and det.get("allowed_m") == allowed,
               f"{det.get('distance_m')} m vs {det.get('allowed_m')} m")
        r = up("exterior_2", *far, captured=iso(datetime.now(timezone.utc)), extra={"location_reason": "Applicant moved; met at new address"})
        e2 = r.json() if r.ok else {}
        record("outside distance with reason -> accepted + flagged", r.ok and "photo_far_from_assigned" in e2.get("flags", []) and e2.get("location_reason"))

        # ---- GPS: no fix / poor accuracy / mock
        r = up("interior", extra={"gps_status": "timeout", "captured_at": iso(datetime.now(timezone.utc))})
        det = (r.json().get("detail") or {}) if r.status_code == 422 else {}
        record("no GPS (timeout) without reason -> 422 gps_reason_required", det.get("code") == "gps_reason_required" and det.get("gps_status") == "timeout")
        r = up("interior", extra={"gps_status": "timeout", "location_reason": "Basement, no signal", "captured_at": iso(datetime.now(timezone.utc))})
        e3 = r.json() if r.ok else {}
        record("no GPS with reason -> accepted, status 'timeout', flagged", r.ok and e3["gps"]["status"] == "timeout" and "photo_without_gps" in e3["flags"])
        r = up("selfie", REF[0], REF[1], acc=400, captured=iso(datetime.now(timezone.utc)), extra={"mocked": "true"})
        e4 = r.json() if r.ok else {}
        record("poor accuracy -> status poor_accuracy + flag", r.ok and e4["gps"]["status"] == "poor_accuracy" and "low_gps_accuracy" in e4["flags"])
        record("mock location reported -> flagged possible_mock_location", r.ok and e4["gps"]["mocked"] is True and "possible_mock_location" in e4["flags"])

        # ---- capture time integrity
        r = up("document", REF[0], REF[1], captured=iso(datetime.now(timezone.utc) + timedelta(hours=1)))
        e5 = r.json() if r.ok else {}
        record("device clock 1 h ahead -> flagged device_clock_suspect", r.ok and "device_clock_suspect" in e5["flags"])
        old = up("document", REF[0], REF[1], captured=iso(datetime.now(timezone.utc) - timedelta(days=5)))
        record("photo captured 5 days before upload -> flagged, original time kept", old.ok and "device_clock_suspect" in old.json()["flags"]
               and abs((datetime.fromisoformat(old.json()["captured_at"]) - (datetime.now(timezone.utc) - timedelta(days=5))).total_seconds()) < 120)
        r = up("document", REF[0], REF[1], captured="yesterday")
        record("invalid capture timestamp rejected", r.status_code == 400)
        record("no API to edit evidence time/GPS (PUT/PATCH not allowed)",
               requests.put(f"{base}/files/{e1['id']}", headers=H(a1), json={"captured_at": "2000-01-01"}, timeout=30).status_code in (404, 405)
               and requests.patch(f"{base}/evidence/{e1['id']}", headers=H(a1), json={"gps": {}}, timeout=30).status_code in (404, 405))

        # ---- idempotent retry from the pending-upload queue
        uid = str(uuid.uuid4())
        img_seed = uuid.uuid4().hex
        r1 = up("document", REF[0], REF[1], captured=iso(datetime.now(timezone.utc)), extra={"upload_id": uid}, seed=img_seed)
        r2 = up("document", REF[0], REF[1], captured=iso(datetime.now(timezone.utc)), extra={"upload_id": uid}, seed=img_seed)
        record("retry with same upload_id -> same evidence, no duplicate", r1.ok and r2.ok and r1.json()["id"] == r2.json()["id"]
               and db.evidence.count_documents({"upload_id": uid}) == 1)
        record("unknown photo slot rejected", up("random_slot", REF[0], REF[1]).status_code == 400)
        record("other agent cannot upload to this case", up("exterior", REF[0], REF[1], token=a2).status_code == 403)

        # ---- visit start cannot be overwritten
        v1 = requests.post(f"{base}/cases/{cid}/visit-start", headers=H(a1), json={"lat": REF[0], "lon": REF[1], "accuracy": 8}, timeout=30).json()
        v2 = requests.post(f"{base}/cases/{cid}/visit-start", headers=H(a1), json={"lat": 1.0, "lon": 1.0, "accuracy": 1}, timeout=30).json()
        record("visit start: first fix kept, later call cannot overwrite", v2["visit"]["lat"] == REF[0] and v2["visit"]["started_at"] == v1["visit"]["started_at"])

        # ---- submission rules
        cfg = rt["residence_applicant"]
        data = {}
        for sec in cfg["sections"]:
            for f in sec["fields"]:
                if f.get("type") in ("select", "multiselect"):
                    data[f["key"]] = f["options"][0]
                elif f.get("type") == "number":
                    data[f["key"]] = "2"
                elif f.get("type") == "date":
                    data[f["key"]] = "1990-05-17"
                else:
                    data[f["key"]] = "Observed value for test"
        data["residence_status"] = "Parental"
        data["assigned_address"] = "AGENT TYPED A DIFFERENT ADDRESS"
        data["visit_datetime"] = "01-Jan-2000 10:00"
        fake_gps = {"lat": 1.234, "lon": 5.678, "accuracy": 1}
        # at this point all five slots have at least one photo -> remove 'interior' to test the missing-photo block
        interior_ids = [str(x["_id"]) for x in db.evidence.find({"case_id": cid, "slot": "interior"})]
        db.evidence.update_many({"case_id": cid, "slot": "interior"}, {"$set": {"slot": "interior_hidden"}})
        r = requests.post(f"{base}/reports/case/{cid}/submit", headers=H(a1), json={"data": data, "gps": fake_gps, "declaration": True}, timeout=60)
        probs = (r.json().get("detail") or {}).get("problems", []) if r.status_code == 422 else []
        record("submit blocked while a mandatory photo is missing (names the slot)", r.status_code == 422 and any("Interior" in p for p in probs), "; ".join(probs)[:120])
        db.evidence.update_many({"_id": {"$in": [ObjectId(i) for i in interior_ids]}}, {"$set": {"slot": "interior"}})

        draft = requests.put(f"{base}/reports/case/{cid}/draft", headers=H(a1), json={"data": data, "gps": fake_gps, "declaration": True}, timeout=60).json()
        record("draft: agent-typed address ignored, case address kept", draft["data"]["assigned_address"] == "Test address line, Test City")
        record("draft: agent-typed visit time ignored", draft["data"]["visit_datetime"] != "01-Jan-2000 10:00" and "IST" in draft["data"]["visit_datetime"],
               draft["data"]["visit_datetime"])
        record("draft: GPS taken from server records, not from client", draft["gps"].get("lat") != 1.234 and draft["gps"].get("source") in ("photo", "visit_start"))

        with cf.ThreadPoolExecutor(2) as ex:
            futs = [ex.submit(requests.post, f"{base}/reports/case/{cid}/submit", headers=H(a1),
                              json={"data": data, "gps": fake_gps, "declaration": True}, timeout=60) for _ in range(2)]
            codes = sorted(f.result().status_code for f in futs)
        record("double submission -> exactly one accepted", codes.count(200) == 1 and codes[1] in (400, 409), str(codes))
        rep = db.reports.find_one({"case_id": cid, "status": "submitted"})
        record("one submitted report version stored", db.reports.count_documents({"case_id": cid, "status": "submitted"}) == 1)
        record("Residence Status 'Parental' saved in MongoDB", rep["data"]["residence_status"] == "Parental")
        record("submitted address = case address", rep["data"]["assigned_address"] == "Test address line, Test City")
        record("submitted visit time = first visit/photo time in IST", "IST" in rep["data"]["visit_datetime"], rep["data"]["visit_datetime"])
        record("submitted GPS is server-derived", rep["gps"].get("lat") != 1.234)
        case_flags = requests.get(f"{base}/cases/{cid}", headers=H(admin), timeout=30).json()["flags"]
        record("evidence flags preserved on case after submission",
               {"photo_far_from_assigned", "photo_without_gps", "possible_mock_location", "device_clock_suspect"} <= set(case_flags), ",".join(case_flags))

        rv = requests.get(f"{base}/reports/{rep['_id']}", headers=H(sup), timeout=30).json()
        record("review screen shows 'Parental'", rv["masked_data"].get("residence_status") == "Parental")
        requests.post(f"{base}/reports/{rep['_id']}/review", headers=H(sup), json={"action": "approve"}, timeout=30).raise_for_status()
        pdf = requests.get(f"{base}/exports/case/{cid}/pdf", headers=H(admin), timeout=60)
        docx = requests.get(f"{base}/exports/case/{cid}/docx", headers=H(admin), timeout=60)
        import zipfile
        docx_text = zipfile.ZipFile(io.BytesIO(docx.content)).read("word/document.xml").decode("utf-8", "ignore")
        # VEE format prints values in capitals (PARENTAL), as in the reference document
        record("Word report shows 'Parental' and IST times", "PARENTAL" in docx_text.upper() and "IST" in docx_text)
        from pdf_text import pdf_text
        ptxt = pdf_text(pdf.content)
        record("PDF report shows 'Parental' and IST times", "PARENTAL" in ptxt.upper() and "IST" in ptxt,
               f"{len(ptxt)} chars; Parental={'PARENTAL' in ptxt.upper()}; IST={'IST' in ptxt}")
        mis = requests.get(f"{base}/exports/cases.xlsx", headers=H(admin), timeout=60)
        record("Excel case export still works (Residence Status is not an Excel/MIS column)", mis.status_code == 200 and mis.content[:2] == b"PK")

        # ---- historical "Other" values are not rewritten
        hist = db.reports.find_one({"data.residence_status": {"$exists": True}, "case_id": {"$ne": cid}})
        if hist:
            db.reports.update_one({"_id": hist["_id"]}, {"$set": {"data.residence_status": "Other"}})  # simulate an old submission
            hv = requests.get(f"{base}/reports/{hist['_id']}", headers=H(admin), timeout=30).json()
            record("historical 'Other' submission preserved and displayed as 'Other'",
                   hv["masked_data"]["residence_status"] == "Other" and db.reports.find_one({"_id": hist["_id"]})["data"]["residence_status"] == "Other")

        # ---- address lock + audited correction
        r = requests.post(f"{base}/cases/{cid}/location", headers=H(a1), json={"assigned_address": "Agent change", "reason": "test"}, timeout=30)
        record("agent cannot change assigned address/location", r.status_code == 403, str(r.status_code))
        r = requests.post(f"{base}/cases/{cid}/location", headers=H(sup), json={"assigned_address": "Corrected address", "assigned_lat": 19.08,
                                                                               "assigned_lon": 72.88, "reason": "Branch sent corrected address"}, timeout=30)
        record("supervisor corrects address + pin", r.ok and r.json()["assigned_address"] == "Corrected address" and r.json()["location_status"] == "pinned")
        a = db.audit_logs.find_one({"action": "case_location_corrected", "entity_id": cid})
        record("correction audited with who/when/before/after", bool(a) and a["user_role"] == "supervisor" and a["details"]["before"]["assigned_address"]
               == "Test address line, Test City" and a["details"]["after"]["assigned_address"] == "Corrected address" and a.get("created_at"))
        r = requests.post(f"{base}/cases/{cid}/location", headers=H(sup), json={"reason": "nothing"}, timeout=30)
        record("empty correction rejected", r.status_code == 400)

        # ---- Super Admin can change the distance threshold
        requests.put(f"{base}/settings", headers=H(admin), json={"updates": {"flag_distance_m": 10000}}, timeout=30).raise_for_status()
        cr3 = requests.post(f"{base}/cases", headers=H(admin), json={
            "client_case_id": f"VERIFY-{uuid.uuid4().hex[:6]}", "client_id": clients[0]["id"], "applicant_name": "Radius",
            "report_type": "residence_applicant", "assigned_address": "X", "primary_phone": "9000000002",
            "assigned_lat": REF[0], "assigned_lon": REF[1]}, timeout=30).json()
        requests.post(f"{base}/cases/{cr3['id']}/assign", headers=H(admin), json={"agent_id": a1u["id"]}, timeout=30).raise_for_status()
        r = up("exterior", *far, case_id=cr3["id"], captured=iso(datetime.now(timezone.utc)))
        record("Super Admin distance setting applied (5.5 km allowed at 10 km)", r.ok and r.json()["allowed_distance_m"] == 10000)
        record("supervisor cannot change the distance setting",
               requests.put(f"{base}/settings", headers=H(sup), json={"updates": {"flag_distance_m": 1}}, timeout=30).status_code == 403)

        # ---- geocoder (one public landmark, direct call)
        import geocoding  # noqa: E402
        try:
            g = geocoding.geocode_case_address({"assigned_address": "Gateway of India", "city": "Mumbai", "state": "Maharashtra", "pincode": "400001"})
            record("geocoder resolves a public address", bool(g) and 18.8 < g["lat"] < 19.2 and 72.7 < g["lon"] < 73.0, str(g))
        except Exception as exc:
            record("geocoder resolves a public address", None, f"SKIPPED (network): {type(exc).__name__}")
    finally:
        try:
            sys.path.insert(0, str(BACKEND))
            os.environ.update({k: v for k, v in file_env.items() if k.startswith("R2_") and v})
            os.environ["MEDIA_FOLDER_ENV"] = "verify"
            import storage_service  # noqa: E402
            paths = []
            for e in db.evidence.find({"storage_provider": "r2"}, {"storage_path": 1, "original": 1}):
                paths.append(e["storage_path"])
                if (e.get("original") or {}).get("storage_path"):
                    paths.append(e["original"]["storage_path"])
            left = 0
            for p in paths:
                try:
                    storage_service.delete_object(p, "r2")
                except Exception:
                    left += 1
            left += r2_test_utils.sweep()
            record("cleanup: all test photos deleted from the R2 test bucket", left == 0, f"{len(paths)} assets")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
            log.close()
            for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "ERROR" in line or "Traceback" in line:
                    print("  server:", line[:220])
            log_path.unlink(missing_ok=True)
            mongo.drop_database(DB_NAME)
            print(f"dropped throwaway database {DB_NAME}")
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    print(f"\n{len(RESULTS) - len(fails)} passed/skipped, {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
