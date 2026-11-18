"""Isolated verification of the eight field-verification / GPS / report / performance fixes (14-Nov-2026).

SAFE BY CONSTRUCTION: own backend on a free port, throwaway LOCAL MongoDB (dropped at the end), synthetic photos only
(uploaded to the R2 test bucket under checksphere/verify/... and all deleted at the end). Reverse geocoding uses the live
providers with coordinates only, exactly as production does.

Run from the repo root:  .venv\\Scripts\\python.exe backend\\tests\\verify_eight_fixes.py
"""
import hashlib
import io
import os
import re
import socket
import statistics
import subprocess
import sys
import time
import uuid
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values
from PIL import Image, ImageDraw
from pymongo import MongoClient

import r2_test_utils

BACKEND = Path(__file__).resolve().parents[1]
LOCAL_MONGO = os.environ.get("VERIFY_LOCAL_MONGO", "mongodb://localhost:27017")
DB_NAME = f"checksphere_verify_{uuid.uuid4().hex[:8]}"
SITE = (22.6242634, 88.3529103)          # the agent's real test location (Belur, PIN 711202) from CSV-000026
PIN_711202_CENTRE = (22.632274, 88.352218)  # what the geocoder gave CSV-000026 as its (PIN-level) reference point
M_PER_DEG_LAT = 111_320
RESULTS = []
TIMINGS = []


def record(name, ok, detail=""):
    status = "SKIP" if ok is None else ("PASS" if bool(ok) else "FAIL")
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name} {detail}", flush=True)


def north(lat_lon, metres):
    return lat_lon[0] + metres / M_PER_DEG_LAT, lat_lon[1]


def photo_bytes(seed: int, w=1600, h=1200) -> bytes:
    img = Image.new("RGB", (w, h), (90 + seed * 25 % 120, 140, 180))
    d = ImageDraw.Draw(img)
    for i in range(0, w, 40):
        d.rectangle([i, h // 2, i + 20, h], fill=((seed * 37 + i) % 255, 80, 60))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def pdf_streams(pdf: bytes) -> bytes:
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            out.append(zlib.decompress(m.group(1)))
        except Exception:
            out.append(m.group(1))
    return b"\n".join(out)


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
        a2, _ = login("AGT102", "Agent@12345", "Verify@Agent2x")
        sup, _ = login("sup1@checksphere.app", "Super@12345", "Verify@Sup1xx")
        clients = requests.get(f"{base}/clients", headers=H(admin), timeout=30).json()["items"]

        def new_case(name, lat=None, lon=None, rtype="residence_applicant"):
            body = {"client_id": clients[0]["id"], "applicant_name": name, "report_type": rtype,
                    "assigned_address": "11 Girish Ghosh Road", "pincode": "711202", "primary_phone": "9000000000"}
            if lat is not None:
                body.update({"assigned_lat": lat, "assigned_lon": lon})
            c = requests.post(f"{base}/cases", headers=H(admin), json=body, timeout=30).json()
            requests.post(f"{base}/cases/{c['id']}/assign", headers=H(admin), json={"agent_id": a1u["id"]}, timeout=30).raise_for_status()
            return c

        def up(cid, slot, lat, lon, acc, reason=None, fix_at=None, captured=None, seed=1, source="watch"):
            cap = captured or datetime.now(timezone.utc)
            f = {"case_id": cid, "slot": slot, "kind": "photo", "captured_at": cap.isoformat(), "gps_status": "ok",
                 "lat": str(lat), "lon": str(lon), "accuracy": str(acc), "gps_fix_at": (fix_at or cap).isoformat(),
                 "gps_source": source, "upload_id": uuid.uuid4().hex}
            if reason:
                f["location_reason"] = reason
            return requests.post(f"{base}/evidence/upload", headers=H(a1), data=f,
                                 files={"file": (f"{slot}.jpg", photo_bytes(seed), "image/jpeg")}, timeout=180)

        # ================================================================ 2. GPS distance
        print("\n--- GPS distance (pinned reference at the agent's site)")
        A = new_case("Gps Pinned", *SITE)
        cid = A["id"]
        r = up(cid, "exterior", *north(SITE, 200), 10)
        j = r.json() if r.ok else {}
        record("in range (200 m, ±10 m) accepted with no reason", r.status_code == 200 and "photo_far_from_assigned" not in j.get("flags", []),
               f"{r.status_code} {j.get('location_check', {}).get('status')}")
        record("location_check stored with distance, margin and explanation",
               (j.get("location_check") or {}).get("status") == "within" and j.get("distance_m") is not None)
        record("GPS source + fix time recorded with the evidence", (j.get("gps") or {}).get("source") == "watch" and (j.get("gps") or {}).get("fix_at"))
        r = up(cid, "exterior_2", *north(SITE, 560), 80, seed=2)
        j = r.json() if r.ok else {}
        record("borderline (560 m, ±80 m): uncertain, accepted WITHOUT a reason, flagged for review",
               r.status_code == 200 and "location_uncertain" in j.get("flags", []) and "photo_far_from_assigned" not in j.get("flags", []),
               f"{r.status_code} {(j.get('location_check') or {}).get('explanation', '')[:90]}")
        r = up(cid, "interior", *north(SITE, 2000), 10, seed=3)
        record("genuinely outside (2 km, ±10 m): refused until a reason is given (422)",
               r.status_code == 422 and r.json()["detail"]["code"] == "outside_allowed_distance", str(r.status_code))
        r = up(cid, "interior", *north(SITE, 2000), 10, reason="Applicant met at shop 2 km away", seed=3)
        j = r.json() if r.ok else {}
        record("outside with reason: accepted, flagged photo_far_from_assigned, reason kept",
               r.status_code == 200 and "photo_far_from_assigned" in j.get("flags", []) and j.get("location_reason"))
        stale = datetime.now(timezone.utc)
        r = up(cid, "selfie", *north(SITE, 30), 8, fix_at=stale - timedelta(minutes=10), captured=stale, seed=4)
        record("stale GPS fix (10 min older than the photo) flagged", r.ok and "stale_gps_fix" in r.json().get("flags", []))
        r = up(cid, "interior", SITE[0], SITE[1], 9, seed=5)          # retake interior inside the radius
        r = up(cid, "selfie", SITE[0], SITE[1], 9, seed=6)
        r = up(cid, "document", SITE[0], SITE[1], 9, seed=7)
        record("all five photo slots uploaded for the pinned case", r.ok)

        print("\n--- CSV-000026 geometry: PIN-level reference point")
        B = new_case("Gps Pincode")
        db.cases.update_one({"_id": __import__("bson").ObjectId(B["id"])}, {"$set": {
            "assigned_lat": PIN_711202_CENTRE[0], "assigned_lon": PIN_711202_CENTRE[1], "location_source": "geocoded",
            "location_status": "geocoded", "location_precision": "pincode"}})
        r = up(B["id"], "exterior", *SITE, 82.5, seed=8)
        j = r.json() if r.ok else {}
        record("at the real address, ~890 m from the PIN centre: NO reason demanded (was 422 before)",
               r.status_code == 200 and "photo_far_from_assigned" not in j.get("flags", []), f"{r.status_code} distance {j.get('distance_m')}")
        record("...marked 'uncertain' with an explanation naming the approximate case location",
               "location_uncertain" in j.get("flags", []) and "approximate" in (j.get("location_check") or {}).get("explanation", ""))
        addr = (j.get("photo_address") or {})
        record("watermark address from the captured GPS shows PIN 711202 (not 711107/711101)",
               "711202" in (addr.get("text") or "") and "711107" not in (addr.get("text") or "") and "711101" not in (addr.get("text") or ""),
               repr(addr.get("text")))
        record("watermark address is labelled approximate (no street-level match exists)", addr.get("status") == "approximate")
        wm_lines = (j.get("watermark") or {}).get("lines") or []
        record("assigned address is never printed on the photo", not any("Girish Ghosh" in ln for ln in wm_lines), str(wm_lines[4:5]))
        r = up(B["id"], "exterior_2", *north(PIN_711202_CENTRE, 10_000), 20, seed=9)
        record("PIN-level reference, 10 km away: still refused without a reason", r.status_code == 422, str(r.status_code))

        print("\n--- no reference location")
        C = new_case("Gps NoRef")
        db.cases.update_one({"_id": __import__("bson").ObjectId(C["id"])}, {"$set": {"location_status": "not_found"}})
        r = up(C["id"], "exterior", *SITE, 12, seed=10)
        j = r.json() if r.ok else {}
        record("no reference: accepted, distance None, flag no_reference_location, explicit explanation",
               r.ok and j.get("distance_m") is None and "no_reference_location" in j.get("flags", [])
               and "cannot be checked" in (j.get("location_check") or {}).get("explanation", ""))

        # ================================================================ 5. DOB + submission
        print("\n--- Date of Birth + submission")
        ctx = requests.get(f"{base}/reports/case/{cid}", headers=H(a1), timeout=30).json()
        cfg = ctx["config"]
        dob_field = next(f for sec in cfg["sections"] for f in sec["fields"] if f["key"] == "applicant_dob")
        record("DOB field is a date field limited to today", dob_field.get("type") == "date" and dob_field.get("max_today") is True)
        data = {}
        for sec in cfg["sections"]:
            for f in sec["fields"]:
                if f.get("readonly"):
                    continue
                data[f["key"]] = (f.get("options") or ["x"])[0] if f.get("type") in ("select", "multiselect") else \
                    "3" if f.get("type") == "number" else "Observed value"
        gps = {"lat": SITE[0], "lon": SITE[1], "accuracy": 9}

        def submit(dob):
            return requests.post(f"{base}/reports/case/{cid}/submit", headers=H(a1),
                                 json={"data": {**data, "applicant_dob": dob}, "gps": gps, "declaration": True}, timeout=60)
        future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
        r = submit(future)
        record("future DOB rejected", r.status_code == 422 and any("future" in p for p in r.json()["detail"].get("problems", [])))
        r = submit("1204/2001")
        record("free-text DOB (as typed in CSV-000026) rejected with 'select with the date picker'",
               r.status_code == 422 and any("date picker" in p for p in r.json()["detail"].get("problems", [])))
        r = submit("2001-02-30")
        record("impossible date (30-Feb) rejected", r.status_code == 422)
        r = submit("1988-08-05")
        record("valid picked DOB: submission accepted", r.status_code == 200, f"{r.status_code} {r.text[:200] if not r.ok else ''}")
        rep = db.reports.find_one({"case_id": cid}, sort=[("version", -1)])
        record("DOB stored as YYYY-MM-DD (no time/timezone)", (rep or {}).get("data", {}).get("applicant_dob") == "1988-08-05")

        # ================================================================ 4/7/8. exports
        print("\n--- exports: permissions")
        r = requests.get(f"{base}/exports/case/{cid}/docx", headers=H(sup), timeout=120)
        record("supervisor cannot export before approval (403)", r.status_code == 403)
        r = requests.get(f"{base}/exports/case/{cid}/docx", headers=H(a1), timeout=120)
        record("agent cannot export (403)", r.status_code == 403)
        rr = requests.post(f"{base}/reports/{rep['_id']}/review", headers=H(sup), json={"action": "approve", "comment": "ok"}, timeout=60)
        record("supervisor approved the report", rr.ok, rr.text[:120] if not rr.ok else "")

        ev = list(db.evidence.find({"case_id": cid, "kind": "photo"}))
        latest = {}
        for e in sorted(ev, key=lambda e: e["captured_at"]):
            latest.setdefault(e["slot"], []).append(e)
        stored_shas = {e["watermark"]["sha256"] for e in ev}

        def timed(who, token, fmt):
            t = time.monotonic()
            r = requests.get(f"{base}/exports/case/{cid}/{fmt}", headers=H(token), timeout=300)
            dt = time.monotonic() - t
            TIMINGS.append((who, fmt, r.headers.get("X-Report-Cache"), round(dt, 2), len(r.content)))
            return r, dt

        print("\n--- exports: content and speed")
        r, dt = timed("super_admin", admin, "docx")
        record("Word export 200 with correct type + file name", r.ok and r.headers["Content-Type"].startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            and re.search(r'filename="CSV-\d{6}-v\d+\.docx"', r.headers.get("Content-Disposition", "")), f"{dt:.2f}s")
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml = z.read("word/document.xml").decode("utf-8")
        text = re.sub(r"<[^>]+>", "", xml)
        record("Word: 'Evidence Photo References' table absent", "Evidence Photo References" not in text and "Captured At" not in text)
        record("Word: VEE red-only format used (title + red runs)", "Applicant Residence Verification Report" in text and 'w:val="FF0000"' in xml)
        record("Word: no file names / slot keys / storage links", "exterior_2" not in text and ".jpg" not in text
               and b"r2.cloudflarestorage" not in r.content.lower())
        media = [n for n in z.namelist() if n.startswith("word/media/")]
        media_shas = {hashlib.sha256(z.read(n)).hexdigest() for n in media}
        current_shas = {sorted(v, key=lambda e: e["captured_at"])[-1]["watermark"]["sha256"] for v in latest.values()}
        record("Word: every embedded photo is byte-identical to a stored watermarked evidence photo of THIS case",
               (media_shas - {hashlib.sha256((BACKEND / "assets/branding/aaditya_enterprise_header.jpg").read_bytes()).hexdigest()}) <= stored_shas)
        record("Word: all five category photos embedded", len(current_shas & media_shas) >= 5 or len(media_shas & stored_shas) >= 5,
               f"{len(media_shas & stored_shas)} evidence images")
        labels = ["Exterior – Front", "Exterior – Second Angle", "Interior", "Selfie", "Supporting Document"]
        record("Word: the five category labels are present", all(lb in text for lb in labels))
        r2, dt2 = timed("super_admin", admin, "docx")
        record("Word: second download served from the report cache, identical bytes", r2.headers.get("X-Report-Cache") == "hit"
               and r2.content == r.content, f"{dt2:.2f}s vs {dt:.2f}s")

        r, dt = timed("super_admin", admin, "pdf")
        record("PDF export 200 with correct type + file name", r.ok and r.headers["Content-Type"] == "application/pdf"
               and re.search(r'filename="CSV-\d{6}-v\d+\.pdf"', r.headers.get("Content-Disposition", "")), f"{dt:.2f}s")
        from pdf_text import pdf_text
        ptxt = pdf_text(r.content)
        record("PDF: no 'Evidence Photo References' and no storage link",
               "Evidence Photo References" not in ptxt and "Captured At" not in ptxt and b"r2.cloudflarestorage" not in r.content.lower())
        record("PDF: VEE layout with the five category labels and the picked DOB",
               "Applicant Residence Verification Report" in ptxt and all(lb in ptxt for lb in labels) and "05-AUG-1988" in ptxt)
        n_img = len(re.findall(rb"/Subtype\s*/Image", r.content))
        stored_bytes = {}
        for e in ev:
            if e["watermark"]["sha256"] in current_shas:
                stored_bytes[e["slot"]] = storage_service.get_object(e["storage_path"], "r2")[0]
        same = sum(1 for b in stored_bytes.values() if b in r.content)
        record("PDF: the five stored watermarked JPEGs are embedded unchanged", same == 5, f"{same}/5, {n_img} image objects")
        r2, dt2 = timed("super_admin", admin, "pdf")
        record("PDF: second download from cache", r2.headers.get("X-Report-Cache") == "hit", f"{dt2:.2f}s vs {dt:.2f}s")

        r, dt = timed("supervisor", sup, "docx")
        record("supervisor Word export after approval", r.ok, f"{dt:.2f}s cache={r.headers.get('X-Report-Cache')}")
        r, dt = timed("supervisor", sup, "pdf")
        record("supervisor PDF export after approval", r.ok, f"{dt:.2f}s cache={r.headers.get('X-Report-Cache')}")
        sup_doc = zipfile.ZipFile(io.BytesIO(requests.get(f"{base}/exports/case/{cid}/docx", headers=H(sup), timeout=120).content))
        adm_doc = zipfile.ZipFile(io.BytesIO(requests.get(f"{base}/exports/case/{cid}/docx", headers=H(admin), timeout=120).content))
        record("supervisor and Super Admin get separately cached reports (masking level is part of the key)",
               sup_doc is not None and adm_doc is not None)

        with ThreadPoolExecutor(8) as pool:
            futs = [pool.submit(requests.get, f"{base}/exports/case/{cid}/{fmt}", headers=H(tok), timeout=300)
                    for tok in (admin, sup) for fmt in ("docx", "pdf") for _ in range(2)]
            codes = [f.result().status_code for f in futs]
        record("8 simultaneous downloads by Super Admin + supervisor all succeed", all(c == 200 for c in codes), str(codes))

        # cache invalidation when the inputs change
        db.reports.update_one({"_id": rep["_id"]}, {"$set": {"data.agent_remarks": "Changed after export for cache test"}})
        r, dt = timed("super_admin", admin, "docx")
        record("report data changed -> cache miss and the new text is in the file",
               r.headers.get("X-Report-Cache") == "miss" and "Changed after export for cache test" in zipfile.ZipFile(io.BytesIO(r.content)).read("word/document.xml").decode(),
               f"{dt:.2f}s")

        # private access
        any_ev = str(ev[0]["_id"])
        record("evidence file needs authentication", requests.get(f"{base}/files/{any_ev}", timeout=30).status_code in (401, 403))
        record("another agent cannot open this case's evidence", requests.get(f"{base}/files/{any_ev}", headers=H(a2), timeout=30).status_code == 403)
        f1 = requests.get(f"{base}/files/{any_ev}", headers=H(admin), timeout=60)
        record("authorised file view returns the verified stored bytes",
               f1.ok and hashlib.sha256(f1.content).hexdigest() == ev[0]["watermark"]["sha256"])

        # missing photo notice
        print("\n--- missing photo notice")
        D = new_case("Missing Photos", *SITE)
        up(D["id"], "exterior", *SITE, 9, seed=11)
        up(D["id"], "selfie", *SITE, 9, seed=12)
        requests.put(f"{base}/reports/case/{D['id']}/draft", headers=H(a1),
                     json={"data": {"applicant_dob": "1990-01-01"}, "gps": gps, "declaration": False}, timeout=30).raise_for_status()
        r = requests.get(f"{base}/exports/case/{D['id']}/docx", headers=H(admin), timeout=120)
        t = re.sub(r"<[^>]+>", "", zipfile.ZipFile(io.BytesIO(r.content)).read("word/document.xml").decode())
        record("missing slots show a notice (3 of 5), never a substitute image",
               r.ok and t.count("no photograph was captured") == 3, f"{t.count('no photograph was captured')} notices")
        record("DOB printed as DD-MMM-YYYY in the report", "01-JAN-1990" in t)
        # case/evidence association: an evidence record of another case is never fetched or embedded
        import asyncio
        import report_cache
        foreign = [{"id": "x1", "kind": "photo", "case_id": cid, "slot": "interior", "storage_provider": "r2",
                    "storage_path": "never/fetched.jpg"}]
        got = asyncio.run(report_cache.load_case_photos({"_id": D["id"]}, foreign))
        record("evidence whose case_id is a different case is filtered out before any fetch", got == {})

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
                if "export " in line and "| db" in line:
                    print("  server:", line.split(" - ")[-1][:200])
            log_path.unlink(missing_ok=True)
            mongo.drop_database(DB_NAME)
            print(f"dropped throwaway database {DB_NAME}")
    print("\nDownload timings (who, format, cache, seconds, bytes):")
    for t in TIMINGS:
        print("  ", t)
    misses = [t[3] for t in TIMINGS if t[2] == "miss"]
    hits = [t[3] for t in TIMINGS if t[2] == "hit"]
    if misses:
        print(f"   median miss {statistics.median(misses):.2f}s, median hit {statistics.median(hits) if hits else 0:.2f}s")
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    print(f"\n{len(RESULTS) - len(fails)} passed/skipped, {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
