"""Read-only pre-launch checklist for a CheckSphere production environment. Changes nothing anywhere.

Run with the PRODUCTION variables loaded (e.g. `railway run python prelaunch_check.py`, or locally with backend/.env
pointing at the production database and bucket). Never prints secret values.
Exit code 0 = ready, 1 = at least one blocking problem.
"""
import asyncio
import os
import sys

import core
import r2_storage
import security
import storage_service

SEED_PASSWORDS = {"admin@checksphere.app": "Admin@12345", "sup1@checksphere.app": "Super@12345",
                  "agent1@checksphere.app": "Agent@12345", "agent2@checksphere.app": "Agent@12345"}
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool | None, detail: str = "", blocking: bool = True):
    status = "OK" if ok else ("WARN" if ok is None or not blocking else "BLOCK")
    results.append((status, name, detail))


async def main() -> int:
    env = os.environ
    check("JWT_SECRET is long and random-looking", len(security.SECRET) >= 48 and len(set(security.SECRET)) > 20,
          f"length {len(security.SECRET)}")
    check("SEED_DEMO_DATA is not enabled", env.get("SEED_DEMO_DATA", "").strip().lower() != "true")
    check("New uploads go to R2", storage_service.write_provider() == storage_service.R2, storage_service.write_provider())
    try:
        r2_storage.init()
        r2_ok = True
    except Exception as exc:
        r2_ok = False
        r2_err = type(exc).__name__
    check("R2 bucket reachable with these credentials", r2_ok, "" if r2_ok else r2_err)
    bucket = env.get("R2_BUCKET", "")
    check("Production bucket (not the test bucket)", "test" not in bucket.lower(), bucket)
    check("Media folder is the production one", storage_service.MEDIA_ENV in ("prod", "production"),
          f"MEDIA_FOLDER_ENV={storage_service.MEDIA_ENV}", blocking=False)
    check("ALLOWED_ORIGINS restricted to the dashboard", env.get("ALLOWED_ORIGINS", "*").strip() not in ("", "*"),
          env.get("ALLOWED_ORIGINS", "*"), blocking=False)
    check("Small-RAM cache sizes set", int(env.get("IMAGE_CACHE_MB", "200")) <= 64 and int(env.get("REPORT_CACHE_MB", "150")) <= 64,
          f"IMAGE_CACHE_MB={env.get('IMAGE_CACHE_MB', '200')} REPORT_CACHE_MB={env.get('REPORT_CACHE_MB', '150')}", blocking=False)
    db = core.db
    await core.client.admin.command("ping")
    weak = []
    async for u in db.users.find({"email": {"$in": list(SEED_PASSWORDS)}, "disabled": {"$ne": True}}, {"email": 1, "password_hash": 1}):
        if await asyncio.to_thread(security.verify_password, SEED_PASSWORDS[u["email"]], u.get("password_hash") or ""):
            weak.append(u["email"])
    check("No active account uses a published demo password", not weak, ", ".join(weak) or "none")
    demo = [u["email"] async for u in db.users.find({"email": {"$in": list(SEED_PASSWORDS)}}, {"email": 1})]
    check("No demo seed accounts exist (enabled or not)", not demo, ", ".join(demo) or "none")
    import seed
    check("Demo seeding impossible on this database", not seed.seeding_allowed(), "")
    supers = await db.users.count_documents({"role": "super_admin", "disabled": {"$ne": True}})
    check("At least one active Super Admin", supers >= 1, str(supers))
    not_r2 = await db.evidence.count_documents({"storage_path": {"$nin": ["", None]}, "storage_provider": {"$ne": "r2"}}) + \
        await db.case_uploads.count_documents({"pdf.storage_path": {"$nin": ["", None]}, "pdf.storage_provider": {"$ne": "r2"}})
    check("Every stored file is on R2", not_r2 == 0, f"{not_r2} records elsewhere")
    check("Test data cleared (no cases yet)", await db.cases.count_documents({}) == 0,
          f"{await db.cases.count_documents({})} cases", blocking=False)
    check("Header_CheckSphere supplied", not __import__("exporters").report_header_is_legacy(),
          "still using the AADITYA fallback", blocking=False)

    width = max(len(n) for _, n, _ in results)
    for status, name, detail in results:
        print(f"[{status:5}] {name.ljust(width)}  {detail}")
    blocks = sum(1 for s, _, _ in results if s == "BLOCK")
    print(f"\n{blocks} blocking, {sum(1 for s, _, _ in results if s == 'WARN')} warnings")
    return 1 if blocks else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    finally:
        core.client.close()
