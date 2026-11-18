"""Pre-launch test-data cleanup for CheckSphere: inventory first, delete only what an approved manifest lists.

Two steps, deliberately separate:

1. INVENTORY (read-only, safe to run any time):
     python test_data_cleanup.py --inventory [decision flags]
   Reads MongoDB and R2 and writes two files to docs/cleanup/:
     cleanup-manifest-<time>.json   exact ids / keys to delete, plus what is kept
     cleanup-manifest-<time>.md     the same, readable, for the owner's approval
   Nothing is changed anywhere.

   Decision flags (the owner chooses; defaults keep things):
     --delete-users EMAIL[,EMAIL...]   user accounts to remove (e.g. the demo seed accounts)
     --delete-all-users                remove EVERY user account (fresh start). Afterwards create the first Super
                                       Admin with create_super_admin.py (the owner types the login and password).
     --delete-clients                  remove all clients and branches (seed/test master data)
     --reset-case-counter              next case number starts again from 1
     --reset-agent-counter             next generated agent ID starts again from AGT001
     --clear-audit-logs                remove test-period audit entries (one "test_data_cleared" entry is written)

2. EXECUTE (only after the owner approves that exact manifest):
     python test_data_cleanup.py --execute docs/cleanup/cleanup-manifest-<time>.json \\
         --confirm-db <DB_NAME> --confirm "DELETE CHECKSPHERE TEST DATA"
   * Re-reads everything first and REFUSES if any record/file exists now that the manifest did not list for
     deletion in the same collection (new data appeared since approval), or if listed items changed.
   * Saves a TEMPORARY safety export first: every database document that will be deleted, and a copy of every file
     that will be deleted, under backend/backups/pre-cleanup-<time>/ (git-ignored, private). It exists only in case
     the cleanup fails part-way. When every listed item is verified gone, the safety export and the manifest files
     (which name the deleted test users) are deleted automatically. If anything fails or cannot be verified, they are
     KEPT and the command exits with an error, so nothing is lost without a trace.
   * Deletes only the listed items: database documents by _id; R2 objects by exact key, only under "checksphere/";
     and the listed local backup files. (CheckSphere stores files only in R2; it has no Cloudinary access any more.)
   * Never touches: settings, report templates/config, code, users/clients not listed.
   * Verifies every listed item is gone and writes cleanup-result-<time>.md (counts only, no names or emails).
"""
import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId, json_util

import core
import r2_storage
import storage_service

# Only this folder is ever listed or deleted. CLEANUP_PREFIX exists so the test harness can use a throwaway folder.
APP_PREFIX = os.environ.get("CLEANUP_PREFIX") or "checksphere/"
assert APP_PREFIX.startswith("checksphere/"), "cleanup is limited to CheckSphere folders"
CONFIRM_PHRASE = "DELETE CHECKSPHERE TEST DATA"
OUT_DIR = Path(os.environ.get("CLEANUP_DIR") or Path(__file__).resolve().parent.parent / "docs" / "cleanup")
BACKUP_DIR = Path(os.environ.get("CLEANUP_BACKUP_DIR") or Path(__file__).resolve().parent / "backups")

# Collections holding case/test activity: every document is deleted.
ACTIVITY = ["cases", "evidence", "reports", "call_logs", "notifications", "case_uploads", "case_requests", "incidents",
            "retention_runs", "sessions", "backups", "pending_uploads", "idempotency_keys", "storage_migrations"]
# Kept unless a decision flag says otherwise.
KEPT_ALWAYS = ["settings"]


def _id_values(ids: list[str]) -> list:
    """Manifest ids are strings. Most collections use ObjectId keys, but some (sessions) use text ids, so match both
    forms: only the form actually stored can match, so nothing else is ever selected."""
    out: list = []
    for i in ids:
        out.append(i)
        if ObjectId.is_valid(i):
            out.append(ObjectId(i))
    return out


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------- read-only inventory
def _r2_objects() -> list[dict]:
    if not r2_storage.configured():
        return []
    c, out, token = r2_storage.client(), [], None
    while True:
        kw = {"Bucket": r2_storage.bucket(), "Prefix": APP_PREFIX}
        if token:
            kw["ContinuationToken"] = token
        res = c.list_objects_v2(**kw)
        out += [{"key": o["Key"], "size": o["Size"]} for o in res.get("Contents", [])]
        if not res.get("IsTruncated"):
            return out
        token = res["NextContinuationToken"]


def _local_backups() -> list[dict]:
    return [{"file": p.name, "size": p.stat().st_size} for p in sorted(BACKUP_DIR.glob("backup-*.json"))]


def _earlier_safety_exports() -> list[str]:
    """Safety exports kept by an earlier cleanup attempt that did not complete (temporary test-data copies)."""
    return sorted(p.name for p in BACKUP_DIR.glob("pre-cleanup-*") if p.is_dir())


async def inventory(decisions: dict, strict: bool = True) -> dict:
    db = core.db
    names = set(await db.list_collection_names())
    counts = {c: await db[c].count_documents({}) for c in sorted(names)}
    delete: dict[str, list[str]] = {}
    for c in ACTIVITY:
        if c in names:
            delete[c] = [str(d["_id"]) async for d in db[c].find({}, {"_id": 1})]
    users = [{"id": str(u["_id"]), "email": u.get("email"), "agent_id": u.get("agent_id"), "role": u.get("role"),
              "name": u.get("name")} async for u in db.users.find({}, {"password_hash": 0})]
    del_emails = {e.strip().lower() for e in decisions.get("delete_users", []) if e.strip()}
    unknown = del_emails - {(u["email"] or "").lower() for u in users}
    if unknown and strict:
        raise SystemExit(f"--delete-users: no such user(s): {sorted(unknown)}")
    delete["users"] = [u["id"] for u in users if (u["email"] or "").lower() in del_emails]
    if decisions.get("delete_all_users"):
        delete["users"] = [u["id"] for u in users]
    elif strict and not any(u["role"] == "super_admin" and u["id"] not in delete["users"] for u in users):
        raise SystemExit("Refusing: this would delete every Super Admin account (you would be locked out).")
    if decisions.get("delete_clients"):
        for c in ("clients", "branches"):
            if c in names:
                delete[c] = [str(d["_id"]) async for d in db[c].find({}, {"_id": 1})]
    if decisions.get("clear_audit_logs") and "audit_logs" in names:
        delete["audit_logs"] = [str(d["_id"]) async for d in db.audit_logs.find({}, {"_id": 1})]

    # file references held by the records being deleted (all of them, since every case record is test data)
    refs = []
    async for e in db.evidence.find({}, {"storage_path": 1, "storage_provider": 1, "original": 1}):
        if e.get("storage_path"):
            refs.append({"provider": e.get("storage_provider"), "path": e["storage_path"]})
        o = e.get("original") or {}
        if o.get("storage_path"):
            refs.append({"provider": o.get("storage_provider") or e.get("storage_provider"), "path": o["storage_path"]})
    async for u in db.case_uploads.find({}, {"pdf": 1}):
        p = u.get("pdf") or {}
        if p.get("storage_path"):
            refs.append({"provider": p.get("storage_provider"), "path": p["storage_path"]})
    async for r in db.case_requests.find({}, {"documents": 1}):
        refs += [{"provider": d.get("storage_provider"), "path": d.get("path")} for d in r.get("documents") or [] if d.get("path")]

    r2 = await asyncio.to_thread(_r2_objects)
    r2_keys = {o["key"] for o in r2}
    ref_keys = {r["path"] for r in refs}
    return {
        "generated_at": _stamp(), "database": os.environ.get("DB_NAME"), "decisions": decisions,
        "database_counts": counts, "users": users,
        "delete": {"mongodb": delete, "r2": r2, "local_backups": _local_backups(),
                   "earlier_safety_exports": _earlier_safety_exports()},
        "keep": {"collections": sorted(c for c in names if not delete.get(c)), "users": [u for u in users if u["id"] not in set(delete["users"])]},
        "checks": {"super_admin_setup_required": bool(decisions.get("delete_all_users")), "file_refs_in_db": len(refs),
                   "refs_not_on_r2": sorted(r["path"] for r in refs if r["provider"] != storage_service.R2),
                   "r2_refs_missing": sorted(ref_keys - r2_keys), "r2_unreferenced_app_files": sorted(r2_keys - ref_keys),
                   "r2_bucket": r2_storage.bucket() if r2_storage.configured() else None,
                   "reset_case_counter": bool(decisions.get("reset_case_counter")),
                   "reset_agent_counter": bool(decisions.get("reset_agent_counter"))},
    }


def write_manifest(inv: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = inv["generated_at"]
    jpath = OUT_DIR / f"cleanup-manifest-{stamp}.json"
    jpath.write_text(json.dumps(inv, indent=2, default=str), encoding="utf-8")
    d, k = inv["delete"], inv["keep"]
    mb = sum(o.get("size") or 0 for o in d["r2"]) / 1e6
    lines = [f"# CheckSphere test-data cleanup manifest ({stamp} UTC)", "",
             f"Database: `{inv['database']}`. Manifest SHA-256 (approve this exact file): `{hashlib.sha256(jpath.read_bytes()).hexdigest()[:16]}`",
             "", "## Will be deleted", "", "| Where | What | Count |", "|---|---|---|"]
    for c, ids in d["mongodb"].items():
        if ids:
            lines.append(f"| MongoDB | `{c}` documents | {len(ids)} of {inv['database_counts'].get(c, 0)} |")
    lines += [f"| R2 `{inv['checks']['r2_bucket']}` | objects under `checksphere/` | {len(d['r2'])} ({mb:.1f} MB) |",
              f"| Local disk | `backend/backups/backup-*.json` (old DB exports containing test data) | {len(d['local_backups'])} |",
              f"| Local disk | safety exports kept by earlier failed attempts (removed only after this cleanup is verified) | {len(d.get('earlier_safety_exports', []))} |",
              "| Local disk | this cleanup's own temporary safety export (removed automatically once every item is verified gone) | 1 |"]
    if inv["checks"]["reset_case_counter"]:
        lines.append("| MongoDB | `counters.case_seq` reset to 0 (next case is number 1) | 1 |")
    if inv["checks"]["reset_agent_counter"]:
        lines.append("| MongoDB | `counters.agent_id` reset to 0 (next generated agent ID is AGT001) | 1 |")
    lines += ["", "## Will be kept", "",
              f"- Collections kept in full: {', '.join(f'`{c}`' for c in k['collections'])}",
              "- User accounts kept:" + ("" if k["users"] else " **none**")]
    lines += [f"  - {u['role']}: {u['name']} ({u['email'] or u['agent_id']})" for u in k["users"]]
    if d["mongodb"].get("users"):
        lines += ["- User accounts deleted:"] + [f"  - {u['role']}: {u['name']} ({u['email'] or u['agent_id']})"
                                                 for u in inv["users"] if u["id"] in set(d["mongodb"]["users"])]
    lines += ["- Application code, report templates (`report_config.py`, `vee_report.py`), header artwork, settings, "
              "configuration and environment variables: untouched.",
              "- Collections are emptied document by document, never dropped: their indexes, the Client/Branch and User "
              "management APIs, screens and role permissions stay exactly as they are.", "",
              "## Consistency checks", "",
              f"- File references in the database: {inv['checks']['file_refs_in_db']}",
              f"- File references not on R2: {len(inv['checks']['refs_not_on_r2'])}",
              f"- Referenced but missing in R2: {len(inv['checks']['r2_refs_missing'])}",
              f"- CheckSphere files in R2 with no database record: {len(inv['checks']['r2_unreferenced_app_files'])}",
              ""]
    if inv["checks"]["super_admin_setup_required"]:
        lines += ["## After the cleanup: no user accounts exist", "",
                  "Nobody can sign in until the owner creates the first Super Admin on their own computer with "
                  "`create_super_admin.py` (login email and password typed by the owner; only a bcrypt hash is stored). "
                  "Demo seeding is refused on this database, so the demo accounts cannot reappear.", ""]
    lines += ["Nothing has been deleted. The exact ids and keys are in the JSON file of the same name."]
    mpath = jpath.with_suffix(".md")
    mpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mpath


# ---------------------------------------------------------------- execute (approved manifest only)
async def execute(manifest_path: Path) -> Path:
    man = json.loads(manifest_path.read_text(encoding="utf-8"))
    db = core.db
    if man["database"] != os.environ.get("DB_NAME"):
        raise SystemExit("Manifest was made for a different database.")
    now_inv = await inventory(man["decisions"])
    # refuse if the world changed since approval (new records/files would otherwise be left or, worse, misjudged)
    problems = []
    for c, ids in man["delete"]["mongodb"].items():
        if sorted(ids) != sorted(now_inv["delete"]["mongodb"].get(c, [])):
            problems.append(f"MongoDB {c}: approved {len(ids)}, now {len(now_inv['delete']['mongodb'].get(c, []))}")
    if sorted(o["key"] for o in man["delete"]["r2"]) != sorted(o["key"] for o in now_inv["delete"]["r2"]):
        problems.append("r2: listed files differ from what exists now")
    if problems:
        raise SystemExit("Refusing: data changed since the manifest was approved. Run --inventory again.\n  " + "\n  ".join(problems))

    stamp = _stamp()
    safe = BACKUP_DIR / f"pre-cleanup-{stamp}"
    (safe / "files").mkdir(parents=True, exist_ok=True)
    # 1. safety export of every document to delete (password hashes of deleted users are left out)
    export = {}
    for c, ids in man["delete"]["mongodb"].items():
        proj = {"password_hash": 0} if c == "users" else None
        export[c] = [d async for d in db[c].find({"_id": {"$in": _id_values(ids)}}, proj)]
    (safe / "mongodb.json").write_text(json_util.dumps(export, indent=1), encoding="utf-8")
    # 2. safety copy of every file to delete
    for o in man["delete"]["r2"]:
        assert o["key"].startswith(APP_PREFIX)
        out = safe / "files" / "r2" / o["key"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(await asyncio.to_thread(r2_storage.get_object, o["key"]))
    print(f"safety export written: {safe}")

    # 3. delete files (exact ids only), then database documents. Any error stops here with the safety export kept.
    deleted = {"r2": 0, "local_backups": 0, "mongodb": {}}
    try:
        for o in man["delete"]["r2"]:
            await asyncio.to_thread(r2_storage.delete_object, o["key"])
            deleted["r2"] += 1
        for b in man["delete"]["local_backups"]:
            p = BACKUP_DIR / b["file"]
            if p.exists() and p.parent == BACKUP_DIR:
                p.unlink()
                deleted["local_backups"] += 1
        for c, ids in man["delete"]["mongodb"].items():
            if ids:
                r = await db[c].delete_many({"_id": {"$in": _id_values(ids)}})
                deleted["mongodb"][c] = r.deleted_count
        if man["decisions"].get("reset_case_counter"):
            await db.counters.update_one({"_id": "case_seq"}, {"$set": {"seq": 0}})
        if man["decisions"].get("reset_agent_counter"):
            await db.counters.update_one({"_id": "agent_id"}, {"$set": {"seq": 0}})
    except Exception as exc:
        raise SystemExit(f"Cleanup stopped by an error ({type(exc).__name__}: {str(exc)[:200]}). Nothing more was deleted. "
                         f"The safety export is KEPT at {safe}; run --inventory to see what remains.")

    # 4. verify each listed item is really gone
    failures = []
    for c, ids in man["delete"]["mongodb"].items():
        if ids:
            left = await db[c].count_documents({"_id": {"$in": _id_values(ids)}})
            if left:
                failures.append(f"MongoDB {c}: {left} listed documents still present")
    for o in man["delete"]["r2"]:
        if await asyncio.to_thread(r2_storage.head_object, o["key"]) is not None:
            failures.append(f"R2 object still present: {o['key']}")
    for b in man["delete"]["local_backups"]:
        if (BACKUP_DIR / b["file"]).exists():
            failures.append(f"local file still present: {b['file']}")
    for flag, cid in (("reset_case_counter", "case_seq"), ("reset_agent_counter", "agent_id")):
        if man["decisions"].get(flag) and ((await db.counters.find_one({"_id": cid})) or {}).get("seq", 0) != 0:
            failures.append(f"counter {cid} not reset")
    after = await inventory(man["decisions"], strict=False)
    # nothing new may have appeared meanwhile (e.g. a running server writing a notification during the cleanup)
    for c in ACTIVITY + (["users"] if man["decisions"].get("delete_all_users") else []) + \
            (["clients", "branches"] if man["decisions"].get("delete_clients") else []):
        if c in ("backups", "idempotency_keys", "pending_uploads", "storage_migrations"):
            continue  # app bookkeeping a running server may legitimately write after the cleanup; reported in counts
        extra = await db[c].count_documents({})
        if extra and man["delete"]["mongodb"].get(c) is not None:
            failures.append(f"MongoDB {c}: {extra} document(s) present that were not in the manifest (created during the cleanup?)")
    if man["keep"]["collections"] and "settings" in man["keep"]["collections"] and not await db.settings.count_documents({}):
        failures.append("settings document missing")

    # 5. success: remove the temporary safety export and the manifest (it names the deleted test users)
    if not failures:
        shutil.rmtree(safe)
        for name in man["delete"].get("earlier_safety_exports", []):
            if name.startswith("pre-cleanup-") and (BACKUP_DIR / name).is_dir():
                shutil.rmtree(BACKUP_DIR / name)
        for f in (manifest_path, manifest_path.with_suffix(".md")):
            f.unlink(missing_ok=True)
    await core.audit({"name": "system", "role": "system"}, "test_data_cleared", "system", "cleanup",
                     {"result": "verified" if not failures else "incomplete", "deleted": deleted,
                      "safety_export": "deleted after verification" if not failures else "kept"})
    counts = {c: n for c, n in after["database_counts"].items()}
    lines = [f"# Cleanup result ({stamp} UTC)", "",
             f"Result: **{'VERIFIED: every listed item is gone' if not failures else 'INCOMPLETE: see problems below'}**", "",
             "## Deleted", "",
             f"- MongoDB documents: {deleted['mongodb']}",
             f"- R2 objects: {deleted['r2']}",
             f"- Local test exports: {deleted['local_backups']}", "",
             "## Now", "",
             f"- Database collection counts: {counts}",
             f"- User accounts: {len(after['users'])}",
             f"- R2 objects under checksphere/: {len(after['delete']['r2'])}", ""]
    if failures:
        lines += ["## Problems", ""] + [f"- {f}" for f in failures] + [
            "", f"The temporary safety export was KEPT for investigation: `{safe}`"]
    else:
        lines += ["The temporary safety export and the approved manifest (which named the deleted test users) were deleted "
                  "after verification. This report contains counts only."]
    out = OUT_DIR / f"cleanup-result-{stamp}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(f"Cleanup INCOMPLETE ({len(failures)} problem(s)); safety export kept. Report: {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--inventory", action="store_true")
    g.add_argument("--execute", metavar="MANIFEST_JSON")
    ap.add_argument("--delete-users", default="")
    ap.add_argument("--delete-clients", action="store_true")
    ap.add_argument("--delete-all-users", action="store_true")
    ap.add_argument("--reset-case-counter", action="store_true")
    ap.add_argument("--reset-agent-counter", action="store_true")
    ap.add_argument("--clear-audit-logs", action="store_true")
    ap.add_argument("--confirm-db")
    ap.add_argument("--confirm")
    a = ap.parse_args()

    async def go():
        if a.inventory:
            decisions = {"delete_users": [e for e in a.delete_users.split(",") if e.strip()], "delete_clients": a.delete_clients,
                         "delete_all_users": a.delete_all_users, "reset_agent_counter": a.reset_agent_counter,
                         "reset_case_counter": a.reset_case_counter, "clear_audit_logs": a.clear_audit_logs}
            print(write_manifest(await inventory(decisions)))
            return 0
        if a.confirm_db != os.environ.get("DB_NAME") or a.confirm != CONFIRM_PHRASE:
            print(f'Refusing: pass --confirm-db <DB_NAME> and --confirm "{CONFIRM_PHRASE}".')
            return 2
        print(await execute(Path(a.execute)))
        return 0

    try:
        return asyncio.run(go())
    finally:
        core.client.close()


if __name__ == "__main__":
    sys.exit(main())
