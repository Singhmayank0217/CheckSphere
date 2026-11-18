# Deploying the CheckSphere backend on Railway

**Nothing has been deployed.** Each step below is done by you in the Railway and Cloudflare dashboards. Do not deploy publicly, upgrade a plan, or enter payment details until you have decided to.

## Why there is no `railway.json`

Railway's docs (checked 18-Nov-2026) say Config as Code (`railway.json` / `railway.toml`) is deprecated. Existing files stop being read on **2026-12-01**.

Its replacement, Infrastructure as Code (`.railway/railway.ts`), cannot set the root directory or Serverless, and it is applied with `railway config apply`, which is itself a deployment action.

So the settings below are entered once in the service's **Settings** page. The repo carries only:
- `backend/Procfile`: start command; Railpack uses it if the dashboard field is empty.
- `backend/.python-version`: Python 3.13, the same as the local venv.

## 1. Cloudflare R2 (do this first)

1. Cloudflare dashboard → R2 → **Create bucket**.
   - Names: `checksphere-test` (for testing) and later `checksphere-prod`.
   - Location: Automatic, or the Asia-Pacific hint.
   - **Do not** enable the public `r2.dev` URL or a custom public domain. The bucket stays private.
2. Bucket → Settings → **Object lifecycle rules** → add the rule "Delete objects with prefix `checksphere/` … `/incoming/` after 2 days". Abandoned direct uploads are then removed automatically. Only `incoming/` objects are temporary; never add a rule for other prefixes.
3. R2 → **Manage API tokens** → Create token:
   - Permission: *Object Read & Write*.
   - Scope: *Apply to specific buckets only* → the one bucket.
   - Copy the Access Key ID and Secret Access Key **straight into Railway variables** (or `backend/.env` for local tests). Never paste them into chat, Git or `EXPO_PUBLIC_*`.
4. Note your Account ID (R2 overview page). The endpoint is `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.
5. CORS is **not** needed. The phone app is not a browser, and the web dashboard uploads through the API.

## 2. MongoDB Atlas network access

- Railway's Free plan has no static outbound IP.
- For **testing only**, Atlas → Network Access → add `0.0.0.0/0`, with the comment "TEMPORARY Railway test – remove before production".
- **Risk:** the cluster is then reachable from any IP. It is protected only by the database user's password and TLS.
- Use a dedicated, strong, least-privilege Atlas user for Railway: `readWrite` on the CheckSphere database only.
- **Owner decision (18-Nov-2026):** this arrangement must not be used for production applicant data. Before production, replace it with a static-IP option (Railway paid feature) or Atlas private networking, and remove `0.0.0.0/0`.

## 3. Create the Railway service

1. Railway → New Project → **Deploy from GitHub repo**. This requires the code to be pushed. Pushing needs your approval; nothing has been pushed.
2. Service → Settings:
   | Setting | Value |
   |---|---|
   | Root Directory | `backend` |
   | Builder | Railpack (default) |
   | Custom Start Command | `uvicorn server:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips=* --timeout-keep-alive 30 --timeout-graceful-shutdown 25` |
   | Healthcheck Path | `/health` |
   | Healthcheck Timeout | `120` |
   | Restart Policy | On Failure, 5 retries |
   | Replicas | 1 (in-memory caches and background jobs assume one process) |
   | Region | the one closest to Mumbai that your plan offers (Southeast Asia) |
   | Serverless | see section 5 |
3. Networking → **Generate Domain**. This gives `https://<name>.up.railway.app`, with HTTPS terminated by Railway. `--proxy-headers` passes the real scheme to the app. Generating the domain makes the API publicly reachable, so do it only when you are ready to test.

## 4. Variables (Service → Variables)

Secrets live only here.

| Variable | Value |
|---|---|
| `MONGO_URL` | Atlas connection string (Railway user) |
| `DB_NAME` | `checksphere` (or a test database name) |
| `JWT_SECRET` | new random value: `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `APP_ENV` | `prod` (or `test`) |
| `MEDIA_FOLDER_ENV` | same as `APP_ENV` |
| `R2_ACCOUNT_ID` | Cloudflare account id |
| `R2_ACCESS_KEY_ID` | from the bucket-scoped token |
| `R2_SECRET_ACCESS_KEY` | from the bucket-scoped token |
| `R2_BUCKET` | `checksphere-test` / `checksphere-prod` |
| `R2_ENDPOINT` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
| `ALLOWED_ORIGINS` | web dashboard origin(s), comma-separated; `*` until the dashboard is hosted |
| `IMAGE_CACHE_MB` | `48` (Free plan RAM is small) |
| `REPORT_CACHE_MB` | `32` |
| `SERVERLESS_MODE` | `true` only if Serverless is enabled (section 5) |
| `DIRECT_UPLOAD_ENABLED` | `true`; set `false` to force uploads through the API without a new APK |
| `GEOCODER_USER_AGENT` | an identifying string, as before |
| `SEED_DEMO_DATA` | **must not be set** |

Optional:
- `R2_UPLOAD_URL_TTL_SECONDS` (default 600)
- `DOWNLOAD_LINK_TTL_SECONDS` (default 60)
- `ACCESS_HOURS`
- `COMPANY_NAME`
- `GEOCODING_PROVIDER`

**Storage:** Cloudflare R2 is the only storage provider. Every photo, original, PDF, request document and backup is stored there; there are no other storage variables.

## 5. Serverless (sleep), optional

- Service → Settings → **Serverless** → enable. Railway puts the service to sleep after about 10 minutes **with no outbound traffic**, and the next request wakes it.
- Set `SERVERLESS_MODE=true` at the same time. The backend then:
  - runs backups, pending alerts and geocoding **on demand**, triggered by real API requests, at most once per 1 h / 5 min / 1 min, instead of on timers;
  - polls MongoDB every 15 min (`MONGO_HEARTBEAT_MS`) instead of every 10 s;
  - closes idle database connections after 60 s.
- **Not guaranteed:** the MongoDB driver keeps one monitoring socket open, and its TCP keep-alive packets may still count as outbound traffic. Whether the service actually sleeps has to be **measured on Railway** after the first deployment (watch the service's sleep indicator and the metrics).
- There is deliberately **no keep-alive or self-ping** anywhere in the code.
- **Cold start in the app:**
  - Requests that hit a sleeping or starting server (network error, 502/503/504) are retried with backoff for about 60 s. Meanwhile a "Server is starting up…" banner shows on every screen.
  - Every POST carries an `Idempotency-Key`, so a retried case creation, allocation or submission returns the first result instead of creating a duplicate.
  - Photos always go through the on-device queue, keyed by `upload_id`.

## 6. After deploying (smoke test)

0. `railway run python prelaunch_check.py` (read-only) must report **0 blocking** items: production bucket, no published demo passwords, a Super Admin present, and so on.

1. `GET https://<domain>/health` → `{"status":"ok","build":"2026-11-18.r2-railway-v1"}`.
2. `GET https://<domain>/health/ready` → `database: ok` and `storage.r2: ok`.
3. Log in as each role on the web dashboard and on the phone.
   - Set `EXPO_PUBLIC_BACKEND_URL=https://<domain>` in `frontend/.env`. It is public, never a secret.
   - Build a new APK with EAS.
4. Upload a test photo to a **test** case. Then check:
   - the evidence record has `storage_provider: "r2"`;
   - the photo views;
   - the Word and PDF reports embed it.

## 7. Usage alerts and spending

See `COSTS_AND_LIMITS.md`. Nothing in this setup upgrades a plan or adds a payment method on your behalf.
