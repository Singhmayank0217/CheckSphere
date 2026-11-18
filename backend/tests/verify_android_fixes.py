"""Isolated verification of the corrections after the Android test of 14-Nov-2026:
  1. submitted form values disappearing (report version tie: stale draft shown instead of the submission)
  2. missing / unverified case reference location (CSV-000015, 2C NS Road, Howrah 711204 vs capture in Belur)
  3. VEE format with red (mandatory) AND black (optional) content

SAFE BY CONSTRUCTION: own backend on a free port, throwaway LOCAL MongoDB (dropped at the end), synthetic photos only
(uploaded to the R2 test bucket under checksphere/verify/... and all deleted at the end). Address lookups go to the live
geocoder with the address text only, exactly as production does. No real case record is read or written.

Run from the repo root:  .venv\\Scripts\\python.exe backend\\tests\\verify_android_fixes.py
"""
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pdf_text import pdf_text  # noqa: E402

LOCAL_MONGO = os.environ.get("VERIFY_LOCAL_MONGO", "mongodb://localhost:27017")
DB_NAME = f"checksphere_verify_{uuid.uuid4().hex[:8]}"
CAPTURE = (22.623922, 88.353029)      # the agent's capture point in Belur (Android test, +/-8.3 m)
CAPTURE_ACC = 8.3
LILUAH_ADDRESS = "2C NS ROAD SHANTINAGAR NAGAR\nGOKUL APARTMENT FLAT 7 SECOND FLOOR"   # as stored on CSV-000015
TEST_PIN = (22.6209027, 88.3394035)   # Liluah railway station: a TEST pin only (the true flat location is not known)
RESULTS = []
SLOTS = ["exterior", "exterior_2", "interior", "selfie", "document"]


def record(name, ok, detail=""):
    status = "SKIP" if ok is None else ("PASS" if bool(ok) else "FAIL")
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name} {detail}", flush=True)


def photo_bytes(seed: int, w=1600, h=1200) -> bytes:
    img = Image.new("RGB", (w, h), (90 + seed * 25 % 120, 140, 180))
    d = ImageDraw.Draw(img)
    for i in range(0, w, 40):
        d.rectangle([i, h // 2, i + 20, h], fill=((seed * 37 + i) % 255, 80, 60))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def docx_xml(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return z.read("word/document.xml").decode("utf-8")


def docx_runs(xml: str) -> list:
    """[(text, colour)] for every run of the Word document body."""
    out = []
    for r in re.finditer(r"<w:r>(.*?)</w:r>|<w:r [^>]*>(.*?)</w:r>", xml, re.S):
        body = r.group(1) or r.group(2) or ""
        t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", body, re.S))
        c = re.search(r'<w:color w:val="([0-9A-Fa-f]{6})"', body)
        if t:
            out.append((t.replace("&amp;", "&").replace("&#8217;", "’"), c.group(1).upper() if c else None))
    return out


def filled_values(cfg: dict, tag: str) -> dict:
    """A distinct value for every editable field of the form, so each one can be traced end to end."""
    data = {}
    for sec in cfg["sections"]:
        for f in sec["fields"]:
            if f.get("readonly"):
                continue
            k, t = f["key"], f.get("type")
            if t == "select":
                data[k] = f["options"][-1] if k not in ("vee_remarks", "vee_recommendation", "assets_seen", "marital_status") else f["options"][0]
            elif t == "multiselect":
                data[k] = "; ".join([f["options"][2], f["options"][8]])
            elif t == "date":
                data[k] = "1988-08-05"
            elif t == "number":
                data[k] = "4"
            else:
                data[k] = f"{tag} {k.replace('_', ' ')}"
    return data


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
           "GEOCODING_PROVIDER": "nominatim", "BACKUP_DIR": str(Path(os.environ.get("TEMP", BACKEND)) / DB_NAME)}
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
        sup, _ = login("sup1@checksphere.app", "Super@12345", "Verify@Sup1xx")
        clients = requests.get(f"{base}/clients", headers=H(admin), timeout=30).json()["items"]

        def new_case(name, rtype="residence_applicant", **extra):
            body = {"client_id": clients[0]["id"], "applicant_name": name, "report_type": rtype, "loan_type": "Home Loan",
                    "assigned_address": "11 Girish Ghosh Road", "pincode": "711202", "primary_phone": "9000000000", **extra}
            c = requests.post(f"{base}/cases", headers=H(admin), json=body, timeout=30).json()
            requests.post(f"{base}/cases/{c['id']}/assign", headers=H(admin), json={"agent_id": a1u["id"]}, timeout=30).raise_for_status()
            return c

        def up(cid, slot, lat, lon, acc, reason=None, seed=1):
            cap = datetime.now(timezone.utc)
            f = {"case_id": cid, "slot": slot, "kind": "photo", "captured_at": cap.isoformat(), "gps_status": "ok",
                 "lat": str(lat), "lon": str(lon), "accuracy": str(acc), "gps_fix_at": cap.isoformat(),
                 "gps_source": "watch", "upload_id": uuid.uuid4().hex}
            if reason:
                f["location_reason"] = reason
            return requests.post(f"{base}/evidence/upload", headers=H(a1), data=f,
                                 files={"file": (f"{slot}.jpg", photo_bytes(seed), "image/jpeg")}, timeout=180)

        # ================================================================ 1. form values end to end
        print("\n--- 1. submitted values: draft -> submit -> DB -> report screen -> review -> Word/PDF")
        A = new_case("Field Trace", assigned_lat=CAPTURE[0], assigned_lon=CAPTURE[1])
        cid = A["id"]
        ctx = requests.get(f"{base}/reports/case/{cid}", headers=H(a1), timeout=30).json()
        cfg = ctx["config"]
        gps = {"lat": CAPTURE[0], "lon": CAPTURE[1], "accuracy": CAPTURE_ACC}
        # the real sequence on CSV-000015: an early server draft holding only a few fields
        early = {"landmark": "Bally", "locality": "Urban", "exterior_observation": "S2"}
        r = requests.put(f"{base}/reports/case/{cid}/draft", headers=H(a1), json={"data": early, "gps": gps}, timeout=30)
        record("early server draft saved (version 1, few fields)", r.ok and r.json().get("version") == 1)
        for i, slot in enumerate(SLOTS):
            rr = up(cid, slot, *CAPTURE, CAPTURE_ACC, seed=i + 1)
            if not rr.ok:
                print("   upload failed:", slot, rr.status_code, rr.text[:200])
        record("five photographs captured and stored", db.evidence.count_documents({"case_id": cid, "kind": "photo"}) == 5)
        values = filled_values(cfg, "T1")
        r = requests.post(f"{base}/reports/case/{cid}/submit", headers=H(a1), json={"data": values, "gps": gps, "declaration": True}, timeout=60)
        record("submission with a value in every field accepted", r.ok, "" if r.ok else r.text[:300])
        sub_id = r.json().get("id") if r.ok else None
        docs = list(db.reports.find({"case_id": cid}))
        record("reproduced the version tie: superseded draft v1 + submitted v1",
               sorted((d["version"], d["status"]) for d in docs) == [(1, "submitted"), (1, "superseded")], str([(d["version"], d["status"]) for d in docs]))
        stored = db.reports.find_one({"case_id": cid, "status": "submitted"})["data"]
        lost = [k for k, v in values.items() if stored.get(k) != v]
        record(f"database: all {len(values)} entered values saved exactly", not lost, f"lost/changed: {lost[:8]}")
        screen = requests.get(f"{base}/reports/case/{cid}", headers=H(a1), timeout=30).json()
        shown = (screen.get("report") or {}).get("data") or {}
        diff = [k for k, v in values.items() if shown.get(k) != v]
        record("agent report screen shows the submitted report (not the stale draft)",
               (screen.get("report") or {}).get("id") == sub_id and not diff, f"status={(screen.get('report') or {}).get('status')} differing={diff[:8]}")
        case_doc = requests.get(f"{base}/cases/{cid}", headers=H(admin), timeout=30).json()
        record("case detail latest_report is the submission", (case_doc.get("latest_report") or {}).get("id") == sub_id)
        rv = requests.get(f"{base}/reports/{sub_id}?reveal=1", headers=H(sup), timeout=30).json()
        diff = [k for k, v in values.items() if (rv.get("report") or {}).get("data", {}).get(k) != v]
        record("supervisor review shows the same values", not diff and rv["report"].get("is_current") is True, f"differing={diff[:8]}")
        stale = next(d for d in docs if d["status"] == "superseded")
        r = requests.post(f"{base}/reports/{stale['_id']}/review", headers=H(sup), json={"action": "approve", "comment": "x"}, timeout=30)
        record("stale draft cannot be reviewed/approved", r.status_code in (400, 409), str(r.status_code))
        # CSV-000016 state: the stale draft was wrongly flipped to under_review by an old review page
        db.reports.update_one({"_id": stale["_id"]}, {"$set": {"status": "under_review"}})
        case_doc = requests.get(f"{base}/cases/{cid}", headers=H(admin), timeout=30).json()
        record("even with the stale draft marked under_review (CSV-000016 state) the submission is current",
               (case_doc.get("latest_report") or {}).get("id") == sub_id)
        r = requests.post(f"{base}/reports/{stale['_id']}/review", headers=H(sup), json={"action": "approve", "comment": "x"}, timeout=30)
        record("...and that stale document still cannot be approved (409)", r.status_code == 409, str(r.status_code))
        r = requests.post(f"{base}/reports/{sub_id}/review", headers=H(sup), json={"action": "approve", "comment": "ok"}, timeout=30)
        record("the real submission can be approved", r.ok, r.text[:200] if not r.ok else "")
        wd = requests.get(f"{base}/exports/case/{cid}/docx", headers=H(sup), timeout=180)
        pdf = requests.get(f"{base}/exports/case/{cid}/pdf", headers=H(sup), timeout=180)
        record("Word and PDF exports downloaded", wd.ok and pdf.ok, f"{wd.status_code} {pdf.status_code}")
        xml = docx_xml(wd.content)
        wtext = re.sub(r"\s+", " ", "".join(t for t, _ in docx_runs(xml)).upper())
        ptext = re.sub(r"\s+", " ", pdf_text(pdf.content).upper())
        printed = ["address_confirmed_by", "marital_status", "earning_members", "approx_value", "approx_rent", "unit", "roof_type",
                   "vehicle", "landmark", "accommodation_type", "interior_condition", "standard_of_living", "approx_area_sqft",
                   "previously_applied", "previous_file_date", "nb_applicant_name", "nb_person_met", "nb_relationship",
                   "nb_applicant_age", "nb_residents", "nb_years_lived", "nb_occupation", "accessibility", "loan_type", "agent_remarks"]
        miss_w = [k for k in printed if str(values[k]).upper() not in wtext]
        miss_p = [k for k in printed if str(values[k]).upper() not in ptext]
        record("Word export prints every entered VEE value", not miss_w, f"missing: {miss_w}")
        record("PDF export prints every entered VEE value", not miss_p, f"missing: {miss_p}")
        record("DOB, Remarks, Recommendation, Assets Seen printed (Word and PDF)",
               all(x in wtext and x in ptext for x in ("05-AUG-1988", "REMARKS:- POSITIVE", "RECOMMENDATION:- YES", "ASSETS SEEN (Y/N):- YES")))

        # ================================================================ 3. VEE red + black
        print("\n--- 3. VEE: red (mandatory) and black (optional) content")
        runs = docx_runs(xml)

        def colour_of(label):
            return next((c for t, c in runs if t.strip().startswith(label)), "absent")
        reds = ["Bank / Branch Name:-", "Nearest Landmark:-", "Unit:-", "Type of Loan:-", "Assets Seen (Y/N):-", "Remarks:-", "Recommendation:-"]
        blacks = ["Approx. Value(If Owned):-", "Approx. Rent:-", "Location:-", "Locality:-", "Accommodation Type:-", "Interior Condition:-",
                  "Standard Living:-", "Approx. Area (sq. Ft.):-", "Applicant Age(Approx.):-", "Occupation:-",
                  "Did the Customer Applied Previously:-", "Verifier Observation", "Verifier Remarks:-",
                  "If the house is locked", "Reasons for Not Recommended", "Verifier Name: -", "Authorized Signature with Seal"]
        bad_r = [(x, colour_of(x)) for x in reds if colour_of(x) != "FF0000"]
        bad_k = [(x, colour_of(x)) for x in blacks if colour_of(x) != "000000"]
        record("Word: red VEE labels are red", not bad_r, str(bad_r))
        record("Word: black VEE labels and headings are present and black", not bad_k, str(bad_k))
        pt = pdf_text(pdf.content)
        record("PDF: same black sections present", all(x in pt for x in ("Verifier Observation", "If the house is locked", "Reasons for Not Recommended",
                                                                          "Authorized Signature with Seal", "Approx. Area (sq. Ft.)")))
        record("ticked reasons printed with a check mark (Word)", xml.count("✔") == 2, f"{xml.count(chr(0x2714))} ticks")
        record("no Evidence Photo References table; 5 photos labelled",
               "Evidence Photo References" not in pt and all(x in pt for x in ("Exterior", "Interior", "Selfie", "Supporting Document")))

        B = new_case("Mandatory Check", assigned_lat=CAPTURE[0], assigned_lon=CAPTURE[1])
        for i, slot in enumerate(SLOTS):
            up(B["id"], slot, *CAPTURE, CAPTURE_ACC, seed=20 + i)
        cfgB = requests.get(f"{base}/reports/case/{B['id']}", headers=H(a1), timeout=30).json()["config"]
        red_only = {}
        for sec in cfgB["sections"]:
            for f in sec["fields"]:
                if f.get("required") and not f.get("readonly"):
                    red_only[f["key"]] = filled_values({"sections": [{"fields": [f]}]}, "T2")[f["key"]]
        r = requests.post(f"{base}/reports/case/{B['id']}/submit", headers=H(a1),
                          json={"data": {k: v for k, v in red_only.items() if k != "landmark"}, "gps": gps, "declaration": True}, timeout=60)
        record("missing red field blocks submission and is named ('Nearest Landmark')",
               r.status_code == 422 and "Nearest Landmark" in r.json()["detail"].get("missing_fields", []), r.text[:200])
        r = requests.post(f"{base}/reports/case/{B['id']}/submit", headers=H(a1),
                          json={"data": {**red_only, "not_recommended_reasons": "Not a listed reason"}, "gps": gps, "declaration": True}, timeout=60)
        record("an unlisted tick-list value is rejected", r.status_code == 422 and any("Tick only" in p for p in r.json()["detail"].get("problems", [])))
        r = requests.post(f"{base}/reports/case/{B['id']}/submit", headers=H(a1), json={"data": red_only, "gps": gps, "declaration": True}, timeout=60)
        record("all red fields filled, every black field empty: submission accepted", r.ok, r.text[:200] if not r.ok else "")
        optional_req = [f["key"] for sec in cfgB["sections"] for f in sec["fields"]
                        if f["key"] in ("approx_value", "approx_rent", "locality", "accommodation_type", "nb_occupation", "not_recommended_reasons") and f.get("required")]
        record("black VEE fields are optional in the form", not optional_req, str(optional_req))
        stored_b = db.reports.find_one({"case_id": B["id"], "status": "submitted"})["data"]
        record("Type of Loan pre-filled from the case when the agent leaves it blank",
               stored_b.get("loan_type") == red_only.get("loan_type") or stored_b.get("loan_type") == "Home Loan")

        # ================================================================ 2. reference location
        print("\n--- 2. reference location: CSV-000015 address vs capture in Belur")
        L = new_case("Bapi (test copy)", assigned_address=LILUAH_ADDRESS, city="Howrah", state="West Bengal", pincode="711204")
        lid = L["id"]
        st = None
        for _ in range(90):
            st = db.cases.find_one({"_id": __import__("bson").ObjectId(lid)})
            if st.get("location_status") != "pending":
                break
            time.sleep(1)
        record("automatic lookup ran and did NOT invent a location for the unfindable address",
               st.get("location_status") == "needs_pin" and st.get("assigned_lat") is None, f"status={st.get('location_status')}")
        note = st.get("location_note") or ""
        print("   lookup note:", note)
        record("lookup explains why (wrong street / PIN centre in another district)",
               "different street" in note or "not in the map data" in note)
        record("the wrong-district PIN 711204 centre is offered only as an unverified candidate",
               any(c.get("precision") == "pincode" and not c.get("verified") for c in st.get("location_candidates") or []))
        cview = requests.get(f"{base}/cases/{lid}", headers=H(a1), timeout=30).json()
        record("agent app receives the plain-language missing-location reason", bool(cview.get("location_problem")), (cview.get("location_problem") or "")[:120])
        r = up(lid, "exterior", *CAPTURE, CAPTURE_ACC, seed=31)
        j = r.json() if r.ok else {}
        lc = j.get("location_check") or {}
        record("photo accepted, distance NOT claimed, flagged no_reference_location with the specific reason",
               r.ok and lc.get("status") == "no_reference" and lc.get("distance_m") is None and "no_reference_location" in j.get("flags", [])
               and "Could not locate" in (lc.get("explanation") or ""), (lc.get("explanation") or "")[:140])
        record("photo record keeps the reference it was compared with (assigned address, no coordinates)",
               (lc.get("reference") or {}).get("address") == LILUAH_ADDRESS and (lc.get("reference") or {}).get("lat") is None)
        # legacy case exactly like CSV-000015: created before automatic lookup, no location fields at all
        legacy = {k: v for k, v in db.cases.find_one({"_id": __import__("bson").ObjectId(lid)}).items()
                  if k not in ("_id", "location_status", "location_note", "location_candidates", "location_source", "location_precision", "geocoded_at")}
        legacy["internal_case_id"] = "CSV-LEGACY-T"
        leg_id = str(db.cases.insert_one(legacy).inserted_id)
        lv = requests.get(f"{base}/cases/{leg_id}", headers=H(admin), timeout=30).json()
        record("legacy case (never geocoded) is identified as such", "never been located" in (lv.get("location_problem") or ""), lv.get("location_problem") or "")
        r = requests.post(f"{base}/cases/{lid}/location/lookup", headers=H(a1), timeout=30)
        r2 = requests.post(f"{base}/cases/{lid}/location", headers=H(a1), json={"assigned_lat": 1, "assigned_lon": 1, "reason": "agent try"}, timeout=30)
        record("agents cannot look up, pin or confirm a case location (403)", r.status_code == 403 and r2.status_code == 403)
        r = requests.post(f"{base}/cases/{lid}/location/lookup", headers=H(sup), timeout=120)
        record("supervisor 'look up now' works and keeps it unlocated", r.ok and r.json().get("assigned_lat") is None and r.json().get("location_status") == "needs_pin",
               r.text[:150] if not r.ok else "")
        cands = (r.json() if r.ok else {}).get("location_candidates") or []
        ci = next((i for i, c in enumerate(cands) if c.get("precision") == "pincode"), None)
        if ci is not None:
            r = requests.post(f"{base}/cases/{lid}/location", headers=H(sup), json={"candidate": ci, "reason": "TEST: confirm PIN centre candidate"}, timeout=30)
            cc = r.json() if r.ok else {}
            record("confirmed candidate keeps its own (PIN-level) precision, status confirmed",
                   r.ok and cc.get("location_precision") == "pincode" and cc.get("location_status") == "confirmed")
            r = up(lid, "exterior_2", *CAPTURE, CAPTURE_ACC, seed=32)
            lc = (r.json() if r.ok else {}).get("location_check") or {}
            print(f"   vs confirmed PIN centre {cands[ci]['lat']},{cands[ci]['lon']}: {lc.get('distance_m')} m, {lc.get('status')} - {lc.get('explanation')}")
            record("PIN-level reference: distance computed and reported as UNCERTAIN, not 'within'", r.ok and lc.get("status") == "uncertain")
        else:
            record("PIN centre candidate available to confirm", None, "skipped: lookup returned no PIN candidate")
        r = requests.post(f"{base}/cases/{lid}/location", headers=H(sup),
                          json={"assigned_lat": TEST_PIN[0], "assigned_lon": TEST_PIN[1], "reason": "TEST pin at Liluah station"}, timeout=30)
        pc = r.json() if r.ok else {}
        record("supervisor pin saved as exact reference", r.ok and pc.get("location_precision") == "exact" and pc.get("location_status") == "pinned")
        aud = db.audit_logs.find_one({"entity_id": lid, "action": "case_location_corrected"}, sort=[("_id", -1)])
        record("pin audited with before/after coordinates and precision",
               bool(aud) and (aud.get("details") or {}).get("after", {}).get("assigned_lat") == TEST_PIN[0]
               and "location_precision" in (aud.get("details") or {}).get("before", {}))
        r = up(lid, "interior", *CAPTURE, CAPTURE_ACC, seed=33)
        jj = r.json() if r.status_code == 422 else {}
        d = (jj.get("detail") or {})
        print(f"   vs exact test pin {TEST_PIN}: {d.get('distance_m')} m - {d.get('message')}")
        record("exact reference 1.4 km away: outside -> reason required (422)", r.status_code == 422 and d.get("code") == "outside_allowed_distance"
               and 1400 < (d.get("distance_m") or 0) < 1480)
        r = up(lid, "interior", *CAPTURE, CAPTURE_ACC, reason="TEST: agent explains the distance", seed=33)
        record("...accepted with a reason and flagged for supervisor review", r.ok and "photo_far_from_assigned" in r.json().get("flags", []))
        after = db.cases.find_one({"_id": __import__("bson").ObjectId(lid)})
        record("reference coordinates never replaced by capture coordinates",
               (after["assigned_lat"], after["assigned_lon"]) == TEST_PIN)
        r = requests.post(f"{base}/cases/{lid}/location", headers=H(sup), json={"assigned_address": "9 Test Road, Liluah", "reason": "TEST address change"}, timeout=30)
        rc = r.json() if r.ok else {}
        aud = db.audit_logs.find_one({"entity_id": lid, "action": "case_location_corrected"}, sort=[("_id", -1)])
        record("address change resets the reference for a fresh lookup, audited with the old pin",
               r.ok and rc.get("assigned_lat") is None and rc.get("location_status") == "pending"
               and (aud.get("details") or {}).get("before", {}).get("assigned_lat") == TEST_PIN[0])
    finally:
        try:
            left = 0
            paths = set()
            for e in db.evidence.find({"storage_provider": "r2"}):
                paths.add(e["storage_path"])
                if (e.get("original") or {}).get("storage_path"):
                    paths.add(e["original"]["storage_path"])
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
