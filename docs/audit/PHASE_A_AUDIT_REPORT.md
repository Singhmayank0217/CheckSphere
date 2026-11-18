# CheckSphere — Phase A Audit Report

**Date:** 2026-11-12  **Scope:** full repository at `D:\Working Codes\CheckSphere` (161 tracked files)  **Mode:** read-only. No source file was changed. The only file added is this report.

**How this was verified:** every backend module was read in full. The frontend was read where it touches the API, storage, camera, GPS, drafts and notifications. Local checks were run (see §15). Where a claim comes only from reading code and not from running it, it says so.

---

## 0. Executive summary

CheckSphere is a well-structured FastAPI + MongoDB backend with an Expo (Android + web) frontend. The business workflow is mostly there in code. It is **not production-ready**. Five issues block it, all fixable in days, not weeks:

1. **Login cannot work on your machine right now.** `backend/.env` has no `JWT_SECRET`. PyJWT 2.15 refuses an empty key (`InvalidKeyError: HMAC key must not be empty` — reproduced locally), so `POST /api/auth/login` returns HTTP 500. Startup still says "complete" because the token is only signed at login.
2. **An agent can list other agents' cases.** `GET /api/cases?agent_id=<other agent>` overwrites the agent's own scope filter (`cases_routes.py:216` then `:247`). Supervisors can escape their scope the same way through `client_id`, `state`, `city`, `branch_id` or `agent_id` on the case list, the Excel export and the dashboard.
3. **"Masked" report data is not masked.** The review and report endpoints return masked data in `masked_data` and also the raw, unmasked data in `report.data` in the same response (`reports_routes.py:119`, `:257`).
4. **File storage is entirely Emergent's.** `storage_service.py` talks only to `integrations.emergentagent.com` using `EMERGENT_LLM_KEY`. Outside Emergent, every photo upload, request-document upload, file view and backup fails. Nothing has been stored anywhere else. **Decision (owner, 2026-11-12): replace it with Cloudinary, using authenticated delivery.** Amazon S3 is no longer part of the plan (see §5).
5. **A fresh production database would get a known Super Admin password.** `seed.py` runs on every startup when `users` is empty and creates `admin@checksphere.app` / `Admin@12345`, which is never forced to change.

Exactly **one** Emergent runtime dependency matters for behaviour: object storage. Everything else Emergent-related is leftover config, branding or unused packages.

---

## 1. Project architecture (as built)

```
 Android app (Expo)  ─┐
 Web dashboard (Expo  ├─HTTPS JSON + Bearer JWT──►  FastAPI (backend/server.py, /api/*)
   web, same bundle) ─┘                               │  ├─ Motor ──► MongoDB Atlas (checksphere, Mumbai)
                                                      │  ├─ requests ──► Emergent Object Storage  ✗ (fails outside Emergent)
                                                      │  └─ in-process asyncio loops: daily backup (→ storage ✗), 24/48h alerts
                                                      └─ python-docx / reportlab / openpyxl / segno (local report generation)
```

| Area | Implementation | Runs where |
|---|---|---|
| API | FastAPI 0.110.1, Starlette 0.37.2, Uvicorn 0.25.0, single `/api` router, 10 route modules | Local |
| DB | Motor 3.7.1 / PyMongo 4.18 → Atlas | External (Atlas, Mumbai) |
| Auth | bcrypt (cost 10), HS256 JWT (12 h) + server-side `sessions` collection (30 days, TTL index), role guards | Local |
| Storage | Emergent objstore HTTP API | **External — Emergent only** |
| Reports | DOCX (python-docx), PDF (reportlab), XLSX (openpyxl), QR (segno) | Local |
| Jobs | `daily_backup_loop` (hourly check), `pending_alert_loop` (5 min) as asyncio tasks inside the API process | Local (one copy per worker) |
| Notifications | `notifications` collection + app polling + **local** phone notifications (expo-notifications). No remote push | Local |
| Frontend | Expo SDK 58, RN 0.88, React 19.3, expo-router, react-query; agent screens (`app/(agent)`, `case`, `report`, `camera`, `request-new`), web portals (`app/admin`, `app/supervisor`, `src/portal`) | Local / device |

**Collections in use:** `users, sessions, clients, branches, cases, reports, evidence, call_logs, audit_logs, notifications, case_requests, settings, counters, backups, activation_tokens, incidents, retention_runs`.

**Report types** (`report_config.py`): residence (applicant/co-applicant), business, office, seller, telephone (residence/office), income, KYC, bank account, custom. Config-driven fields, GPS requirement, photo slots and minimum call attempts.

---

## 2. Emergent-specific dependencies (complete list)

| # | File:line | What | Needed for the app? | Action |
|---|---|---|---|---|
| E1 | `backend/storage_service.py:1-60` | Whole storage client; default base URL `https://integrations.emergentagent.com`, `/objstore/api/v1/storage/init` with `EMERGENT_LLM_KEY` | **Yes** — evidence, request docs, backups | **Replace** with a Cloudinary media service (§5). Callers: `server.py:79`, `evidence_routes.py:35,86`, `requests_routes.py:126,140`, `ops_routes.py:120` |
| E2 | `backend/requirements.txt:59` | `litellm` wheel from `customer-assets.emergentagent.com` | No (never imported) | Remove |
| E3 | `backend/requirements.txt` (removed locally, uncommitted) | `emergentintegrations==0.2.2` | No (never imported) | Keep removed |
| E4 | `backend/requirements.txt` | ~60 unused packages: `openai, google-genai, google-generativeai, google-api-*, huggingface_hub, tokenizers, tiktoken, stripe, pandas, numpy, boto3, botocore, s3transfer, s5cmd, jq, black, mypy, flake8, isort, passlib, python-jose, ecdsa, rsa…` | No | Trim to the runtime set (§10) and add the official `cloudinary` SDK |
| E5 | `frontend/app.json:12,23` | `com.emergent.fieldtrace.hco5ty` bundle/package ID; `slug`/`scheme` = `frontend` | Yes (identity of the APK) | Change to your company's ID **before the first APK goes out** (changing it later makes it a different app) |
| E6 | `frontend/package.json` `preinstall` + `frontend/scripts/cmd-guard*`, `install-guard.sh`, `sync-shims.sh` | Emergent sandbox install guard (reads `/opt/install-guard/rules.json`) | No | Remove |
| E7 | `.emergent/`, `.gitconfig` (identity `emergent-agent-e1`), `TEMPLATE.md`, `README.md` (Emergent template text), `memory/PRD.md`, `test_result.md`, `test_reports/` | Platform metadata and docs | No | Replace README; archive the rest under `docs/legacy/` |
| E8 | `backend/tests/*.py` | Hardcode `/app/frontend/.env`, `/app/backend/tests`, demo passwords, and call a live preview URL | Tests only | Rewrite to run against a local backend + separate test DB |
| E9 | `frontend/src/utils/upload.ts`, `constants/testIds` | Comments referencing the platform | No | Cosmetic |
| E10 | `memory/PRD.md:39` | "Real push … needs Emergent push" | Feature gap | Use Expo push service or FCM directly if remote push is wanted |

No Emergent URLs are hardcoded in the frontend. `EXPO_PUBLIC_BACKEND_URL` was filled in by the platform and **is missing locally** (there is no `frontend/.env`).

---

## 3. Broken or incomplete integrations

| ID | Severity | Item | Evidence |
|---|---|---|---|
| B1 | CRITICAL | Login fails (500): no `JWT_SECRET` | `security.py:15` uses `""` as the default; reproduced the `InvalidKeyError` |
| B2 | CRITICAL | Object storage: all uploads, file views and backups fail | `storage_service.py`; your logs show the 400 from `/storage/init` |
| B3 | HIGH | Daily backup fails every hour and only logs one error line | `ops_routes.py:131-139` |
| B4 | HIGH | Frontend has no `EXPO_PUBLIC_BACKEND_URL` → calls relative `/api` → fails on Android and on the Expo web dev server | `src/api.ts:7` |
| B5 | MEDIUM | Your startup command `python -m uvicorn server --reload` is missing `:app` | Use `python -m uvicorn server:app --reload --port 8001` from `backend/` |
| B6 | MEDIUM | Automated tests can't run outside Emergent (Linux paths, live preview URL) | `backend/tests/*` |
| B7 | LOW | 2 TypeScript errors | `src/utils/phoneAlerts.ts:39,44` |

---

## 4. MongoDB health

**Good:** one Motor client shared by the whole app; `tz_aware=True`; index creation at startup (`server.py:26-52`) including unique `internal_case_id`, sparse-unique `email`/`agent_id`, TTL on `sessions.expires_at`; atomic counters (`core.next_seq`); soft-delete of cases; client closed on shutdown.

| ID | Severity | Finding | File |
|---|---|---|---|
| D1 | CRITICAL | Demo data (users with known passwords, fake cases) seeds into **any** empty DB, production included | `seed.py:9-26`, `server.py:83` |
| D2 | HIGH | No environment separation: one `DB_NAME`, no `APP_ENV`. Tests write into the same DB | `core.py:17-19` |
| D3 | MEDIUM | Missing indexes: `notifications(user_id, created_at)`, `case_requests(requested_by)`, `(supervisor_id, status)`, `audit_logs(user_id)`, `audit_logs(entity_id)`, `activation_tokens(token_hash)` + TTL, `reports(case_id, status)` | `server.py:26` |
| D4 | MEDIUM | No timeouts configured (defaults: 30 s server selection); `/health` doesn't check the DB | `core.py:18`, `server.py:61` |
| D5 | MEDIUM | `KeyError` at import if `MONGO_URL`/`DB_NAME` are missing (crash without a helpful message); no config validation | `core.py:17` |
| D6 | MEDIUM | Several multi-document updates (submit report, approve request → create case) aren't transactional; a crash in between leaves partial state | `reports_routes.py:170-178`, `requests_routes.py:256-268` |
| D7 | LOW | Invalid ObjectId/ISO date strings in some routes → 500 instead of 400/404 (`admin_routes` user ops, `list_cases` dates) | various |
| D8 | LOW | Motor is deprecated in favour of PyMongo's native async API; plan a migration, not urgent | `core.py:14` |
| D9 | INFO | Atlas tier unknown. The free M0 tier has **no backups** and isn't suitable for production | — |

**Backups (`ops_routes.py:114-139`):** application-level JSON dump of 10 collections. It **leaves out** `counters` (a restore would reset the `CSV-000xxx` numbering and hit duplicate-key errors), `case_requests`, `notifications`, `sessions` and `activation_tokens`. Evidence files aren't included. The output is unencrypted plaintext PII. Everything is loaded into memory (`to_list(100000)`). **There is no restore code.** Backups should rely on Atlas backups plus `mongodump`, with the app job kept only as an extra export.

---

## 5. Object storage — current behaviour and recommendation

**Current behaviour** (all through E1):

| Function | Endpoint | Gaps |
|---|---|---|
| Evidence upload | `POST /api/evidence/upload` (`evidence_routes.py:15`) | Reads the whole file into memory before the 10 MB check; **no MIME/extension allowlist**; the extension comes from the client filename unsanitised (`:33`, e.g. `a.x/../` → key fragment `x/../`); no retry/idempotency key. Good: SHA-256, uuid object key, case/agent authorisation for agents, GPS/time metadata saved, timeline + audit |
| Evidence view | `GET /api/files/{id}?token=` (`:68`) | **Bearer token in the URL** (ends up in logs/history); serves the **client-supplied MIME `inline`** from the API origin → an uploaded HTML/SVG file is stored XSS against admins; filename not escaped in the header |
| Request documents | `requests_routes.py:120-143` | Same issues; any MIME type allowed |
| Deletion | none; retention purge (`ops_routes.py:173`) only clears `storage_path` in Mongo — **the files themselves are never deleted** | Matters for DPDP |
| Backups | `ops_routes.py:120` | Same storage as evidence |
| Reports | DOCX/PDF list photo references only; **photos are not embedded** | Functional gap |

### 5.1 Decision: Cloudinary (owner's decision, 2026-11-12). Amazon S3 is dropped.

```
Mobile app / Web dashboard ──(Bearer JWT, multipart)──► FastAPI ──(API key + secret, server-side only)──► Cloudinary (type=authenticated)
                                                          │
                                                          └──► MongoDB Atlas: evidence metadata only (no binaries)
```
The app never talks to Cloudinary directly and never sees a Cloudinary credential. `CLOUDINARY_*` variables exist only in `backend/.env`.

### 5.2 What Cloudinary's documentation says (checked 2026-11-12), and what it means for the design

| Fact (Cloudinary docs) | Consequence for CheckSphere |
|---|---|
| `type: "upload"` (the default) is **public** on the CDN | Every upload must set `type="authenticated"`. A random public ID isn't treated as protection |
| `authenticated` protects the original **and all derived versions**; delivery needs a signed URL; on-the-fly transformations aren't allowed (use eager transformations) | Thumbnails are generated as eager transformations at upload time |
| Ordinary signed delivery URLs **do not expire** and "Doesn't prevent link sharing" | Ordinary signed CDN URLs are **never** handed to clients for evidence |
| Expiring CDN tokens (`auth_token`) need the **Advanced plan or higher**, enabled by Cloudinary support | Not assumed. The design works without it |
| `private_download_url(public_id, format, resource_type, type, expires_at)` gives a **time-limited** signed URL through the Admin API (default 1 h; not cached on the CDN; uses about twice the bandwidth) | This is the "short-lived signed download URL": backend-issued, **≤ 120 s**, only after the authorisation check |
| Backend SDKs default to `resource_type=image`; `raw` is for non-media files | Photos → `image`. PDF/DOCX/XLSX evidence and request documents → `raw` (no image processing, no PDF rasterising, and it avoids the free plan's PDF-delivery block on image assets). To be confirmed by a real test on your account |
| Free plans block PDF/ZIP **delivery** by default (Security settings); paid plans don't | Covered by `raw` + backend download, but tested explicitly (test 3) |
| Signed uploads are created on the backend with the API secret (signature valid for 1 h) | Uploads go through the backend (see 5.3) |
| `overwrite=false` with an existing public ID returns `"existing": true` | Gives idempotent retries |
| Upload size limits depend on the plan | Our own limits (images 10 MB, docs 15 MB) are kept at or below your plan's limit; to be checked in your Console |
| **Storage is in the US by default; EU/APAC residency is an Enterprise-only, on-request option. India isn't listed** | ⚠️ See 5.6 |

### 5.3 Upload flow (backend-proxied; recommended over direct-from-phone signed uploads)
1. The app sends `POST /api/evidence/upload` (multipart) with the JWT and a client-generated `upload_id` (UUID, used for idempotency).
2. The backend authorises the request. An agent must be assigned to the case. Supervisors must have the case in their scope (fixes A7). The case status must allow uploads.
3. The backend reads the file as a **stream with a size cap**. It checks the extension against an allowlist, checks the **magic bytes** against the allowlist (JPEG/PNG/HEIC/WebP for photos; PDF/DOCX/XLSX for documents), and ignores the MIME type the client claims. It computes SHA-256 and MD5.
4. **Duplicate check before upload:** if the same `sha256` already exists on the same case, it returns the existing record (`same_evidence_reused`). If it exists on another case, it uploads and flags `duplicate_photo_cross_case` for human review (current behaviour is kept).
5. It inserts an `evidence` row first with `verification_status="pending_upload"` and pre-allocated `_id`.
6. `cloudinary.uploader.upload(... type="authenticated", resource_type=image|raw, public_id=<deterministic>, overwrite=False, eager=[thumbnail] for images, context/metadata = non-PII ids only)`, wrapped in a 3-attempt exponential backoff for 5xx and timeouts. A 4xx is not retried.
7. **Upload verification:** `bytes` must equal the local size and `etag` must equal the local MD5. If they match, the status becomes `stored`; otherwise it becomes `upload_failed`, the asset is destroyed and the API returns 502. A retry with the same `upload_id` resumes safely.
8. Timeline entry and audit `evidence_uploaded` (sha prefix, size, resource_type; no PII).

A direct phone-to-Cloudinary signed upload would save backend bandwidth, but it lets the client control the payload before we've inspected it. It isn't recommended for applicant evidence at this volume.

### 5.4 Download / view flow
- `GET /api/files/{evidence_id}`: authorisation check (`can_access_case`), then the **backend streams the bytes** (fetched server-side via `private_download_url`). Response headers: fixed safe `Content-Type` from our allowlist, `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`, RFC 6266-encoded filename. Audited as `evidence_downloaded`. This keeps a leaked URL from being a risk at all, and it's what the web `<img>` and the report generator use.
- `POST /api/files/{evidence_id}/download-link` (admin/supervisor only): returns a `private_download_url` with `expires_at = now + 120 s`, audited as `evidence_link_issued`. It's for large files or bulk downloads. **Residual risk, stated plainly:** anyone holding this link can use it until it expires.
- The `?token=<JWT>` query parameter is replaced with a 60-second, single-purpose, HMAC-signed file ticket bound to user + evidence id (fixes A6).
- Thumbnails: the eager derived image, also streamed by the backend.

### 5.5 Naming and folders (no personal data anywhere in IDs)
```
checksphere/{env}/evidence/{category}/{case_oid}/{evidence_oid}     category ∈ residence | office | business | applicant | documents
checksphere/{env}/requests/{request_oid}/{doc_id}
checksphere/{env}/reports/{case_oid}/v{n}                            (only if generated reports are stored; today they're generated on demand)
```
`category` comes from `report_type` (`residence_*`, `tel_residence` → residence; `office_*`, `tel_office` → office; `business_applicant` → business; `kyc`, `income`, `bank_account`, `seller`, `custom` → applicant; non-photo files → documents). `{env}` is `dev`/`staging`/`prod`. A **separate Cloudinary product environment for production** is recommended, so dev keys can never touch production media. Context metadata is limited to `case_oid`, `evidence_oid` and `slot`. No names, phones, PAN, Aadhaar or addresses.

### 5.6 ⚠️ Data residency — needs your explicit sign-off
By default Cloudinary stores assets in the **United States**. EU/APAC regions are an Enterprise option on request, and India isn't offered. Your MongoDB data is in Mumbai, but applicant photographs and identity documents would sit outside India. Before production, please check:
- your contracts with SBI and other bank clients (bank outsourcing contracts often carry data-location and audit-right clauses); and
- DPDP cross-border transfer rules (transfers are allowed unless the Government restricts a country, but your clients may impose stricter terms).

This doesn't change the implementation. It's a business/legal sign-off I can't make for you. If a client requires India-only storage, the storage service is behind an interface, so another backend can be swapped in without touching routes.

### 5.7 MongoDB `evidence` metadata (new fields are additive; nothing existing is removed)
`case_id, slot, kind, sha256, gps{lat,lon,accuracy,status,mocked}, captured_at, uploaded_by, uploaded_by_name, device_id, mime, size, filename, created_at` (existing) **+** `upload_id` (unique), `agent_id`, `storage_provider` (`cloudinary`|`emergent_legacy`), `cloudinary.{asset_id, public_id, resource_type, type, version, format, bytes, etag}`, `verification_status` (`pending_upload|stored|upload_failed|deleted|legacy_unavailable`), `uploaded_at`, `deleted_at`, `deleted_by`. Request documents get the same sub-document.

### 5.8 Deletion
`cloudinary.uploader.destroy(public_id, resource_type=…, type="authenticated", invalidate=True)`. The Mongo row is **soft-deleted** (`verification_status=deleted`, `deleted_at`, `deleted_by`) and audited as `evidence_deleted`. Only Super Admin can delete, and only after review; agents can't delete submitted evidence. Retention purge (`ops_routes.py:173`) will call this, so the files are really removed and not just unlinked. Note: if Cloudinary's own backup feature is enabled on your plan, copies may persist there. That will be documented.

### 5.9 Reports
DOCX/PDF generation will fetch each evidence image server-side and **embed** it with slot, captured time and GPS captions. Today the reports only list references. Generated reports stay on-demand and are not stored by default.

### 5.10 Existing data / migration
- Evidence rows created on Emergent keep all their metadata. A one-off script marks them `storage_provider="emergent_legacy"`, `verification_status="legacy_unavailable"`. Nothing is deleted.
- If you can still export the files from Emergent, `scripts/migrate_legacy_evidence.py --dry-run` will match the files by `storage_path`, check SHA-256 against the stored `sha256`, upload them to Cloudinary, and update the rows (keeping `legacy_storage_path`). Without the files, the rows stay visible as "file not available".
- I can't tell from here how many such rows exist in your Atlas database. A read-only count is the first step once you approve.

### 5.11 Backups (not Cloudinary's job)
Cloudinary stores media; it doesn't back up the database. The backup plan is:
1. **Atlas backups**: continuous backup or cloud snapshots on a dedicated tier (M10+); the free M0 tier has none.
2. **`mongodump --archive --gzip`** scheduled from an operator machine or server, **encrypted** (age or AES-256-GCM, with the key kept off the server), stored in two places, and covered by a written, **tested restore procedure** (`BACKUP_AND_RECOVERY.md`) with a restore drill into a scratch database.
3. The in-app "Run backup" button becomes an encrypted export of **all** collections (including `counters` and `case_requests`). It goes to local encrypted storage by default. Uploading it to Cloudinary (`raw`, `authenticated`, restricted) is **optional and off by default**: the archive is encrypted *before* upload, and plan file-size limits may make it unsuitable as data grows.
4. Cloudinary media itself: enable Cloudinary's backup option if your plan includes it, and document how deleted or overwritten assets are recovered.

---

## 6. Authentication & authorisation

| ID | Severity | Finding | File:line |
|---|---|---|---|
| A1 | CRITICAL | Missing `JWT_SECRET` → login 500 (fail-closed, not forgeable, but blocks everything). There's no startup check | `security.py:15` |
| A2 | CRITICAL | **Scope-override IDOR.** Query params overwrite the role scope filter. Agent: `?agent_id=` on `/api/cases`. Supervisor with a single-dimension scope: `?client_id/state/city/branch_id/agent_id=` on `/api/cases`, `/api/exports/cases.xlsx`, `/api/dashboard/*` (stats, map) | `cases_routes.py:216,239-247`; `export_routes.py:74-80`; `dashboard_routes.py:19-29` |
| A3 | CRITICAL | Default Super Admin `Admin@12345`, `must_change_password=False`; demo agents/supervisor also seeded | `seed.py:15,23` |
| A4 | HIGH | Masking bypass: raw `report.data` returned beside `masked_data` | `reports_routes.py:119,257` |
| A5 | HIGH | No login rate limiting / lockout / backoff; failed logins are only audited | `auth_routes.py:31` |
| A6 | HIGH | Token in query string for file views; web stores the token in AsyncStorage (localStorage). Together with A4/§5 inline-MIME, one XSS → admin token theft | `api.ts:89`, `storage/index.web.ts:51` |
| A7 | MEDIUM | Supervisors can write to cases **outside** their scope: evidence upload, visit start, call logs (only the agent role is checked) | `evidence_routes.py:22`, `cases_routes.py:376,401` |
| A8 | MEDIUM | A supervisor with an empty `scope` sees **all** cases (by design, but risky by default) | `security.py:115-131` |
| A9 | MEDIUM | `CORS allow_origins=["*"]` with credentials | `server.py:57` |
| A10 | MEDIUM | `/docs`, `/openapi.json` public | FastAPI default |
| A11 | LOW | Supervisors can list all users, including Super Admin phone/email/last-login IP | `admin_routes.py:39` |
| A12 | LOW | `GET /reports/{id}` changes state (marks under_review) | `reports_routes.py:236` |
| A13 | LOW | Password policy is length ≥ 8 only; no self-service reset (admin reset + activation link exist, which is fine for an internal app) | `auth_routes.py:26` |

**Works correctly (code-reviewed):** bcrypt hashing; DB-backed sessions checked on every request (so logout, revoke-all, deactivate and password reset invalidate tokens immediately); forced first-login password change gate; `disabled` users blocked; agent object checks on case detail, report, draft, submit, evidence list, call logs, agent-response; request scoping; review/export restricted to admin/supervisor; audit log on almost every action.

**Secure Super Admin initialisation (to build):** `python -m scripts.create_superadmin --email … --name …`. It prompts for the password interactively, never through args or env, and refuses if a super admin exists unless `--force`. Seeding is allowed only when `APP_ENV=development` **and** `SEED_DEMO_DATA=true`.

---

## 7. Business workflow coverage (code-reviewed, not yet runtime-verified)

| Requirement | Status |
|---|---|
| Super Admin: users, supervisors, agents, activate/deactivate, reset, sessions, activation links | Implemented |
| Clients & branches | Create + list. **No edit/deactivate endpoints** |
| Excel import + template | Implemented (no file-size cap) |
| Assign / reassign, agent accept / request reassignment | Implemented |
| Agent case requests → supervisor approve/reject/clarify/escalate → case | Implemented |
| Report forms per type, draft, submit with validation, blocked judgemental words, declaration | Implemented |
| Review: approve / return (comment mandatory) / inconclusive / exception / escalate; versions | Implemented |
| Word / PDF / Excel MIS / case list export | Implemented. **Photos not embedded**; masking for supervisors only |
| GPS flags (missing, low accuracy, distance, impossible travel, same place/time, late, no visit start), duplicate-photo flag | Implemented on the server from **client-reported** GPS |
| Audit log viewer, map, dashboard, incidents, retention | Implemented (retention doesn't delete files) |
| Push notifications when the app is closed | **Not implemented** (polling + local notifications only) |
| Credit/eligibility recommendations | Correctly absent; blocked words + disclaimer enforce this |

---

## 8. GPS, camera and evidence integrity

| ID | Severity | Finding |
|---|---|---|
| G1 | HIGH | **Offline photos aren't queued.** If an upload fails, the photo is lost and the agent must retake it. Only text drafts are stored offline and synced. The UI doesn't claim photos sync, but the "draft saved offline" message may be read that way (`camera.tsx:48-72`) |
| G2 | MEDIUM | `captured_at` is set when "Use Photo" is tapped, not at the shutter; GPS is read **once when the camera screen opens**, not at capture (`camera.tsx:28-33,55`), so it can be stale |
| G3 | MEDIUM | No mock-location detection. expo-location exposes `coords.mocked` on Android, but it isn't read or sent. Must not be described as anti-spoofing today |
| G4 | MEDIUM | GPS status isn't distinguished on the server: "denied", "unavailable" and "poor accuracy" all collapse into "no GPS" / `missing_gps`. The client result type (`geo.ts`) already has `denied`/`unavailable` |
| G5 | MEDIUM | Offline drafts: AES-CTR with a **fixed counter (nonce reuse) for every draft and save**, and no integrity tag (`drafts.ts:24-35`). Use AES-GCM with a random nonce, or rely on SecureStore for small payloads |
| G6 | LOW | Duplicate detection is exact SHA-256 only (re-encoded copies aren't caught); no EXIF read |
| OK | — | Camera-only capture (gallery blocked), permission flows, server SHA-256, evidence ↔ case binding, flags go to human review (no auto-reject) |

**Must be tested on a real Android device:** camera, location permission flows, GPS accuracy indoors/outdoors, `mocked` flag, background/killed-app notifications, SecureStore, offline → online draft sync, large-photo upload on mobile data.

---

## 9. Frontend & Android

| ID | Severity | Finding |
|---|---|---|
| F1 | HIGH | No `frontend/.env` / `.env.example`; `EXPO_PUBLIC_BACKEND_URL` is required (B4) |
| F2 | HIGH | Package ID / scheme / slug are Emergent placeholders (E5); `version` 1.0.0 with no `android.versionCode` policy |
| F3 | HIGH | No `eas.json` / release build config; no signing key plan. Needs EAS Build (cloud) or `expo prebuild` + Gradle locally |
| F4 | MEDIUM | `userInterfaceStyle`, splash and icons are generic; check `assets/images` for template React logos (`react-logo*.png`, `partial-react-logo.png`, unused) |
| F5 | MEDIUM | Native file downloads not supported ("available on the web dashboard") — fine for agents, document it |
| F6 | LOW | 2 TS errors (B7); preinstall guard (E6) |

**API URL by environment** (to document in `ENVIRONMENT_CONFIGURATION.md`):

| Target | `EXPO_PUBLIC_BACKEND_URL` |
|---|---|
| Web dev on the same PC | `http://localhost:8001` |
| Android emulator | `http://10.0.2.2:8001` |
| Physical phone on Wi-Fi | `http://<PC LAN IP>:8001` (backend started with `--host 0.0.0.0`; Windows firewall rule) |
| Production APK / web | `https://api.<your-domain>` (baked in at build time — the APK must be built with the prod value) |

---

## 10. Environment variable inventory (values not shown)

| Variable | Where | Used by code? | Required | Notes |
|---|---|---|---|---|
| `MONGO_URL` | backend/.env | Yes `core.py:17` | Yes | Atlas SRV string. Secret |
| `DB_NAME` | backend/.env | Yes `core.py:19` | Yes | Use `checksphere_dev` / `checksphere_test` / `checksphere` (prod) |
| `MONGODB_USERNAME`, `MONGODB_PASSWORD`, `MONGODB_URI` | backend/.env | **No** | — | Atlas onboarding leftovers. Delete (duplicate secrets) |
| `JWT_SECRET` | missing | Yes `security.py:15` | **Yes** | ≥ 64 random chars, different per environment |
| `ACCESS_HOURS` | — | Yes | Optional (12) | |
| `COMPANY_NAME` | — | Yes `core.py:21` | Optional | Your company name for reports |
| `INTEGRATION_PROXY_URL`, `EMERGENT_LLM_KEY`, `STORAGE_APP` | — | Yes (storage) | To be **removed** | Replaced by the storage vars below |
| *(new)* `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | backend/.env only | to add | Yes (for media) | From Cloudinary Console → Settings → API Keys. Secret is **backend only**. Never put it in `EXPO_PUBLIC_*`, the frontend, the APK or Git. Use separate keys or a separate product environment for production |
| *(new)* `MEDIA_FOLDER_ENV` | backend/.env | to add | Optional (= `APP_ENV`) | `dev`/`staging`/`prod` segment of public IDs |
| *(new)* `MAX_IMAGE_MB`, `MAX_DOC_MB`, `DOWNLOAD_LINK_TTL_SECONDS` | backend/.env | to add | Optional (10 / 15 / 120) | |
| *(new)* `APP_ENV`, `SEED_DEMO_DATA`, `CORS_ORIGINS`, `RUN_SCHEDULER`, `LOG_LEVEL`, `BACKUP_ENCRYPTION_KEY` | — | to add | | `BACKUP_ENCRYPTION_KEY` is only needed if in-app encrypted exports are enabled |
| `EXPO_PUBLIC_BACKEND_URL` | frontend/.env (missing) | Yes `api.ts:7` | Yes | Public. **Never put secrets in `EXPO_PUBLIC_*`** — they're bundled into the APK |

`.gitignore` already excludes `.env`, `.env.*`, `*.env`, `*.key`, `*.pem`, `*.jks`. Verified that `backend/.env` was **never committed** (`git log --all` is empty for it). `.env.example` files need a `!.env.example` exception.

**Minimal runtime requirements** (from actual imports): fastapi, uvicorn[standard], motor/pymongo, pydantic, python-dotenv, bcrypt, PyJWT, python-multipart, openpyxl, python-docx, reportlab, pillow, segno, **cloudinary** (official SDK; the version is pinned at install time), + pytest/httpx (dev). `requests` is dropped once the Emergent client is gone.

---

## 11. Security summary (OWASP API Top 10 mapping)

| OWASP | Findings |
|---|---|
| API1 Broken Object Level Authz | A2 (CRITICAL), A7 |
| API2 Broken Authentication | A1, A3, A5, A6 |
| API3 Broken Object Property Level Authz | A4 (masking leak), A11 |
| API4 Unrestricted Resource Consumption | no rate limits; uploads read fully into memory; Excel import uncapped; backup `to_list(100000)` |
| API5 Broken Function Level Authz | OK — role guards consistently applied |
| API8 Security Misconfiguration | CORS `*`, public `/docs`, no security headers, inline client MIME |
| API9 Improper Inventory | ~60 unused packages; Emergent artefacts |
| API10 Unsafe consumption | Excel parsing of uploaded files (admin only) |
| MASVS-STORAGE | Token in SecureStore on Android (good); drafts weakly encrypted (G5); web token in localStorage |
| Logging | Audit log is good. App logs use `%s` of exceptions; make sure no PII/secret ends up in logs; the file token currently does |

**DPDP (India).** The Digital Personal Data Protection Act, 2023 and the DPDP Rules, 2025 (notified November 2025, with most obligations commencing in phases, roughly 12–18 months after notification) are relevant. For CheckSphere you are most likely a **Data Processor** acting for bank clients (the Data Fiduciaries), so your contract terms with them govern a lot. Practical controls this codebase needs regardless: purpose-limited collection, a retention that really deletes (files included), breach-detection and notification readiness (audit + incident module exists), access logging (exists), encryption at rest (Cloudinary-managed storage + Atlas encryption), the cross-border question for media (§5.6), and data-subject request handling through the client. *This is not a legal compliance opinion. Confirm the obligations and dates with counsel, and check your client contracts and any RBI outsourcing requirements they pass down to you.*

---

## 12. Background jobs & notifications

| ID | Severity | Finding |
|---|---|---|
| J1 | HIGH | Jobs run inside every API worker. With `--workers N` or more than one container, backups and alerts run N times (duplicate notifications). There's no leader lock |
| J2 | MEDIUM | `alert_task` isn't cancelled on shutdown (`server.py:92-98`); `@app.on_event` is deprecated (use lifespan) |
| J3 | MEDIUM | Failures are only an `ERROR` line every hour/5 min. There's no last-run status in the DB and no admin alert |
| J4 | INFO | 24h/48h alerts are keyed on `updated_at`, not `due_at`, so any edit resets the clock |
| J5 | INFO | Daily MIS is generated **on demand** only; there's no scheduled MIS job despite the requirement |

Fix: a `RUN_SCHEDULER=true` flag on exactly one process plus a Mongo lease lock (`job_locks` collection with TTL); a `job_runs` collection with status; lifespan handler.

---

## 13. Deployment blockers

1. B1/A1 (JWT secret), B2 (storage), A2 (IDOR), A3/D1 (seeding), A4 (masking).
2. No Dockerfile / process manager / reverse proxy config; no HTTPS termination.
3. No staging/prod environment separation.
4. APK identity and signing (F2, F3).
5. Backup/restore isn't proven (§4).

---

## 14. Prioritised implementation plan (Phase B — needs your approval)

All work goes on a new branch `independence/phase-b`, one commit per item. Effort: S ≈ < ½ day, M ≈ 1 day, L ≈ 2–3 days.

**Stage 1 — Make it run locally and close the critical holes**
| # | Item | Fixes | Effort |
|---|---|---|---|
| 1 | `config.py`: load and validate env at startup (fail fast with clear messages), `APP_ENV`; `backend/.env.example`, `frontend/.env.example`; trim `requirements.txt` (+ `requirements-dev.txt`) | A1, B1, D5, E2–E4, F1 | S |
| 2 | **Cloudinary media service** (`media_service.py`, behind a small interface): upload image/raw with `type=authenticated`, eager thumbnail, verify bytes+etag, metadata/`resource` lookup, `private_download_url` links (≤ 120 s), streamed retrieval, `destroy`+invalidate, retries with backoff, structured logs. Remove the Emergent client. Validation: extension + magic bytes + size caps; idempotent `upload_id`; SHA-256 duplicate handling; `nosniff`, safe `Content-Disposition`. Rewire `evidence_routes`, `requests_routes`, retention, startup. Legacy-row marking script (dry-run first). A fake in-memory backend is used **only** in automated tests | B2, E1, §5 | L |
| 3 | Fix scope override: always AND role scope with filters (`cases`, `exports`, `dashboard`); supervisor write checks; regression tests | A2, A7 | S |
| 4 | Strip raw `report.data` when masked | A4 | S |
| 5 | Seeding only in dev with `SEED_DEMO_DATA=true`; `create_superadmin` CLI | A3, D1 | S |
| 6 | Rewrite tests to start the app in-process against `checksphere_test` (never the dev/prod DB); run them | B6, E8 | M |

**Stage 2 — Hardening**
| 7 | Login rate limit + progressive lockout; CORS allowlist; disable docs in prod; security headers | A5, A9, A10 | S |
| 8 | Replace `?token=` with 60 s single-purpose file tickets; admin/supervisor `download-link` endpoint issuing ≤ 120 s Cloudinary `private_download_url` (§5.4) | A6 | S |
| 9 | Jobs: lifespan, `RUN_SCHEDULER`, Mongo lease lock, `job_runs` status. Backups per §5.11: `mongodump` + encryption scripts, **restore script with dry-run**, in-app export of all collections (incl. `counters`) encrypted before any optional Cloudinary upload. Retention destroys Cloudinary assets | J1–J3, §4, §5.11 | M |
| 10 | Missing indexes, DB timeouts, `/health` + `/health/ready` with a DB ping | D3, D4 | S |

**Stage 3 — Field integrity & app**
| 11 | Capture GPS + timestamp at the shutter; send `mocked`, permission status and accuracy; server stores a `gps_status` enum and flags `possible_mock_location` for review | G2–G4 | M |
| 12 | Persistent offline photo queue (file + metadata in app storage, idempotent upload key, retry, visible "pending uploads" count) | G1 | L |
| 13 | Draft encryption → AES-GCM random nonce, with migration of existing drafts | G5 | S |
| 14 | Embed evidence photos (with GPS/time captions) in DOCX/PDF; masking options in exports | §5, §7 | M |
| 15 | `app.json` identity, `eas.json` (dev/preview/production profiles), versioning, signing guide | E5, F2, F3 | S |

**Stage 4 — Documentation & deployment design** (no resources created without your approval)
| 16 | `README.md`, `LOCAL_DEVELOPMENT.md` (PowerShell), `ENVIRONMENT_CONFIGURATION.md`, `PRODUCTION_DEPLOYMENT.md`, `ANDROID_BUILD.md`, `BACKUP_AND_RECOVERY.md`, `SECURITY_CHECKLIST.md`; Dockerfile | — | M |

**Proposed production architecture (for approval later):** API hosting in an Indian region next to Atlas Mumbai. The hosting provider is still open; an AWS Mumbai compute example is shown, and Amazon S3 is **not** used. The API runs as a Docker container (start: one EC2/Lightsail instance with Caddy for automatic HTTPS; grow: ECS Fargate behind an ALB with 2 tasks + a separate scheduler task). The web dashboard is a static Expo web export served by the same Caddy (or any static host). Evidence and documents go to **Cloudinary as authenticated assets** (separate production product environment; see the residency note in §5.6). Atlas is a dedicated tier (M10+) with continuous backup, IP access list restricted to the API's egress IP, and a separate DB user per environment. Dev, staging and prod each get their own DB, Cloudinary environment/folder and secrets. APKs are distributed privately (signed APK via a link on your company site/MDM). Agents only ever reach `https://api.<domain>`.

---

## 15. What was tested in this audit

| Check | Result |
|---|---|
| `python -m py_compile backend/*.py` (Python 3.13.3 venv) | Pass |
| `pip check` | Pass (no broken requirements); `emergentintegrations` not installed; `litellm 1.80.0` installed but unused |
| JWT signing with an empty secret (PyJWT 2.15.1) | **Fails** with `InvalidKeyError` → confirms B1 |
| `npx tsc --noEmit` (frontend) | 2 errors (`phoneAlerts.ts:39,44`) |
| Existing pytest suites | **Not run.** They're live-HTTP tests that write users/cases into whatever DB the backend uses, and they hardcode `/app/...` Linux paths. Running them now would put test data into your Atlas DB. Item 6 fixes this first |
| Emergent's own `test_reports/` | Not relied on |
| Android device / emulator | Not tested (manual) |
| Production | Nothing deployed or created |

---

## 16. External accounts you will need (later stages)

| Need | Where | When |
|---|---|---|
| `JWT_SECRET` | Generate locally: `python -c "import secrets;print(secrets.token_urlsafe(64))"` | Now (Stage 1) |
| Cloudinary account (cloud name, API key, API secret). Check the plan's upload size limits and whether PDF delivery is restricted (Console → Settings → Security). Ideally a separate product environment for production | cloudinary.com → Console → Settings → API Keys | **Stage 1 item 2: needed for real upload tests.** Put the values only in `backend/.env` |
| Sign-off on US storage of applicant media (§5.6) | Your client contracts / counsel | Before production |
| Separate Atlas databases/users for dev, test, prod; production cluster tier with backups | MongoDB Atlas | Before production |
| Domain + DNS | Your registrar | Before production |
| Expo account (for EAS Build) or a local Android SDK; an upload/signing keystore stored safely | expo.dev / Android Studio | Stage 3 item 15 |
| (Optional) Expo push / Firebase project for closed-app notifications | expo.dev / Firebase | If remote push is wanted |

---

## 17. Cloudinary verification test plan

A test is marked **passed** only when a real upload or download against your Cloudinary account behaves as listed. SDK initialisation alone doesn't count.

| # | Test | Type | Expected result |
|---|---|---|---|
| 1 | Authenticated image upload | Automated (pytest against a local backend + real Cloudinary dev environment) | Asset has `type=authenticated`, `resource_type=image`; Mongo row `stored`; bytes/etag match |
| 2 | Authenticated document upload (DOCX) | Automated | `resource_type=raw`, `type=authenticated` |
| 3 | PDF upload and retrieval | Automated | Upload OK; backend stream returns identical SHA-256; checked on your plan's PDF security setting |
| 4 | Authorised evidence retrieval (assigned agent) | Automated | 200, bytes match |
| 5 | Unauthorised access | Automated | Other agent → 403; out-of-scope supervisor → 403; no token → 401; **plain unsigned Cloudinary delivery URL fetched directly → 401/404** |
| 6 | Supervisor access (in scope) | Automated | 200 |
| 7 | Super Admin access | Automated | 200 |
| 8 | Signed link expiry | Automated (short TTL, e.g. 5 s, then wait) | Works before expiry, rejected after |
| 9 | Asset deletion | Automated | `destroy` OK; later fetch fails; Mongo row soft-deleted + audit entry |
| 10 | Upload failure handling | Automated (fault injection: bad credentials / forced timeout) | Clean 502, row `upload_failed`, no orphan; retry with the same `upload_id` succeeds once |
| 11 | Duplicate upload | Automated | Same case → existing record returned; other case → flag `duplicate_photo_cross_case` |
| 12 | Metadata persistence | Automated | All §5.7 fields present; no PII in public_id/context |
| 13 | Case ↔ evidence association | Automated | public_id contains the right `case_oid`; listing by case returns only its files |
| 14 | Android camera upload | **Manual, real Android device** | Photo appears in supervisor review with GPS/time |
| 15 | Uploads from different Indian states via the deployed backend | **Production/staging test, pending deployment** | Latency/success measured from field devices |

Tests 1–13 need a Cloudinary **dev** product environment (or a dev-only folder) and a separate test MongoDB database (`checksphere_test`). Test assets are deleted at the end of the run; only assets the tests created are touched.
