"""Create the first CheckSphere Super Admin, typed in by the owner on their own computer.

    cd backend
    ..\\.venv\\Scripts\\python.exe create_super_admin.py

* Run it yourself in PowerShell or Windows Terminal, not through Claude: you type the login email and the password
  at the prompts. The password is read with getpass (nothing is shown on screen) and asked twice.
* The password is never a command-line argument or environment variable (those end up in shell history and process
  lists), and is never printed, logged, written to a file, or sent anywhere except as a bcrypt hash to MongoDB.
* It refuses to run when the terminal cannot hide typing (some Git Bash/mintty windows), instead of echoing.
* It refuses when an active Super Admin already exists, so it cannot be used to take over a running system.
  Further users (supervisors, agents, other admins) are created in the web dashboard by this Super Admin.
* The database it writes to is the one in backend/.env (or the Railway variables with `railway run`); you confirm
  the database name before anything is written.
"""
import asyncio
import getpass
import os
import re
import sys
import warnings

import core
import security

MIN_LEN = 12
MAX_BYTES = 72  # bcrypt only uses the first 72 bytes
PUBLISHED = {"admin@12345", "super@12345", "agent@12345"}  # demo passwords published in seed.py
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def password_problems(pw: str, email: str) -> list[str]:
    p = []
    if len(pw) < MIN_LEN:
        p.append(f"at least {MIN_LEN} characters")
    if len(pw.encode()) > MAX_BYTES:
        p.append(f"at most {MAX_BYTES} bytes")
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        p.append("letters and at least one digit")
    if pw.lower() in PUBLISHED or "checksphere" in pw.lower():
        p.append("not a demo password and not containing 'checksphere'")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in pw.lower():
        p.append("not containing your login email name")
    if pw != pw.strip():
        p.append("no leading or trailing spaces")
    return p


def host_of(url: str) -> str:
    return url.split("@")[-1].split("/")[0].split("?")[0]


async def main() -> int:
    if not sys.stdin.isatty():
        print("Refusing: run this in an interactive terminal (PowerShell or Windows Terminal).")
        return 2
    db = core.db
    print(f"Database: {os.environ['DB_NAME']} on {host_of(core.mongo_url)}")
    existing = await db.users.count_documents({"role": "super_admin", "disabled": {"$ne": True}})
    if existing:
        print(f"Refusing: {existing} active Super Admin account(s) already exist. Create further users in the dashboard.")
        return 2
    if input("Type the database name to confirm: ").strip() != os.environ["DB_NAME"]:
        print("Not confirmed. Nothing was written.")
        return 2

    email = input("Super Admin login email: ").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 320:
        print("That is not a valid email address. Nothing was written.")
        return 2
    if await db.users.find_one({"email": email}):
        print("An account with that email already exists. Nothing was written.")
        return 2
    name = input("Full name (shown in the app and audit log): ").strip()[:120] or "Super Admin"

    warnings.simplefilter("error", getpass.GetPassWarning)  # never fall back to echoing the password
    try:
        for _ in range(3):
            pw = getpass.getpass(f"Password (min {MIN_LEN} characters, letters and digits; typing is hidden): ")
            problems = password_problems(pw, email)
            if problems:
                print("Password must have: " + "; ".join(problems) + ". Try again.")
                continue
            if getpass.getpass("Repeat password: ") != pw:
                print("The two entries differ. Try again.")
                continue
            break
        else:
            print("Too many attempts. Nothing was written.")
            return 2
    except getpass.GetPassWarning:
        print("Refusing: this terminal cannot hide typing. Use PowerShell or Windows Terminal.")
        return 2

    doc = {"role": "super_admin", "name": name, "email": email, "phone": None,
           "password_hash": await asyncio.to_thread(security.hash_password, pw),
           "must_change_password": False, "disabled": False, "scope": {}, "created_at": core.now()}
    del pw
    res = await db.users.insert_one(doc)
    await core.audit({"name": "local setup", "role": "system"}, "super_admin_created", "user", str(res.inserted_id),
                     {"method": "create_super_admin.py", "email": email})
    print(f"Super Admin created for {email}. Sign in on the web dashboard's Super Admin login.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nCancelled. Nothing was written.")
        sys.exit(2)
    finally:
        core.client.close()
