# CheckSphere: moving storage to Cloudflare R2 and hosting to Railway (plan for approval)

Status: **approved 18-Nov-2026 and implemented in the working tree. Nothing has been deployed, committed, or changed in any Cloudflare, Railway or Cloudinary account.**

**Superseded (18-Nov-2026, evening):** the test data was cleared and **Cloudinary was removed from CheckSphere entirely**: no code, dependency or variable remains, and R2 is the only storage provider. The Cloudinary migration and dual-read described below were never used on real data. `storage_migration.py` was deleted, and `verify_r2_migration.py` became `verify_r2_storage.py`. This document is kept as the historical plan; the current state is in `PRODUCTION_LAUNCH.md`.

**Superseded in part (18-Nov-2026, later the same day):** the owner confirmed that all existing data is test data. R2 is the permanent provider. The Cloudinary migration will not be run; the test data is cleaned up instead. See `PRODUCTION_LAUNCH.md` for the inventory, the cleanup procedure and the launch sequence.

Owner decisions (18-Nov-2026):
- R2 tests use a real private `checksphere-test` bucket.
- Atlas `0.0.0.0/0` is **temporary, for testing only**, and must not be used for production applicant data.
- Add the opt-in `SERVERLESS_MODE`.
- Implement everything as planned.

Correction after implementation: `railway.json` is **not used**. Railway deprecated Config as Code, and files stop being read on 2026-12-01. Settings go in the Railway dashboard; see `RAILWAY_DEPLOYMENT.md`.
Date: 18-Nov-2026

---

## 1. What exists today (findings)

| Area | Current behaviour | Where |
|---|---|---|
| Storage abstraction | One module, `storage_service.py`, with `object_path()`, `put_object_async()`, `get_object_async()`, `delete_object_async()`, `detect_type()`, `mime_for()`. All callers go through it. `PROVIDER = "cloudinary"`. | `backend/storage_service.py` |
| Evidence photos | The phone POSTs multipart to `/api/evidence/upload`. The backend validates by decoding the image, takes SHA-256 of the original, watermarks it, stores **two private Cloudinary assets** (original and watermarked), then inserts one `evidence` record. `upload_id` is unique-indexed, so retries never duplicate. | `evidence_routes.py:40-246` |
| Evidence record fields | `storage_path`, `storage_provider`, `cloudinary{…}`, `sha256` (original), `watermark.sha256` (stored file), `original{storage_path, sha256, size, format, cloudinary}`. | same |
| PDFs (new cases) | `/case-uploads`: PDF signature check, SHA-256, stored under `…/uploads/…`; the record holds `pdf.storage_path`, `pdf.sha256` and `pdf.storage_provider`. | `case_uploads_routes.py:93-158` |
| Request documents | `case_requests.documents[]` holds `path`, `sha256` and `storage_provider`. | `requests_routes.py:120-161` |
| Reads | Every read checks `storage_provider == storage_service.PROVIDER`. **If the provider string changes to "r2", all existing Cloudinary evidence returns 404 and drops out of reports.** That is the main migration hazard. | `evidence_routes.py:265`, `report_cache.py:77`, `requests_routes.py:153` |
| Reports | Photos are fetched in parallel and checked against `watermark.sha256`, then kept in an in-memory LRU cache (200 MB images, 150 MB reports). The report cache key is a content hash, so a change to a case already invalidates it. | `report_cache.py` |
| Backups | The daily JSON backup is written to the **local disk** (`backend/backups`). Railway disks are wiped on every redeploy, so this would lose backups. | `ops_routes.py:119-139` |
| Header | `exporters.DOCX_HEADER_IMAGE = assets/branding/aaditya_enterprise_header.jpg` is used by the Word builder and drawn on every PDF page by `vee_report.py:627-643`. There is a single constant, so swapping it is one change. | `exporters.py:122`, `vee_report.py` |
| Server | `/health` exists, but there is no Railway start command, no `PORT` binding and no graceful-shutdown settings. Startup logs "Cloudinary ready". | `server.py` |
| Frontend | `api()` has no retry or cold-start handling. A 502/503 is shown straight away as an error. The photo queue (`pendingUploads.ts`) already keeps the file on the phone and reuses `upload_id` on retry. Report submit is already protected: an atomic status claim returns 409 on a repeat. | `frontend/src/api.ts`, `src/utils/pendingUploads.ts`, `reports_routes.py:244-272` |
| Dependencies | `boto3`/`botocore` are already listed in `requirements.txt` but not installed in the current environment. The file also lists many packages the backend never imports (openai, stripe, google-genai, huggingface, pandas, mypy, black…). | `backend/requirements.txt` |

**About the attached image:** the image in your message is the existing **AADITYA ENTERPRISE** banner. It is identical in design to `assets/branding/aaditya_enterprise_header.jpg`. It is not `Header_CheckSphere`, so I will not switch headers until you send that file.

---

## 2. Files that need to change

### Backend: new files
- `backend/r2_storage.py`: the R2 client (boto3, S3 API, SigV4, `region_name="auto"`). Provides put, get, head, delete, presign-PUT and presign-GET.
- `backend/storage_migration.py`: the Cloudinary-to-R2 copy utility, run as a CLI (`python storage_migration.py --dry-run | --run | --retry-failed | --report`).
- `backend/railway.json`: Railway build and deploy configuration.
- `backend/Procfile`: fallback start command.
- `backend/.python-version`: pins Python for the Railway builder.
- `backend/tests/verify_r2_migration.py`: an isolated harness in the same style as the existing `verify_*.py` files.
- `docs/migration/RAILWAY_DEPLOYMENT.md` and `docs/migration/COSTS_AND_LIMITS.md`.

### Backend: changed files
- `storage_service.py` becomes a **provider router**:
  - New writes go to `STORAGE_PROVIDER` (default `r2` when the R2 variables are set).
  - Reads dispatch on each record's own `storage_provider` (`cloudinary` or `r2`).
  - The existing Cloudinary code stays, read-only for old records.
  - The function names stay the same, so most callers are unchanged.
- `evidence_routes.py`:
  - `get_file` reads from either provider, not only "the current" one.
  - New endpoints for direct upload: `POST /api/evidence/upload-url` and `POST /api/evidence/complete`.
  - The existing multipart endpoint is kept as a fallback, for the web dashboard and for app builds already installed on phones.
  - The generic `cloudinary` metadata key is renamed to `storage` on new records. Old records are untouched.
- `report_cache.py`: `evidence_bytes()` accepts either provider. Cache sizes become configurable through environment variables (see the RAM note in section 6).
- `requests_routes.py`, `case_uploads_routes.py`: read from either provider and write new files to R2.
- `ops_routes.py`: backups are written to the R2 bucket under `checksphere/<env>/backups/`. Local disk is used only when R2 is not configured, for local development.
- `server.py`:
  - Startup checks the configured providers.
  - New `/health/ready` endpoint that checks the database and storage. `/health` stays a cheap liveness check.
  - Graceful shutdown of the background loops.
  - `SERVER_BUILD` is bumped.
- `core.py`: optional `ALLOWED_ORIGINS` for CORS. The default stays as it is now, so nothing breaks.
- `exporters.py`, `vee_report.py`: the header path comes from one resolver. It uses `assets/branding/Header_CheckSphere.<ext>` once you approve it. Until then it falls back to the current AADITYA banner. The `BUILDER_VERSION` bump in `report_cache.py` makes cached reports rebuild.
- `.env.example`: R2 and Railway variables.
- `requirements.txt`:
  - Keep `boto3`.
  - Separately, **with your OK only**, add a trimmed `requirements-railway.txt` without the unused AI/Stripe/dev packages. That makes the Railway build faster and the image smaller.

### Frontend: changed files
A new APK (EAS build) is needed for the phone side.
- `src/api.ts`:
  - Cold-start handling: a "Server is waking up…" state.
  - Bounded retry with backoff on 502, 503, 504 and network errors, for **GET requests and idempotent calls only**.
  - Every POST sends an `Idempotency-Key` header.
- `src/utils/pendingUploads.ts`, `src/utils/upload.ts`:
  - Direct-to-R2 flow (authorise → PUT → complete) as a 3-stage state machine, stored per queued photo, so a retry resumes at the right stage.
  - The existing `upload_id` is reused as the idempotency key.
  - Falls back to multipart when the server does not offer direct upload.
- A small "waking server" banner component (`src/components/ui.tsx`), used by the login screen and the home screens.

**No changes:** authentication, case creation and assignment, Create/Allocate New Verification, GPS capture and distance checks, watermark rendering, reverse geocoding, drafts and autosave, VEE layouts, audit logging, retention logic (except where the bytes are stored).

---

## 3. Proposed R2 storage design

- **One private bucket**, e.g. `checksphere-prod`, plus a separate `checksphere-test` for tests. No public access, no `r2.dev` URL and no custom public domain.
- **Object keys keep today's format:** `checksphere/<env>/<kind>/<case-or-owner-id>/<uuid>.<ext>`.
  - Keys hold database ids only, never personal data.
  - Migrated Cloudinary files get **the same key as their existing `storage_path`**, so the database change during migration is only the provider flag plus migration metadata. The path, checksums and report cache keys stay the same.
- **Object metadata (`x-amz-meta-*`):** `sha256`, `case-id`, `slot`, `variant` (original / watermarked / pdf), `original-filename` (URL-encoded, 200 chars max). The original filename also stays in Mongo, as it does today.
- **Overwrites are blocked:** writes use `If-None-Match: *`, which R2 supports. An existing key can never be replaced, so the files stay immutable, as they are today.
- **Validation on every write:** size limit (10 MB), the real file signature (`detect_type` or a full image decode), MIME taken from the detected type and never from the client, SHA-256 computed server-side and stored. After the PUT, a HEAD confirms `ContentLength`. R2 also verifies the `ChecksumSHA256` value we send.
- **Direct mobile upload, the 7 steps you listed:**
  1. `POST /api/evidence/upload-url {case_id, slot, upload_id, size, sha256, content_type}` → the backend runs the same role, case-access, status and slot checks as today, and records a `pending_uploads` document keyed by `upload_id` with a TTL index.
  2. The backend returns a **presigned PUT, valid 10 minutes**, for exactly one key: `checksphere/<env>/incoming/<case>/<upload_id>.<ext>`. Content-Length and `x-amz-checksum-sha256` are signed into it, so R2 rejects a different file.
  3. The phone PUTs the bytes straight to R2.
  4. `POST /api/evidence/complete {upload_id, gps…, captured_at…}` → the backend downloads the incoming object, then:
     - re-checks size, signature and SHA-256;
     - decodes the image;
     - reverse-geocodes the location;
     - **watermarks it on the server, as today**;
     - stores the original and the watermarked copy as two final private objects;
     - inserts the evidence record (the unique `upload_id` still prevents duplicates);
     - deletes the `incoming/` object.
  5. If `complete` is retried, it returns the existing record.
  6. An R2 **lifecycle rule** deletes `incoming/` objects older than 2 days, so abandoned uploads never pile up.
- **Downloads:**
  - In-app viewing stays as it is: `/api/files/{id}` with the role check and an audit record, and the backend streams the bytes. App and web code don't change.
  - Optionally, for large originals and PDFs, the backend can answer with a **60-second presigned GET** after the same role check (`?redirect=1`).
  - Permanent R2 keys never leave the server.
- **Why the multipart path stays:**
  - The web dashboard and older installed APKs keep working.
  - It is also the safe fallback if the R2 CORS configuration is wrong for browsers.

---

## 4. Railway deployment configuration

`backend/railway.json` (the service's root directory is `backend`):
```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": { "builder": "RAILPACK" },
  "deploy": {
    "startCommand": "uvicorn server:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips=* --timeout-keep-alive 30 --timeout-graceful-shutdown 25",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 120,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 5
  }
}
```

- A single uvicorn worker, because the in-memory caches and background loops assume one process and the free plan's RAM is small.
- Railway sends SIGTERM on redeploy or sleep. Uvicorn stops accepting connections and lets in-flight requests finish (up to 25 s). Background loops are cancelled.
- An interrupted upload is safe:
  - multipart: the record is inserted only after both objects are stored;
  - direct: nothing is recorded until `complete` succeeds.
- No Windows paths. `ROOT_DIR` is already file-relative. Backups move to R2.
- Railway terminates HTTPS on `*.up.railway.app` or a custom domain. `--proxy-headers` gives the app the real scheme. `export_routes` already uses `x-forwarded-proto`.

### Required Railway environment variables
These go in Railway variables only, never in Git or `EXPO_PUBLIC_*`.

| Variable | Notes |
|---|---|
| `MONGO_URL`, `DB_NAME` | Atlas (Mumbai). |
| `JWT_SECRET` | A new random value for production. |
| `ACCESS_HOURS` | Optional. |
| `APP_ENV` / `MEDIA_FOLDER_ENV` | `prod`. |
| `STORAGE_PROVIDER` | `r2`. |
| `R2_ACCOUNT_ID` | Cloudflare account id. |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | An R2 API token with **Object Read & Write scoped to this one bucket**. |
| `R2_BUCKET` | e.g. `checksphere-prod`. |
| `R2_ENDPOINT` | `https://<account_id>.r2.cloudflarestorage.com`. Use the `.eu.` form only if you choose EU jurisdiction. |
| `R2_UPLOAD_URL_TTL_SECONDS` | Default 600. |
| `DOWNLOAD_LINK_TTL_SECONDS` | Default 60. |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | **Kept during the transition**, to read and migrate old files. |
| `ALLOWED_ORIGINS` | The web dashboard origin(s). |
| `GEOCODING_PROVIDER`, `GEOCODER_USER_AGENT`, `COMPANY_NAME` | Existing settings. |
| `IMAGE_CACHE_MB`, `REPORT_CACHE_MB` | Smaller on the free plan; see section 6. |
| `SEED_DEMO_DATA` | **Must be unset in production.** |

Frontend: `EXPO_PUBLIC_BACKEND_URL=https://<service>.up.railway.app`. It is public by design and is the only frontend change to environment variables.

---

## 5. Cloudinary migration strategy

1. **Dual read starts first.** It ships before anything is copied. Every read path dispatches on the record's own `storage_provider`. Old Cloudinary records keep working the whole time.
2. **New writes go to R2** once R2 is configured.
3. **Copy utility** (`storage_migration.py`, run manually by you or by me after your approval):
   - **Inventory:** every object reference in `evidence` (`storage_path` and `original.storage_path`), `case_uploads.pdf` and `case_requests.documents[]` where the provider is `cloudinary`. One document per object goes into a new `storage_migrations` collection (unique on collection + record id + field), with status `pending`.
   - **Per object:**
     1. Download from Cloudinary (the existing signed fetch).
     2. Compute SHA-256 and size.
     3. Compare with the stored checksum: `watermark.sha256` for the stored photo, `sha256`/`original.sha256` for the original and PDFs, and Cloudinary's recorded `bytes`/`etag`.
     4. PUT to R2 under the **same key**, with `If-None-Match: *`. If the key already exists with an equal SHA-256, it is treated as already copied, so retries are safe.
     5. HEAD and re-download from R2 to confirm the SHA-256 again.
     6. **Only then**, update the database record with a conditional update: match on `_id`, the old provider and the same path. It sets `storage_provider: "r2"` and `migration: {from: "cloudinary", at, sha256, verified: true}`, and keeps the old `cloudinary{…}` block **untouched** as provenance.
   - **Photos have two objects.** The record's provider flips only after **both** the original and the watermarked copy are verified. The per-file provider fields allow a partial state without a broken read.
   - **Statuses:**
     - `pending`
     - `copied`
     - `verified` (DB updated)
     - `failed` (error + attempt count)
     - `unverified`: the copy matches Cloudinary's bytes, but the record has no stored SHA-256 to compare with (possible for very old records). The DB is **not** flipped for these. They are listed for your decision.
   - `--retry-failed` reruns only the failed objects. Concurrency is limited (4). The run can be stopped and resumed at any time.
   - **No new evidence records** are ever created. Only existing records are updated, conditionally.
   - **Nothing is deleted from Cloudinary.** The utility has no delete code path.
4. **Migration report** (`--report`, as Markdown and JSON in `docs/migration/reports/`): totals by collection and by kind, then copied, verified, failed (with reasons), unverified, and bytes moved.
5. **Cloudinary stays enabled** until you explicitly approve disabling it. Even after that, the Cloudinary read code stays dormant until you also approve removing it. Deleting Cloudinary data is a separate step that needs your explicit approval.

---

## 6. Free-plan limits and expected behaviour

Figures are from current public pricing as I know it. **Check them on the Cloudflare and Railway pricing pages when you sign up.** Both providers change their plans.

### Cloudflare R2 (free tier, per month)
- 10 GB-month of storage.
- 1 million Class A operations (writes, lists).
- 10 million Class B operations (reads).
- **Egress is free.**
- Beyond the free tier, usage is billed to the card on file. R2 needs a payment method on the Cloudflare account even for free use.
- There is **no hard cap**. Usage is not refused at the limit; it is billed. So I will document the dashboard checks and a monthly billing notification. We should stay well inside the limits:
  - each photo is about 2 objects of about 0.5–3 MB;
  - each direct upload costs about 4 Class A and 2 Class B operations.

### Railway
- New accounts get a trial credit. After that, the **Free plan** gives a small monthly credit (about $1 at present) and small per-service limits (about 0.5 GB RAM).
- When the credit runs out, **services are stopped. They are not billed** unless you upgrade.
  - The API then returns errors or is unreachable.
  - The phone queue keeps photos on the device and uploads them later, so no upload is silently lost.
  - Drafts stay on the device.
- **RAM risk:** today's in-memory caches can grow to 350 MB, plus image decoding. On a 0.5 GB service that can cause an out-of-memory restart. On Railway I will set `IMAGE_CACHE_MB≈48` and `REPORT_CACHE_MB≈32`.
- **Hard spending limits / usage alerts:** Railway's usage-limit settings are on paid workspaces (Hobby and above). On Free, the credit itself is the cap. I will document both and **will not upgrade anything.**
- **No static outbound IP on Free:** MongoDB Atlas network access would have to allow `0.0.0.0/0`. That relies on the strong database user password and TLS. Railway's static IPs are a paid feature. **This is a security trade-off for you to accept or reject.**
- Ephemeral disk: handled by moving backups to R2. Nothing permanent is written locally.

### Railway Serverless (sleep)
- Enabled per service in Settings → Serverless. The service sleeps after about 10 minutes **with no outbound traffic**, and the first inbound request wakes it.
- **Important finding:** the backend keeps outbound traffic going all the time:
  - MongoDB driver heartbeats, about every 10 s;
  - the hourly backup check;
  - the geocode loop;
  - the pending-request alert loop.
- With the current code, **the service will most likely never sleep**, and it uses free credit around the clock. Options for you to choose from (I will not add any keep-alive):
  - **(a)** Accept always-on.
  - **(b)** An opt-in `SERVERLESS_MODE=true`. The loops then run on demand (triggered by real API traffic, at most once per interval) instead of on timers, and the Mongo client uses a longer heartbeat. Mongo heartbeats still count as outbound traffic, so sleep is still not guaranteed; I would measure it on Railway.
- **Cold-start UX:** the app shows "Server is waking up…" and retries GET requests (and logins, which are safe to repeat) with backoff for up to about 60 s. Uploads go through the queue, which is idempotent by `upload_id`. Submissions are already protected by the atomic status claim (409 on a repeat). A new `Idempotency-Key` header also makes case creation and allocation return the first result instead of creating a second case.

---

## 7. Header_CheckSphere
- I am waiting for the real `Header_CheckSphere` file. **I will not draw or invent one.**
- Once it arrives:
  - it is stored byte-for-byte in `backend/assets/branding/`, and the README marks it as a protected asset;
  - it is used for Word (page header, every page) and PDF (drawn on every page) through a single resolver;
  - the aspect ratio is kept, it is fitted to the margin width, and the top margin is computed so the body never overlaps it;
  - `BUILDER_VERSION` is bumped and the samples are regenerated for you to approve.
- After you approve it, the AADITYA fallback is removed from the code path. The old file stays in the repo unless you ask for it to be removed.

---

## 8. Test plan
Test data only, against a throwaway local MongoDB and a **test bucket**. The real Atlas database is read-only; the migration dry run only reads it.

I will cover tests 1–12 from your list with a new `verify_r2_migration.py` plus the existing harnesses. Some things cannot be tested from this PC:
- **Not testable here:** Railway sleep and wake (needs a real deployment, which requires your approval) and a real Android device (needs a new EAS build).
- **Simulated here instead:** cold start, by stopping and restarting the local server during app retries.
