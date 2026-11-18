"""Isolated verification of test_data_cleanup.py (inventory -> approved manifest -> execute -> verify).

SAFE BY CONSTRUCTION: throwaway LOCAL MongoDB (dropped at the end); files only under
checksphere/verify-cleanup-<run>/ in the R2 TEST bucket; a temporary local backups folder.
Control files just OUTSIDE that folder prove nothing else is touched; they are removed at the end.
The real Atlas database and backend/backups are never used.

Run from the repo root:  .venv\\Scripts\\python.exe backend\\tests\\verify_cleanup.py
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from PIL import Image
from pymongo import MongoClient

BACKEND = Path(__file__).resolve().parents[1]
RUN = uuid.uuid4().hex[:8]
DB_NAME = f"checksphere_verify_{RUN}"
PREFIX = f"checksphere/verify-cleanup-{RUN}/"
CONTROL = f"checksphere/verify-cleanup-{RUN}-control/"
TMP = Path(tempfile.gettempdir()) / DB_NAME
RESULTS = []


def record(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    RESULTS.append(status)
    print(f"[{status}] {name} {detail}", flush=True)


def jpeg(seed):
    b = io.BytesIO()
    Image.new("RGB", (64, 64), (hash(seed) % 255, 90, 60)).save(b, "JPEG")
    return b.getvalue()


def main() -> int:
    env_file = {k: v for k, v in dotenv_values(BACKEND / ".env").items() if v}
    if "test" not in (env_file.get("R2_BUCKET") or ""):
        print("R2_BUCKET must be the test bucket")
        return 2
    env = {**os.environ, **env_file, "MONGO_URL": "mongodb://localhost:27017", "DB_NAME": DB_NAME, "CLEANUP_PREFIX": PREFIX,
           "CLEANUP_DIR": str(TMP / "manifests"), "CLEANUP_BACKUP_DIR": str(TMP / "backups"), "MEDIA_FOLDER_ENV": f"verify-cleanup-{RUN}"}
    os.environ.update({k: v for k, v in env.items() if k.startswith("R2_")})
    sys.path.insert(0, str(BACKEND))
    import r2_storage
    db = MongoClient("mongodb://localhost:27017")[DB_NAME]
    (TMP / "backups").mkdir(parents=True, exist_ok=True)
    r2_keys = []
    try:
        # ---- throwaway data
        now = datetime.now(timezone.utc)
        admin = db.users.insert_one({"role": "super_admin", "email": "realadmin@example.test", "name": "Keep Admin"}).inserted_id
        db.users.insert_one({"role": "agent", "email": "demo-agent@example.test", "agent_id": "DEMO1", "name": "Delete Me"})
        db.settings.insert_one({"_id": "app", "value": {"company_name": "CheckSphere", "retention_days": 3650}})
        db.clients.insert_one({"name": "Demo Client"})
        db.branches.insert_one({"name": "Demo Branch"})
        db.counters.insert_many([{"_id": "case_seq", "seq": 27}, {"_id": "agent_id", "seq": 102}])
        case = db.cases.insert_one({"internal_case_id": "CSV-1", "status": "assigned", "created_at": now}).inserted_id
        for i in range(4):
            k = f"{PREFIX}evidence/{case}/r{i}.jpg"
            r2_storage.put_object(k, jpeg(f"r{i}"), "image/jpeg")
            r2_keys.append(k)
        ctrl_r = f"{CONTROL}keep.jpg"
        r2_storage.put_object(ctrl_r, jpeg("ctrl"), "image/jpeg")
        db.evidence.insert_many([
            {"case_id": str(case), "storage_provider": "r2", "storage_path": r2_keys[0],
             "original": {"storage_path": r2_keys[1], "storage_provider": "r2"}},
            {"case_id": str(case), "storage_provider": "r2", "storage_path": r2_keys[2],
             "original": {"storage_path": r2_keys[3], "storage_provider": "r2"}}])
        db.reports.insert_one({"case_id": str(case)})
        db.notifications.insert_one({"case_id": str(case)})
        db.sessions.insert_one({"user_id": str(admin)})
        db.sessions.insert_one({"_id": str(uuid.uuid4()), "user_id": str(admin)})  # sessions use text ids in the app
        db.audit_logs.insert_many([{"action": "x", "created_at": now} for _ in range(3)])
        (TMP / "backups" / "backup-20260101-000000.json").write_text("{}")
        (TMP / "backups" / "keep-me.txt").write_text("not a backup")

        def tool(*args):
            return subprocess.run([sys.executable, "test_data_cleanup.py", *args], cwd=BACKEND, env=env,
                                  capture_output=True, text=True, timeout=600)

        # ---- inventory (read-only)
        before = {c: db[c].count_documents({}) for c in db.list_collection_names()}
        inv = tool("--inventory", "--delete-users", "demo-agent@example.test", "--delete-clients", "--reset-case-counter",
                   "--clear-audit-logs")
        md = Path(inv.stdout.strip().splitlines()[-1]) if inv.returncode == 0 else None
        man = json.loads(md.with_suffix(".json").read_text()) if md else {}
        after_inv = {c: db[c].count_documents({}) for c in db.list_collection_names()}
        record("inventory runs and changes nothing", inv.returncode == 0 and before == after_inv, inv.stderr[-300:])
        d = man.get("delete", {})
        record("manifest lists exactly the test files in the folder (R2 4, backups 1)",
               len(d.get("r2", [])) == 4 and [b["file"] for b in d.get("local_backups", [])]
               == ["backup-20260101-000000.json"], "")
        record("control files outside the folder are not listed",
               all(not o["key"].startswith(CONTROL) for o in d["r2"]))
        record("manifest keeps settings, counters and the kept admin; deletes the demo user",
               "settings" in man["keep"]["collections"] and "counters" in man["keep"]["collections"]
               and [u["email"] for u in man["keep"]["users"]] == ["realadmin@example.test"] and len(d["mongodb"]["users"]) == 1)

        # ---- execute guards
        no_confirm = tool("--execute", str(md.with_suffix(".json")))
        record("execute refuses without --confirm-db and the confirmation phrase", no_confirm.returncode == 2)
        late = db.cases.insert_one({"internal_case_id": "CSV-LATE"}).inserted_id
        changed = tool("--execute", str(md.with_suffix(".json")), "--confirm-db", DB_NAME, "--confirm", "DELETE CHECKSPHERE TEST DATA")
        record("execute refuses when data changed after approval (nothing deleted)",
               changed.returncode != 0 and "Refusing" in (changed.stdout + changed.stderr) and db.cases.count_documents({}) == 2
               and r2_storage.head_object(r2_keys[0]) is not None)
        db.cases.delete_one({"_id": late})

        # ---- a cleanup that fails part-way (R2 deletion broken on purpose): the safety export must be KEPT
        fail_driver = ("import sys, r2_storage\n"
                       "_real = r2_storage.delete_object\n_n = [0]\n"
                       "def boom(*a, **k):\n    _n[0] += 1\n"
                       "    if _n[0] > 2:\n        raise RuntimeError('simulated R2 outage')\n    return _real(*a, **k)\n"
                       "r2_storage.delete_object = boom\n"
                       "import test_data_cleanup\n"
                       "sys.argv = ['test_data_cleanup.py'] + sys.argv[1:]\n"
                       "sys.exit(test_data_cleanup.main())\n")
        fail = subprocess.run([sys.executable, "-c", fail_driver, "--execute", str(md.with_suffix(".json")), "--confirm-db", DB_NAME,
                               "--confirm", "DELETE CHECKSPHERE TEST DATA"], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=600)
        kept = next((p for p in (TMP / "backups").glob("pre-cleanup-*")), None)
        exp = json.loads((kept / "mongodb.json").read_text()) if kept else {}
        files = [p for p in kept.rglob("*.jpg")] if kept else []
        record("failed cleanup stops with an error and KEEPS the safety export (documents + every file)",
               fail.returncode != 0 and "KEPT" in (fail.stdout + fail.stderr) and kept is not None
               and len(exp.get("evidence", [])) == 2 and len(files) == 4, (fail.stdout + fail.stderr)[-200:])
        record("failed cleanup keeps the manifest and deletes no database records",
               md.exists() and md.with_suffix(".json").exists() and db.cases.count_documents({}) == 1 and db.evidence.count_documents({}) == 2)
        retry_refused = tool("--execute", str(md.with_suffix(".json")), "--confirm-db", DB_NAME, "--confirm", "DELETE CHECKSPHERE TEST DATA")
        record("re-running the stale manifest is refused (two R2 objects already gone)", retry_refused.returncode != 0
               and "Refusing" in (retry_refused.stdout + retry_refused.stderr))

        # ---- fresh inventory, then the successful cleanup
        inv_b = tool("--inventory", "--delete-users", "demo-agent@example.test", "--delete-clients", "--reset-case-counter",
                     "--clear-audit-logs")
        md = Path(inv_b.stdout.strip().splitlines()[-1])
        man_b = json.loads(md.with_suffix(".json").read_text())
        record("new manifest lists the earlier kept safety export for removal",
               man_b["delete"]["earlier_safety_exports"] == [kept.name] and len(man_b["delete"]["r2"]) == 2)
        ex = tool("--execute", str(md.with_suffix(".json")), "--confirm-db", DB_NAME, "--confirm", "DELETE CHECKSPHERE TEST DATA")
        record("execute completes", ex.returncode == 0, (ex.stdout + ex.stderr)[-400:])
        empty = all(db[c].count_documents({}) == 0 for c in ("cases", "evidence", "reports", "notifications", "sessions", "clients", "branches"))
        record("test records deleted (cases, evidence, reports, notifications, sessions, clients, branches)", empty)
        record("settings intact, agent-id counter intact, case counter reset",
               db.settings.find_one({"_id": "app"})["value"]["company_name"] == "CheckSphere"
               and db.counters.find_one({"_id": "agent_id"})["seq"] == 102 and db.counters.find_one({"_id": "case_seq"})["seq"] == 0)
        record("kept admin remains, demo user removed",
               [u["email"] for u in db.users.find()] == ["realadmin@example.test"])
        record("audit log cleared except one 'test_data_cleared' entry",
               [a["action"] for a in db.audit_logs.find()] == ["test_data_cleared"])
        left_r = r2_storage.client().list_objects_v2(Bucket=r2_storage.bucket(), Prefix=PREFIX).get("KeyCount", 0)
        record("R2 files in the folder deleted", left_r == 0, f"r2 {left_r}")
        record("control files outside the folder untouched",
               r2_storage.get_object(ctrl_r) == jpeg("ctrl"))
        record("only backup-*.json removed from the backups folder",
               sorted(p.name for p in (TMP / "backups").iterdir() if p.is_file()) == ["keep-me.txt"])
        record("after verified success: every temporary safety export is deleted (this one and the earlier one)",
               "safety export written" in ex.stdout and not list((TMP / "backups").glob("pre-cleanup-*")))
        record("after verified success: the manifest naming the test users is deleted",
               not md.exists() and not md.with_suffix(".json").exists())
        res = sorted((TMP / "manifests").glob("cleanup-result-*.md"))
        txt = res[-1].read_text() if res else ""
        record("result report says VERIFIED and contains counts only (no names or emails)",
               "VERIFIED" in txt and "@" not in txt and "Delete Me" not in txt, res[-1].name if res else "")

        # ---- full wipe: every user deleted (fresh start for a new Super Admin)
        db.users.insert_one({"role": "agent", "email": "tester@example.test", "name": "Tester"})
        db.counters.update_one({"_id": "agent_id"}, {"$set": {"seq": 102}})
        guard = tool("--inventory", "--delete-users", "realadmin@example.test,tester@example.test")
        record("deleting every Super Admin by name is refused without --delete-all-users",
               guard.returncode != 0 and "Super Admin" in (guard.stdout + guard.stderr))
        inv2 = tool("--inventory", "--delete-all-users", "--reset-agent-counter")
        md2 = Path(inv2.stdout.strip().splitlines()[-1])
        man2 = json.loads(md2.with_suffix(".json").read_text())
        record("--delete-all-users lists every account and flags the Super Admin setup",
               len(man2["delete"]["mongodb"]["users"]) == 2 and man2["keep"]["users"] == []
               and man2["checks"]["super_admin_setup_required"] and "create_super_admin.py" in md2.read_text())
        ex2 = tool("--execute", str(md2.with_suffix(".json")), "--confirm-db", DB_NAME, "--confirm", "DELETE CHECKSPHERE TEST DATA")
        record("full wipe executes: no users left, agent counter reset, settings kept",
               ex2.returncode == 0 and db.users.count_documents({}) == 0 and db.counters.find_one({"_id": "agent_id"})["seq"] == 0
               and db.settings.count_documents({}) == 1, (ex2.stdout + ex2.stderr)[-300:])
        record("full wipe also leaves no safety export or manifest behind",
               not list((TMP / "backups").glob("pre-cleanup-*")) and not md2.exists() and not md2.with_suffix(".json").exists())
    finally:
        c = r2_storage.client()
        for pre in (PREFIX, CONTROL):
            for o in c.list_objects_v2(Bucket=r2_storage.bucket(), Prefix=pre).get("Contents", []):
                c.delete_object(Bucket=r2_storage.bucket(), Key=o["Key"])
        MongoClient("mongodb://localhost:27017").drop_database(DB_NAME)
        shutil.rmtree(TMP, ignore_errors=True)
        print("cleanup: throwaway DB dropped, test files and temp folder removed")
    print(f"\nSUMMARY: {RESULTS.count('PASS')} pass, {RESULTS.count('FAIL')} fail")
    return 1 if "FAIL" in RESULTS else 0


if __name__ == "__main__":
    sys.exit(main())
