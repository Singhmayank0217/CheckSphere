"""Isolated verification of create_super_admin.py and the demo-seeding lock.

SAFE BY CONSTRUCTION: throwaway LOCAL MongoDB only (dropped at the end). The test password is generated randomly
here for this throwaway database; it is never printed and is not the owner's password.

Run from the repo root:  .venv\\Scripts\\python.exe backend\\tests\\verify_superadmin_setup.py
"""
import json
import os
import secrets
import socket
import string
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests
from pymongo import MongoClient

BACKEND = Path(__file__).resolve().parents[1]
DB_NAME = f"checksphere_verify_{uuid.uuid4().hex[:8]}"
LOCAL = "mongodb://localhost:27017"
RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append("PASS" if ok else "FAIL")
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


# Runs create_super_admin.main() with scripted prompts (simulating the owner typing), as a separate process so the
# module reads this throwaway database. isatty is forced True: the real check is tested separately below.
DRIVER = r'''
import asyncio, getpass, json, sys
answers = json.loads(sys.argv[1]); pw = json.loads(sys.argv[2])
sys.stdin.isatty = lambda: True
it = iter(answers); pit = iter(pw)
import builtins
builtins.input = lambda prompt="": next(it)
getpass.getpass = lambda prompt="": next(pit)
import create_super_admin
rc = asyncio.run(create_super_admin.main())
create_super_admin.core.client.close()
sys.exit(rc)
'''


def main() -> int:
    env = {**os.environ, "MONGO_URL": LOCAL, "DB_NAME": DB_NAME, "SEED_DEMO_DATA": "false", "R2_BUCKET": "", "MEDIA_FOLDER_ENV": "verify",
           "BACKUP_DIR": str(Path(os.environ.get("TEMP", ".")) / DB_NAME)}
    db = MongoClient(LOCAL)[DB_NAME]
    alphabet = string.ascii_letters + string.digits
    test_pw = "".join(secrets.choice(alphabet) for _ in range(14)) + "7a"
    proc = None
    try:
        def drive(answers, pws):
            return subprocess.run([sys.executable, "-c", DRIVER, json.dumps(answers), json.dumps(pws)], cwd=BACKEND, env=env,
                                  capture_output=True, text=True, timeout=120)

        # 1. refuses without an interactive terminal (no echo fallback, nothing written)
        r = subprocess.run([sys.executable, "create_super_admin.py"], cwd=BACKEND, env=env, input="x\n", capture_output=True,
                           text=True, timeout=60)
        record("refuses when not run in an interactive terminal", r.returncode == 2 and "Refusing" in r.stdout
               and db.users.count_documents({}) == 0)
        # 2. wrong database name confirmation -> nothing written
        r = drive(["wrong-db"], [])
        record("refuses when the database name is not confirmed", r.returncode == 2 and db.users.count_documents({}) == 0)
        # 3. weak/demo passwords rejected, mismatched repeat rejected
        r = drive([DB_NAME, "owner@example.test", "Owner Name"], ["Admin@12345", "short1", test_pw, test_pw + "x"])
        record("demo, short and mismatched passwords rejected; nothing written after 3 tries",
               r.returncode == 2 and r.stdout.count("Password must have") == 2 and "differ" in r.stdout and db.users.count_documents({}) == 0)
        # 4. success
        r = drive([DB_NAME, "Owner@Example.test", "Owner Name"], [test_pw, test_pw])
        u = db.users.find_one({"role": "super_admin"})
        record("Super Admin created with the typed login email (lower-cased)", r.returncode == 0 and u and u["email"] == "owner@example.test",
               r.stdout[-200:])
        record("only a bcrypt hash is stored", u["password_hash"].startswith("$2") and test_pw not in json.dumps(u, default=str))
        logs = json.dumps(list(db.audit_logs.find({}, {"_id": 0})), default=str)
        record("audit entry written without the password", "super_admin_created" in logs and test_pw not in logs)
        record("the password never appears in the command's output", test_pw not in r.stdout + r.stderr)
        # 5. a second run is refused while a Super Admin exists
        r = drive([DB_NAME, "other@example.test", "X"], [test_pw, test_pw])
        record("refuses to create another Super Admin when one exists", r.returncode == 2 and db.users.count_documents({}) == 1)

        # 6. the new account can sign in through the real API; demo seeding is refused
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        log = open(Path(os.environ.get("TEMP", ".")) / f"{DB_NAME}.log", "w")
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)], cwd=BACKEND,
                                env={**env, "SEED_DEMO_DATA": "true", "APP_ENV": "prod", "GEOCODING_PROVIDER": "off"},
                                stdout=log, stderr=subprocess.STDOUT)
        for _ in range(60):
            try:
                if requests.get(f"http://127.0.0.1:{port}/health", timeout=2).ok:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        time.sleep(1)
        ok = requests.post(f"http://127.0.0.1:{port}/api/auth/login", json={"identifier": "owner@example.test", "password": test_pw,
                                                                         "expected_role": "super_admin"}, timeout=30)
        bad = requests.post(f"http://127.0.0.1:{port}/api/auth/login", json={"identifier": "admin@checksphere.app", "password": "Admin@12345"},
                            timeout=30)
        record("new Super Admin signs in on the Super Admin portal", ok.ok and ok.json()["user"]["role"] == "super_admin")
        record("demo login does not exist", bad.status_code == 401)
        record("SEED_DEMO_DATA=true with APP_ENV=prod: no demo accounts created",
               db.users.count_documents({}) == 1 and not db.users.find_one({"email": "admin@checksphere.app"}))
    finally:
        if proc:
            proc.terminate()
            proc.wait(20)
        MongoClient(LOCAL).drop_database(DB_NAME)
        print("cleanup: throwaway DB dropped")
    print(f"\nSUMMARY: {RESULTS.count('PASS')} pass, {RESULTS.count('FAIL')} fail")
    return 1 if "FAIL" in RESULTS else 0


if __name__ == "__main__":
    sys.exit(main())
