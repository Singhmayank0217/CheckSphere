"""Isolated verification: Super Admin manages clients and branches; Supervisors and Agents cannot (server-side checks).

SAFE BY CONSTRUCTION: own backend on a free port against a throwaway LOCAL MongoDB (demo seeding is allowed only
there), dropped at the end. No storage is used.

Run from the repo root:  .venv\\Scripts\\python.exe backend\\tests\\verify_clients_branches.py
"""
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
from openpyxl import Workbook
from pymongo import MongoClient

BACKEND = Path(__file__).resolve().parents[1]
DB_NAME = f"checksphere_verify_{uuid.uuid4().hex[:8]}"
LOCAL = "mongodb://localhost:27017"
RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append("PASS" if ok else "FAIL")
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


def main() -> int:
    env = {**os.environ, **{k: v for k, v in dotenv_values(BACKEND / ".env").items() if v},
           "MONGO_URL": LOCAL, "DB_NAME": DB_NAME, "SEED_DEMO_DATA": "true", "APP_ENV": "verify", "MEDIA_FOLDER_ENV": "verify",
           "GEOCODING_PROVIDER": "off",
           "R2_BUCKET": "", "BACKUP_DIR": str(Path(os.environ.get("TEMP", ".")) / DB_NAME)}
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    log = open(Path(os.environ.get("TEMP", ".")) / f"{DB_NAME}.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT)
    api = f"http://127.0.0.1:{port}/api"
    db = MongoClient(LOCAL)[DB_NAME]
    try:
        for _ in range(60):
            try:
                if requests.get(f"http://127.0.0.1:{port}/health", timeout=2).ok:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        time.sleep(2)

        def login(ident, pw, new_pw=None):
            j = requests.post(f"{api}/auth/login", json={"identifier": ident, "password": pw}, timeout=30).json()
            if j.get("must_change_password") and new_pw:
                requests.post(f"{api}/auth/change-password", headers={"Authorization": f"Bearer {j['access_token']}"},
                              json={"current_password": pw, "new_password": new_pw}, timeout=30).raise_for_status()
            return {"Authorization": f"Bearer {j['access_token']}"}, j["user"]

        A, _ = login("admin@checksphere.app", "Admin@12345")
        S, _ = login("sup1@checksphere.app", "Super@12345", "Verify@Sup1xx")
        G, gu = login("AGT101", "Agent@12345", "Verify@Agent1x")

        # ---- Super Admin: full management
        c = requests.post(f"{api}/clients", headers=A, json={"name": "Test Bank One", "code": "TB1"}, timeout=30)
        cid = c.json().get("id")
        record("Super Admin creates a client", c.ok and cid, f"HTTP {c.status_code}")
        dup = requests.post(f"{api}/clients", headers=A, json={"name": "test bank one"}, timeout=30)
        record("duplicate client name (any case) refused", dup.status_code == 400)
        e = requests.put(f"{api}/clients/{cid}", headers=A, json={"name": "Test Bank One Ltd", "code": "TB1L"}, timeout=30)
        record("Super Admin edits client details", e.ok and e.json()["name"] == "Test Bank One Ltd" and e.json()["code"] == "TB1L")
        b = requests.post(f"{api}/branches", headers=A, json={"client_id": cid, "name": "Belur Branch", "city": "Howrah",
                                                              "state": "West Bengal"}, timeout=30)
        bid = b.json().get("id")
        record("Super Admin creates a branch under the selected client", b.ok and b.json()["client_id"] == cid)
        bdup = requests.post(f"{api}/branches", headers=A, json={"client_id": cid, "name": "belur branch"}, timeout=30)
        record("duplicate branch name within the client refused", bdup.status_code == 400)
        be = requests.put(f"{api}/branches/{bid}", headers=A, json={"name": "Belur Main", "city": "Belur"}, timeout=30)
        record("Super Admin edits branch details", be.ok and be.json()["name"] == "Belur Main" and be.json()["city"] == "Belur"
               and be.json()["state"] == "West Bengal")
        b2 = requests.post(f"{api}/branches", headers=A, json={"client_id": cid, "name": "Second Branch"}, timeout=30).json()

        # deactivate branch, then client
        d1 = requests.post(f"{api}/branches/{b2['id']}/set-active", headers=A, json={"active": False}, timeout=30)
        sup_br = [x["id"] for x in requests.get(f"{api}/branches", headers=S, timeout=30).json()["items"]]
        adm_br = [x["id"] for x in requests.get(f"{api}/branches?include_inactive=true", headers=A, timeout=30).json()["items"]]
        record("Super Admin deactivates a branch; hidden from others, visible to Super Admin",
               d1.ok and d1.json()["active"] is False and b2["id"] not in sup_br and bid in sup_br and b2["id"] in adm_br)
        d2 = requests.post(f"{api}/clients/{cid}/set-active", headers=A, json={"active": False}, timeout=30)
        sup_cl = [x["id"] for x in requests.get(f"{api}/clients", headers=S, timeout=30).json()["items"]]
        sup_cl_inc = [x["id"] for x in requests.get(f"{api}/clients?include_inactive=true", headers=S, timeout=30).json()["items"]]
        adm_cl = [x["id"] for x in requests.get(f"{api}/clients?include_inactive=true", headers=A, timeout=30).json()["items"]]
        sup_br2 = [x["id"] for x in requests.get(f"{api}/branches", headers=S, timeout=30).json()["items"]]
        record("Super Admin deactivates a client; its branches leave the lists too",
               d2.ok and cid not in sup_cl and bid not in sup_br2 and cid in adm_cl)
        record("include_inactive is ignored for a Supervisor", cid not in sup_cl_inc)
        nb = requests.post(f"{api}/branches", headers=A, json={"client_id": cid, "name": "Blocked"}, timeout=30)
        record("no new branch under a deactivated client", nb.status_code == 400)
        case_body = {"client_case_id": f"CB-{uuid.uuid4().hex[:5]}", "client_id": cid, "branch_id": bid, "applicant_name": "X",
                     "report_type": "residence_applicant", "assigned_address": "Addr", "primary_phone": "9000000000"}
        nc = requests.post(f"{api}/cases", headers=A, json=case_body, timeout=30)
        record("new case with a deactivated client refused", nc.status_code == 400 and "deactivated" in nc.text, nc.text[:100])
        # Excel import with the deactivated client is reported per row, not imported
        wb = Workbook(); ws = wb.active
        tpl = requests.get(f"{api}/cases/import-template", headers=A, timeout=30)
        from openpyxl import load_workbook
        hdr = [c_.value for c_ in next(load_workbook(io.BytesIO(tpl.content)).active.iter_rows(min_row=1, max_row=1))]
        ws.append(hdr)
        row = {h: "" for h in hdr}
        row.update({k: v for k, v in {"Client Name": "Test Bank One Ltd", "Applicant Name": "Imp", "Report Type": "Residence Verification",
                                       "Assigned Address": "Addr", "Primary Contact Number": "9000000000"}.items() if k in row})
        ws.append([row[h] for h in hdr]); buf = io.BytesIO(); wb.save(buf)
        imp = requests.post(f"{api}/cases/import", headers=A, files={"file": ("i.xlsx", buf.getvalue(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}, timeout=60)
        record("Excel import refuses rows for a deactivated client", imp.ok and "deactivated" in imp.text and
               db.cases.count_documents({"client_id": cid}) == 0, imp.text[:160])
        # reactivate
        r1 = requests.post(f"{api}/clients/{cid}/set-active", headers=A, json={"active": True}, timeout=30)
        r2 = requests.post(f"{api}/branches/{b2['id']}/set-active", headers=A, json={"active": True}, timeout=30)
        nc2 = requests.post(f"{api}/cases", headers=A, json=case_body, timeout=30)
        record("Super Admin reactivates client and branch; new case accepted again", r1.ok and r2.ok and nc2.ok, f"HTTP {nc2.status_code}")
        other = requests.post(f"{api}/clients", headers=A, json={"name": "Other Bank"}, timeout=30).json()
        mism = requests.post(f"{api}/cases", headers=A, json={**case_body, "client_case_id": "CB-MIS", "client_id": other["id"]}, timeout=30)
        record("branch from a different client refused for a new case", mism.status_code == 400)
        bad = requests.put(f"{api}/clients/not-an-id", headers=A, json={"name": "x"}, timeout=30)
        record("malformed id answers 404 (not a server error)", bad.status_code == 404)
        audits = {a["action"] for a in db.audit_logs.find({"action": {"$regex": "^(client|branch)_"}})}
        record("every change is audited", {"client_created", "client_updated", "client_deactivated", "client_activated",
                                           "branch_created", "branch_updated", "branch_deactivated", "branch_activated"} <= audits,
               str(sorted(audits)))

        # ---- Supervisor and Agent: read only (server refuses every write)
        for who, H in (("Supervisor", S), ("Agent", G)):
            codes = [
                requests.post(f"{api}/clients", headers=H, json={"name": f"{who} Bank"}, timeout=30).status_code,
                requests.put(f"{api}/clients/{cid}", headers=H, json={"name": "Hacked"}, timeout=30).status_code,
                requests.post(f"{api}/clients/{cid}/set-active", headers=H, json={"active": False}, timeout=30).status_code,
                requests.post(f"{api}/branches", headers=H, json={"client_id": cid, "name": f"{who} Br"}, timeout=30).status_code,
                requests.put(f"{api}/branches/{bid}", headers=H, json={"name": "Hacked"}, timeout=30).status_code,
                requests.post(f"{api}/branches/{bid}/set-active", headers=H, json={"active": False}, timeout=30).status_code,
                requests.delete(f"{api}/clients/{cid}", headers=H, timeout=30).status_code,
                requests.delete(f"{api}/branches/{bid}", headers=H, timeout=30).status_code,
            ]
            record(f"{who}: create/edit/deactivate/delete of clients and branches all refused", all(c_ in (403, 405) for c_ in codes[:6])
                   and all(c_ in (403, 404, 405) for c_ in codes[6:]), str(codes))
            reads = requests.get(f"{api}/clients", headers=H, timeout=30).ok and requests.get(f"{api}/branches", headers=H, timeout=30).ok
            record(f"{who}: can still read active clients and branches (needed for case forms)", reads)
        unchanged = db.clients.find_one({"name": "Test Bank One Ltd", "active": True}) and db.branches.find_one({"_id": __import__("bson").ObjectId(bid), "name": "Belur Main", "active": True})
        record("nothing was changed by the refused attempts", bool(unchanged))
        noauth = requests.post(f"{api}/clients", json={"name": "Anon"}, timeout=30)
        record("no token -> refused", noauth.status_code in (401, 403))
        record("no delete endpoint exists (deactivate instead)", requests.delete(f"{api}/clients/{cid}", headers=A, timeout=30).status_code == 405)
    finally:
        proc.terminate()
        proc.wait(20)
        log.close()
        MongoClient(LOCAL).drop_database(DB_NAME)
        print("cleanup: throwaway DB dropped")
    print(f"\nSUMMARY: {RESULTS.count('PASS')} pass, {RESULTS.count('FAIL')} fail")
    return 1 if "FAIL" in RESULTS else 0


if __name__ == "__main__":
    sys.exit(main())
