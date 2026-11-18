# CheckSphere production launch: R2 + Railway (updated 18-Nov-2026)

## Status (18-Nov-2026, evening)

- **Test-data cleanup: done and verified** (`docs/cleanup/cleanup-result-20261118-160847.md`).
  - The database holds only `settings`, the two reset counters and one audit entry.
  - No user accounts exist yet.
  - CheckSphere's 53 Cloudinary files and 3 R2 test objects were deleted; the 66 assets of other Cloudinary projects are untouched.
  - The temporary safety export and the manifest were deleted after verification.
- **Cloudinary removed from CheckSphere:**
  - no Cloudinary code, dependency or `CLOUDINARY_*` variable remains;
  - R2 is the only storage provider;
  - the Cloudinary account itself (other projects) was not touched.
- **Next:** create the new Super Admin (step 3 below).

The sections below describe the plan and the cleanup as approved; they are kept as the record of what was done.

## What changed in the plan

The owner confirmed on 18-Nov-2026 that **every existing case record and evidence file is test data**. Nothing needs to be kept or migrated.

- **R2 is the permanent storage provider.** `STORAGE_PROVIDER=r2` is the production configuration.
- **The Cloudinary-to-R2 migration was not needed.** The test files were deleted instead, and the migration tool was removed together with Cloudinary.
- **Cleanup comes before launch.** Production starts with an empty case history, the same code, roles, report templates and settings, and only the user accounts the owner keeps.

Each step below that changes data, publishes code or costs money waits for the owner's explicit approval.

## Inventory (read-only, 18-Nov-2026)

### MongoDB Atlas, database `checksphere` (the only app database on the cluster)

| Collection | Documents | Nature |
|---|---|---|
| cases | 27 | test |
| evidence | 26 (53 file references) | test |
| reports | 13 | test |
| call_logs | 3 | test |
| notifications | 86 | test |
| case_uploads | 1 (1 PDF) | test |
| sessions | 23 | test logins |
| backups | 4 | records of local test exports |
| audit_logs | 450 (12–18 Nov) | test activity |
| clients | 2: Metro Capital Finance, Apex Rural Bank | **demo seed data** |
| branches | 3: Andheri, Connaught Place, Koramangala | **demo seed data** |
| users | 7 | see below |
| settings | 1 (company name, flags, retention, blocked words, custom fields) | **keep** |
| counters | `case_seq` 27, `agent_id` 102 | keep (`case_seq` can reset to 0) |
| idempotency_keys, pending_uploads, storage_migrations | 0 | empty |

### Users

| Role | Account | Note |
|---|---|---|
| super_admin | CheckSphere Admin, `admin@checksphere.app` | **demo seed account. Its password is still `Admin@12345`, which is published in `backend/seed.py`.** |
| supervisor | Meera Joshi, `sup1@checksphere.app` | demo seed account, published password |
| agent | Ravi Kumar, `agent1@checksphere.app` | demo seed account, published password |
| agent | Anita Desai, `agent2@checksphere.app` | demo seed account, published password |
| agent | Staff test account A (real staff member; identity not recorded here) | created 12-Nov |
| supervisor | Staff test account B (real staff member; identity not recorded here) | created 13-Nov |
| agent | Staff test account C (real staff member; identity not recorded here) | created 13-Nov |

### Cloudinary (one account, shared with other projects)
- **53 CheckSphere files** under `checksphere/checksphere/` (30.1 MB): 52 evidence photos (26 records × original + watermarked) and 1 case PDF.
  - All 53 are referenced by the database and all exist. There are no orphans and nothing is missing.
- **66 assets belonging to other projects** in the same account (outside the `checksphere/` folder), plus Cloudinary's own `samples/`.
  - **These are never listed for deletion and never touched.** Deleting the Cloudinary *account* is therefore not part of this plan.

### R2
- `checksphere-test`: 0 objects. All test runs cleaned up after themselves.
- `checksphere-prod`: not created yet.
- The test token is limited to one bucket, so it cannot list other buckets.

### Local disk
- `backend/backups/`: 5 old JSON database exports (12–18 Nov) containing test data. The folder is git-ignored.

## Owner decisions (18-Nov-2026, revised)

- **Delete all demo and test data.** That covers:
  - cases, evidence, reports, call logs, notifications, case uploads, sessions and backup records;
  - the test audit log;
  - the demo clients and branches;
  - **every user account**: all 4 demo seed accounts and the 3 staff test accounts (2 agents, 1 supervisor);
  - only CheckSphere's own 53 Cloudinary files and the local test exports. The 66 assets of other projects are never touched.
- **Fresh start:**
  - Both counters reset, so the first case is number 1 and the first generated agent ID is AGT001.
  - The owner creates a brand-new Super Admin after the cleanup, and the real users after that.
- **Keep:** code, roles and permissions, the settings document (company name, flags, retention, restricted words, custom fields), report templates, header artwork, branding and configuration.
- **Clients and branches:** the Super Admin must have full management of them, kept intact through the cleanup (see below).

## Cleanup procedure

The cleanup is done by `backend/test_data_cleanup.py`, tested in isolation by `backend/tests/verify_cleanup.py` (25/25 pass), including:
- the full-wipe path that deletes every user;
- the Super Admin guard;
- control files outside the folder, which survive;
- a refusal when data changes after approval;
- a cleanup that fails part-way (the safety export is kept);
- automatic removal of every temporary copy after a verified success.

**Manifest for approval:** `docs/cleanup/cleanup-manifest-20261118-160007.md` (and `.json`, fingerprint `9c7f5f1d8efee8eb`). It is git-ignored because it lists names and emails. It deletes:

| Where | Count |
|---|---|
| cases / evidence / reports / call_logs / notifications / case_uploads | 27 / 26 / 13 / 3 / 86 / 1 |
| sessions / backups records / audit_logs | 23 / 4 / 450 |
| users | **7 of 7** (no account remains) |
| clients / branches | 2 / 3 (demo data only; the feature stays) |
| Cloudinary `checksphere/` files | 53 (30.1 MB) |
| R2 `checksphere-test` objects | 3 (start-up backups written by Claude's test runs on 18-Nov; not owner data) |
| local `backend/backups/backup-*.json` | 5 |
| counters | `case_seq` → 0, `agent_id` → 0 |

**Kept:** `settings`, the `counters` documents (reset, not removed), the 66 Cloudinary assets of other projects, and all code and configuration.

**Collections are emptied, never dropped.** Their indexes, the Client/Branch and User management APIs, the screens and the role permissions stay unchanged.

**The owner does not want any old test data kept (confirmed 18-Nov-2026).** The safety export is only a temporary precaution in case the cleanup fails.

**How it runs** (only after approval of that exact manifest):
1. **Refuse if anything changed:** it re-reads everything and refuses if any record or file differs from the manifest.
2. **Temporary safety export:** it writes a copy of the documents to be deleted (password hashes left out) and of every file to be deleted to `backend/backups/pre-cleanup-<time>/`, which is git-ignored and local only. If this copy cannot be made completely, nothing is deleted.
3. **Delete:** it deletes only the listed items:
   - CheckSphere's Cloudinary files, by exact id, under `checksphere/` only;
   - the R2 objects, by exact key;
   - the 5 local exports;
   - the database documents;
   - then it resets the counters.
   If any deletion fails, it stops at once, deletes nothing more, and **keeps** the safety export and the manifest.
4. **Verify:** it checks that every listed item is gone, the counters are reset, the settings document is present, and the 66 assets of other Cloudinary projects are all still there.
5. **On verified success, it deletes:**
   - the temporary safety export;
   - any safety export kept by an earlier failed attempt;
   - the manifest files, which name the deleted test users.

   **No copy of the old test data remains anywhere.** The only record left is `docs/cleanup/cleanup-result-<time>.md` (counts only, no names or emails) plus one audit-log entry, "test_data_cleared" (counts only).
6. **If verification finds a problem:** everything is kept, the command exits with an error, and the result report lists the problems.

```bash
python test_data_cleanup.py --execute docs/cleanup/cleanup-manifest-20261118-160007.json --confirm-db checksphere --confirm "DELETE CHECKSPHERE TEST DATA"
```

## Creating the new Super Admin (owner, on their own computer)

After the cleanup, no account exists. The owner creates the first Super Admin with `backend/create_super_admin.py` (tested by `backend/tests/verify_superadmin_setup.py`, 11/11 pass). It is run in **PowerShell or Windows Terminal**, from the `backend` folder:

```bash
..\.venv\Scripts\python.exe create_super_admin.py
```

The script then:
1. Shows which database it will write to and asks the owner to type its name (`checksphere`).
2. Asks for the **login email** and full name. The Super Admin login screen signs in by email.
3. Asks for the **password twice with hidden typing**.
   - Rules: at least 12 characters, letters and a digit, not a demo password, not containing "checksphere" or the email name.
   - It **refuses to run in a terminal that cannot hide typing**, rather than echoing the password.
4. Stores only a **bcrypt hash**.
   - The password is never a command argument, never an environment variable, and never printed, logged, written to `.env`, manifests or code.
   - One audit entry ("super_admin_created", email only) is written.
5. It **refuses if an active Super Admin already exists**, so it can't be used to take over a running system. All further users are created in the dashboard (Supervisors, Agents).

Never share the password in chat. Claude never runs this script with real values.

For Railway, the same script can later be run with `railway run python create_super_admin.py`, if the database is ever recreated.

## Demo accounts can no longer appear

- `seed.py` now refuses to create demo data unless the database is on **this computer** (localhost) and the environment is not marked production, **whatever `SEED_DEMO_DATA` says**.
  - Tested against Atlas, other hosts, look-alike hostnames, tricky URLs and `APP_ENV=prod`.
  - Without this lock, the empty users table after the cleanup would have let the demo admin be re-created by a single setting.
- `prelaunch_check.py` blocks launch if any demo seed account exists (enabled or not), if any account accepts a published demo password, if seeding would be possible, or if no Super Admin exists.

## Client and branch management (Super Admin)

| Action | API (server-enforced: Super Admin only) | Screen (Super Admin portal → Clients and Branches) |
|---|---|---|
| View all, including inactive | `GET /clients?include_inactive=true`, `GET /branches?include_inactive=true` (others always get active only) | list with Active/Inactive badges, branches under their client |
| Create client | `POST /clients` (duplicate names refused, any letter case) | "Add Client" |
| Edit client | `PUT /clients/{id}` (name, code) | "Edit" |
| Activate / deactivate client | `POST /clients/{id}/set-active` | "Deactivate" (with confirmation) / "Activate" |
| Create branch under a selected client | `POST /branches` (client must exist and be active; duplicate names within the client refused) | "Add Branch" (active clients only) |
| Edit branch | `PUT /branches/{id}` (name, city, state) | "Edit" |
| Activate / deactivate branch | `POST /branches/{id}/set-active` | "Deactivate" / "Activate" |

- **Supervisors and Agents:**
  - The server refuses every create, edit and deactivate (403). There is no delete endpoint for anyone; deactivation is used instead.
  - They can still *read* active clients and branches, which the case forms need.
  - The Clients and Branches menu item exists only in the Super Admin portal, and `/admin/*` redirects anyone else to their own portal.
- **Effect of deactivating:**
  - The client or branch is no longer offered or accepted for **new** cases (manual creation and Excel import). Existing cases keep their client and branch.
  - Deactivating a client also hides its branches from the lists.
- **Small fix included:** a new case's branch must belong to the chosen client. Before, a mismatched branch was silently accepted, and a malformed branch id caused a server error.
- **Every change is audited:** client/branch created, updated, activated and deactivated.
- **Tests:**
  - `backend/tests/verify_clients_branches.py`: 23/23 pass, covering API permissions for every role, deactivation effects, the Excel import, duplicates and audit.
  - A browser check of the web dashboard on throwaway data: add, edit, deactivate with confirmation, reactivate, add branch; and a Supervisor gets no menu item and is redirected away from `/admin/clients`.

## Launch sequence and approval gates

| # | Step | Who | Needs approval |
|---|---|---|---|
| 1 | Approve the manifest `cleanup-manifest-20261118-160007` | owner | **done** (approved) |
| 2 | Run the cleanup, verify, show the result report | Claude | **done**, verified |
| 3 | Create the new Super Admin with `create_super_admin.py` (owner types email and password locally) | owner | n/a |
| 4 | Sign in, create real clients/branches, supervisors and agents in the dashboard | owner | n/a |
| 5 | Create R2 bucket `checksphere-prod`, a token scoped to it, and the 2-day `incoming/` lifecycle rule | owner | n/a |
| 6 | Commit and push the code | Claude | **yes** |
| 7 | Create the Railway service and variables, generate the domain | owner, Claude guiding | **yes** (public deploy) |
| 8 | `railway run python prelaunch_check.py` → 0 blocking; smoke test | Claude | n/a |
| 9 | Production APK (EAS) with `EXPO_PUBLIC_BACKEND_URL=https://<railway-domain>` | owner | **yes** |
| 10 | Remove Cloudinary from CheckSphere (code, dependency, variables) | Claude | **done** (none to set on Railway) |
| 11 | Replace Atlas `0.0.0.0/0` before real applicant data arrives | owner | **yes** (may cost money) |

**Note for local development after launch:** `backend/.env` points at the same Atlas database that becomes production. Use a separate development database and the `checksphere-test` bucket for local work.
