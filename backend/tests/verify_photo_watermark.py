"""Isolated verification: camera photo formats + GPS address watermark + original/watermarked storage.

SAFE BY CONSTRUCTION: own backend on a free port, throwaway LOCAL MongoDB (dropped at the end), synthetic images only
(uploaded to the R2 test bucket under checksphere/verify/... and all deleted). Reverse geocoding uses the live provider with
coordinates only (public sample coordinates), exactly as production does.

Run from the repo root:  .venv\\Scripts\\python.exe backend\\tests\\verify_photo_watermark.py
"""
import hashlib
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
from dotenv import dotenv_values
from PIL import Image, ImageDraw, ImageStat
from pymongo import MongoClient

import r2_test_utils

BACKEND = Path(__file__).resolve().parents[1]
LOCAL_MONGO = os.environ.get("VERIFY_LOCAL_MONGO", "mongodb://localhost:27017")
DB_NAME = f"checksphere_verify_{uuid.uuid4().hex[:8]}"
PIN = (22.623888, 88.353012)   # sample coordinates from the requirement (Kolkata)
RESULTS = []
IST = timezone(timedelta(hours=5, minutes=30))


def record(name, ok, detail=""):
    status = "SKIP" if ok is None else ("PASS" if bool(ok) else "FAIL")
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name} {detail}", flush=True)


def scene(w, h, seed, light=True):
    img = Image.new("RGB", (w, h), (236, 232, 224) if light else (36, 52, 70))
    d = ImageDraw.Draw(img)
    r = abs(hash(seed))
    for i in range(0, w, 50):
        d.rectangle([i, h // 3, i + 25, h], fill=((r + i) % 200, 90, 60))
    d.ellipse([w // 2 - w // 6, h // 4 - w // 6, w // 2 + w // 6, h // 4 + w // 6], fill=(210, 170, 140))
    return img


def encode(img, fmt, **kw):
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def camera_jpeg_rotated(seed):
    """Like many Android cameras: pixels stored landscape + EXIF Orientation=6 (display rotated 90°)."""
    img = scene(1600, 1200, seed)
    exif = Image.Exif()
    exif[0x0112] = 6
    return encode(img, "JPEG", quality=90, exif=exif.tobytes())


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
        case = requests.post(f"{base}/cases", headers=H(admin), json={
            "client_case_id": f"WMTEST-{uuid.uuid4().hex[:6].upper()}", "client_id": clients[0]["id"], "applicant_name": "Watermark Test",
            "report_type": "residence_applicant", "assigned_address": "ASSIGNED ADDRESS TEXT 123", "primary_phone": "9000000000",
            "assigned_lat": PIN[0], "assigned_lon": PIN[1]}, timeout=30).json()
        cid = case["id"]
        requests.post(f"{base}/cases/{cid}/assign", headers=H(admin), json={"agent_id": a1u["id"]}, timeout=30).raise_for_status()

        def up(slot, data, name="capture.jpg", ctype="image/jpeg", lat=PIN[0] + 0.0004, lon=PIN[1] + 0.0003, acc=7.5,
               captured=None, extra=None, token=a1):
            f = {"case_id": cid, "slot": slot, "kind": "photo", "captured_at": (captured or datetime.now(timezone.utc)).isoformat()}
            if lat is not None:
                f.update({"lat": str(lat), "lon": str(lon), "accuracy": str(acc), "gps_status": "ok"})
            f.update(extra or {})
            return requests.post(f"{base}/evidence/upload", headers=H(token), data=f, files={"file": (name, data, ctype)}, timeout=180)

        # ---------------- the device bug, reproduced: the 404 body that used to be uploaded as the photo
        r = up("exterior", b"File not found", name="capture-1.jpg")
        record("old device bug reproduced: 'File not found' body uploaded as .jpg -> 400 rejected", r.status_code == 400, str(r.status_code))
        logtxt = log_path.read_text(encoding="utf-8", errors="replace")
        record("server logs a diagnostic for rejected photos (size + first bytes, no content)",
               "not a decodable photo" in logtxt and "46696c65206e6f7420666f756e64"[:16] in logtxt)
        r = up("exterior", encode(Image.new("RGB", (10, 10)), "JPEG")[:40], name="truncated.jpg")
        record("truncated/corrupt JPEG rejected", r.status_code == 400)
        r = up("exterior", b"%PDF-1.4 not a photo", name="x.jpg")
        record("PDF disguised as photo rejected", r.status_code == 400)

        # ---------------- formats
        evs = {}
        fmts = {
            "JPEG (camera, EXIF-rotated)": ("exterior", camera_jpeg_rotated("a"), "image/jpeg"),
            "PNG": ("exterior_2", encode(scene(1200, 900, "b"), "PNG"), "image/png"),
            "WebP": ("interior", encode(scene(1200, 900, "c", light=False), "WEBP", quality=85), "image/webp"),
        }
        try:
            import pillow_heif  # noqa: F401
            pillow_heif.register_heif_opener()
            fmts["HEIC"] = ("selfie", encode(scene(1080, 1440, "d", light=False), "HEIF", quality=85), "application/octet-stream")
        except Exception as exc:
            record("HEIC encode for test", None, f"SKIPPED: {exc}")
        fmts["JPEG (document)"] = ("document", encode(scene(1240, 1754, "e"), "JPEG", quality=92), "image/jpeg")
        shot_time = datetime.now(timezone.utc) - timedelta(hours=3, minutes=7)  # offline capture uploaded later
        for label, (slot, data, ctype) in fmts.items():
            r = up(slot, data, ctype=ctype, captured=shot_time if slot == "exterior" else None,
                   extra={"upload_id": f"wm-{slot}-{uuid.uuid4().hex[:8]}"})
            ok = r.status_code == 200
            record(f"{label} -> accepted, stored as watermarked JPEG + original", ok and r.json()["mime"] == "image/jpeg"
                   and r.json()["original"]["sha256"] == hashlib.sha256(data).hexdigest(), "" if ok else r.text[:200])
            if ok:
                evs[slot] = (r.json(), data)

        # ---------------- watermark content + placement, all five slots
        lines_all = []
        for slot, (ev, orig_bytes) in evs.items():
            g = requests.get(f"{base}/files/{ev['id']}", headers=H(a1), timeout=60)
            img = Image.open(io.BytesIO(g.content))
            img.load()
            wm = ev["watermark"]
            printed = wm["printed_lines"]
            lines_all += printed
            text = " | ".join(wm["lines"])
            record(f"[{slot}] download opens as JPEG, sha256 matches stored watermarked checksum",
                   g.ok and img.format == "JPEG" and hashlib.sha256(g.content).hexdigest() == wm["sha256"])
            x0, y0, bw, bh = wm["box"]
            W, Hh = img.size
            record(f"[{slot}] watermark box is in the bottom-right, inside the image, not full width",
                   x0 > W * 0.3 and y0 > Hh * 0.5 and x0 + bw <= W and y0 + bh <= Hh and bw < W * 0.7, f"box {wm['box']} on {W}x{Hh}")
            box_l = ImageStat.Stat(img.crop((x0 + bw // 4, y0 + bh // 4, x0 + bw - 4, y0 + bh - 4)).convert("L")).mean[0]
            record(f"[{slot}] box is dark with light text pixels (readable)", box_l < 110, f"mean luminance {box_l:.0f}")
            record(f"[{slot}] lines: CHECKSPHERE / date|time IST / Latitude / Longitude / Address / Photo",
                   wm["lines"][0] == "CHECKSPHERE" and wm["lines"][1].endswith("IST") and wm["lines"][2].startswith("Latitude: ")
                   and wm["lines"][3].startswith("Longitude: ") and wm["lines"][4].startswith("Address") and wm["lines"][5].startswith("Photo: "))
            record(f"[{slot}] lat/lon printed = stored GPS (6 dp)",
                   wm["lines"][2] == f"Latitude: {ev['gps']['lat']:.6f}" and wm["lines"][3] == f"Longitude: {ev['gps']['lon']:.6f}")
            cap = datetime.fromisoformat(ev["captured_at"])
            record(f"[{slot}] printed time = stored capture time in IST", wm["lines"][1] == cap.astimezone(IST).strftime("%d-%b-%Y | %I:%M:%S %p IST"),
                   wm["lines"][1])
            forbidden = ["accuracy", "±", case["internal_case_id"].lower(), case["client_case_id"].lower(), "captured gps location", "location:"]
            record(f"[{slot}] no accuracy / case reference / generic location text printed",
                   not any(f in text.lower() for f in forbidden), text[:160])
            record(f"[{slot}] accuracy + case id still kept in MongoDB", ev["gps"]["accuracy"] == 7.5 and ev["case_id"] == cid)
            if slot in ("selfie", "document"):
                ow, oh = wm["image_size"][0], None
                orig_img = Image.open(io.BytesIO(orig_bytes))
                record(f"[{slot}] watermark in an added strip below the photo (face/document never covered)",
                       wm["band"] and img.size[1] > orig_img.size[1] and y0 >= orig_img.size[1])
            else:
                record(f"[{slot}] same dimensions as the photo (no stretching/cropping)", not wm["band"])
        ev_ext = evs.get("exterior", (None,))[0]
        if ev_ext:
            img = Image.open(io.BytesIO(requests.get(f"{base}/files/{ev_ext['id']}", headers=H(a1), timeout=60).content))
            record("EXIF rotation applied before watermarking (portrait output from rotated camera JPEG)", img.size[1] > img.size[0], str(img.size))
            record("offline capture: printed time is the shutter time, not the upload time",
                   ev_ext["watermark"]["lines"][1] == shot_time.astimezone(IST).strftime("%d-%b-%Y | %I:%M:%S %p IST"))
            pa = ev_ext["photo_address"]
            record("address = reverse geocode of the captured GPS (not the assigned case address)",
                   pa["status"] in ("resolved", "approximate") and pa["text"] and "ASSIGNED ADDRESS" not in pa["text"]
                   and pa["text"] in ev_ext["watermark"]["lines"][4], f"{pa['status']}: {pa['text']}")
        record("photo categories printed", sorted(l for l in lines_all if l.startswith("Photo: ")) ==
               sorted(f"Photo: {t}" for t, s_ in (("Exterior – Front", "exterior"), ("Exterior – Second Angle", "exterior_2"),
                                                     ("Interior", "interior"), ("Selfie", "selfie"), ("Supporting Document", "document")) if s_ in evs))

        # ---------------- address unavailable (open ocean) -> "Address unavailable", coordinates kept
        r = up("interior", encode(scene(900, 900, "f"), "JPEG"), lat=-10.0, lon=-30.0, extra={"location_reason": "test: open sea point"})
        if r.ok:
            ev = r.json()
            created = ev
            record("no address found -> 'Address unavailable' printed, coordinates kept",
                   ev["watermark"]["lines"][4] == "Address unavailable" and ev["watermark"]["lines"][2] == "Latitude: -10.000000"
                   and ev["photo_address"]["status"] == "unavailable", ev["photo_address"].get("reason", ""))
            record("distance flag still applied (far photo needs reason, flagged)", "photo_far_from_assigned" in ev["flags"])
        # GPS unavailable -> coordinates "Not available", address unavailable
        r = up("interior", encode(scene(900, 900, "g"), "JPEG"), lat=None, extra={"gps_status": "timeout", "location_reason": "test: no fix"})
        record("GPS unavailable -> 'Not available' lat/lon + 'Address unavailable'", r.ok and r.json()["watermark"]["lines"][2] == "Latitude: Not available"
               and r.json()["watermark"]["lines"][4] == "Address unavailable")
        # approximate wording (unit level, deterministic)
        import watermark as wmod  # noqa: E402
        ln = wmod.watermark_lines(datetime.now(timezone.utc), 1.0, 2.0, {"text": "Some Town, State", "status": "approximate"}, "interior")
        record("approximate address is labelled as approximate", ln[4] == "Address (approximate): Some Town, State")

        # ---------------- security / integrity
        ev0 = next(iter(evs.values()))[0]
        import r2_storage  # noqa: E402
        for which, path in (("watermarked", ev0["storage_path"]), ("original", ev0["original"]["storage_path"])):
            code = r2_test_utils.unsigned_status(path)
            record(f"{which} object private: unsigned R2 request denied", code in (400, 401, 403), str(code))
        head = r2_storage.head_object(ev0["storage_path"])
        record("watermarked object stored in private R2 with its checksum", bool(head)
               and head["metadata"].get("sha256") == ev0["watermark"]["sha256"])
        record("other agent cannot download -> 403", requests.get(f"{base}/files/{ev0['id']}", headers=H(a2), timeout=30).status_code == 403)
        record("no token -> 401", requests.get(f"{base}/files/{ev0['id']}", timeout=30).status_code == 401)
        o = requests.get(f"{base}/files/{ev0['id']}?variant=original", headers=H(sup), timeout=60)
        record("supervisor can download untouched original (sha256 matches device bytes)",
               o.ok and hashlib.sha256(o.content).hexdigest() == ev0["original"]["sha256"] == ev0["sha256"])
        record("agent cannot download the unwatermarked original", requests.get(f"{base}/files/{ev0['id']}?variant=original", headers=H(a1), timeout=30).status_code == 403)

        # retry with the same upload_id -> no duplicate record and no extra stored files
        uid = "wm-retry-" + uuid.uuid4().hex[:8]
        data = encode(scene(800, 600, "h"), "JPEG")
        r1 = up("exterior_2", data, extra={"upload_id": uid})
        before = len(r2_test_utils.list_keys(f"checksphere/verify/evidence/{cid}/"))
        r2 = up("exterior_2", data, extra={"upload_id": uid})
        after = len(r2_test_utils.list_keys(f"checksphere/verify/evidence/{cid}/"))
        record("retry same upload_id -> same evidence, no new stored files", r1.ok and r2.ok and r1.json()["id"] == r2.json()["id"]
               and before == after and db.evidence.count_documents({"upload_id": uid}) == 1, f"assets {before}->{after}")
        stored_doc = db.evidence.find_one({"upload_id": uid})
        record("retry keeps original capture metadata unchanged", stored_doc["captured_at"].isoformat()[:19] == r1.json()["captured_at"][:19])
        record("metadata complete (original+watermarked checksums, address, gps, upload id, storage details)",
               all(k in stored_doc for k in ("original", "watermark", "photo_address", "gps", "upload_id", "storage", "received_at", "captured_at", "agent_id", "slot"))
               and stored_doc["storage_provider"] == "r2" and stored_doc["original"]["storage"]["provider"] == "r2")
        record("no endpoint to edit evidence GPS/time/watermark", requests.patch(f"{base}/evidence/{ev0['id']}", headers=H(a1), json={}, timeout=30).status_code in (404, 405))

        # submission still requires all five
        rc = requests.get(f"{base}/reports/case/{cid}", headers=H(a1), timeout=30).json()
        have = {e["slot"] for e in rc["evidence"]}
        record("all five slots have uploaded photos via the same pipeline", {"exterior", "exterior_2", "interior", "selfie", "document"} <= have
               if "selfie" in evs else None)
    finally:
        try:
            left = 0
            paths = []
            for e in db.evidence.find({"storage_provider": "r2"}):
                paths.append(e["storage_path"])
                if (e.get("original") or {}).get("storage_path"):
                    paths.append(e["original"]["storage_path"])
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
