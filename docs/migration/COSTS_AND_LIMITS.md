# Free-plan limits, usage monitoring and cost safety

The figures below are from the providers' public pricing as known on 18-Nov-2026. **Check them on the pricing pages when you sign up**: Cloudflare R2 pricing, and Railway's Pricing and Plans pages. Plans change.

## Cloudflare R2

**Free each month:**
- 10 GB-month of storage
- 1,000,000 Class A operations (writes, lists)
- 10,000,000 Class B operations (reads)
- free egress (downloads)

**What CheckSphere uses:**
- **Storage per photo:** about 2 objects (camera original plus watermarked copy), typically 0.5–3 MB each.
  - Each case has 5 photos, so roughly 5–30 MB per case.
  - 10 GB holds roughly 350–2,000 cases of photos.
  - Production starts with no stored files: all test data was cleared on 18-Nov-2026.
- **Operations per photo:**
  - Through the API: about 2 writes and 2 HEADs.
  - Direct from the phone: about 4 writes (incoming PUT, original, watermarked, delete) and about 3 reads.
- **Reports:** each photo is read once and then served from the in-memory cache. Reports are cached by content hash and are rebuilt only when the case, report, evidence, settings or header changes.
- **Backups:** one JSON object per day.

**Important: R2 has no hard spending cap.**
- Usage above the free tier is billed to the payment method on the Cloudflare account. It is not refused.
- Cloudflare → R2 → **Metrics** shows storage and operations.
- Set **Billing → Notifications** (usage-based billing alert) to email you at a low threshold, for example $1.
- Check monthly. At CheckSphere's volume, the free tier should last a long time.

**What we avoid:**
- Duplicate copies: migrated files keep the same key, and `incoming/` objects are deleted after verification plus the 2-day lifecycle rule.
- Repeated downloads: in-memory photo cache.
- Repeated report builds: content-hash cache.

## Railway

**Plans:**
- New accounts get a one-time trial credit.
- After the trial, the **Free plan** gives a small monthly credit (about $1 at present) and small per-service resources (about 0.5 GB RAM).
- When the credit is used up, **services are stopped. Nothing is billed** unless you choose to upgrade.

**What CheckSphere uses:**
- Always-on, the backend uses credit continuously. Without sleep, the Free credit will likely run out partway through the month. Serverless mode (see `RAILWAY_DEPLOYMENT.md`) may reduce this; it must be measured.
- **RAM:** set `IMAGE_CACHE_MB=48` and `REPORT_CACHE_MB=32`. The defaults (200 + 150 MB) could exceed 0.5 GB with image processing and cause out-of-memory restarts.

**When the Railway allowance is exhausted:**
- The API becomes unreachable. The app shows "Server is starting up…", then a connection error after about 60 s of retries.
- **No upload is silently lost.**
  - Photos stay in the phone's private queue, under the same `upload_id`, until the server confirms them.
  - Drafts stay on the device.
  - Nothing is written to Railway's disk.
- Uploads resume automatically when the service runs again.
- The web dashboard cannot be used until then.

**Alerts and limits:**
- Railway's *usage limits* (custom email alert and hard limit) are available on paid workspaces.
- On the Free plan the credit itself is the hard limit.
- If you upgrade later (only with your approval), set **Workspace → Usage → Usage limits**: an email alert at a low amount and a hard limit, so a paid plan can never exceed a figure you choose.

## MongoDB Atlas
- Unchanged; your existing cluster.
- Two small new collections:
  - `pending_uploads` (TTL 48 h)
  - `idempotency_keys` (TTL 24 h)
