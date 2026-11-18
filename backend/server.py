"""CheckSphere API server."""
import asyncio
import logging
import os
from contextlib import suppress

from fastapi import APIRouter, FastAPI
from pymongo import ASCENDING, DESCENDING, IndexModel
from starlette.middleware.cors import CORSMiddleware

import core
import storage_service
import auth_routes
import admin_routes
import cases_routes
import reports_routes
import evidence_routes
import dashboard_routes
import export_routes
import audit_routes
import ops_routes
import requests_routes
import case_uploads_routes
import background
import idempotency
from seed import seed_if_empty

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

INDEXES: dict[str, list[IndexModel]] = {
    "users": [IndexModel([("agent_id", ASCENDING)], name="agent_id", unique=True, sparse=True),
              IndexModel([("email", ASCENDING)], name="email", unique=True, sparse=True),
              IndexModel([("role", ASCENDING)], name="role")],
    "sessions": [IndexModel([("user_id", ASCENDING)], name="user_id"),
                 IndexModel([("expires_at", ASCENDING)], name="expires_at", expireAfterSeconds=0)],
    "cases": [IndexModel([("internal_case_id", ASCENDING)], name="internal_case_id", unique=True),
              IndexModel([("assigned_agent_id", ASCENDING)], name="assigned_agent_id"),
              IndexModel([("status", ASCENDING)], name="status"),
              IndexModel([("created_at", DESCENDING)], name="created_desc"),
              IndexModel([("client_id", ASCENDING)], name="client_id")],
    "reports": [IndexModel([("case_id", ASCENDING), ("version", DESCENDING)], name="case_version")],
    "evidence": [IndexModel([("case_id", ASCENDING)], name="case_id"),
                 IndexModel([("sha256", ASCENDING)], name="sha256"),
                 IndexModel([("upload_id", ASCENDING)], name="upload_id", unique=True, sparse=True)],
    "call_logs": [IndexModel([("case_id", ASCENDING)], name="case_id")],
    "audit_logs": [IndexModel([("created_at", DESCENDING)], name="created_desc")],
    "case_uploads": [IndexModel([("submitted_by", ASCENDING), ("submitted_at", DESCENDING)], name="submitted_by"),
                     IndexModel([("status", ASCENDING)], name="status"), IndexModel([("state", ASCENDING)], name="state")],
    # direct-to-R2 upload authorisations; expired ones are removed by MongoDB (TTL)
    "pending_uploads": [IndexModel([("upload_id", ASCENDING)], name="upload_id", unique=True),
                        IndexModel([("expires_at", ASCENDING)], name="expires_at", expireAfterSeconds=0)],
    "idempotency_keys": [IndexModel([("expires_at", ASCENDING)], name="expires_at", expireAfterSeconds=0)],
}


async def ensure_indexes() -> None:
    for collection, models in INDEXES.items():
        for model in models:
            try:
                await core.db[collection].create_indexes([model])
            except Exception as exc:
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)


SERVER_BUILD = "2026-11-18.r2-railway-v1"  # shown on the app's login screen; bump on each backend release

app = FastAPI(title="CheckSphere API")

# ALLOWED_ORIGINS: comma-separated web dashboard origins (e.g. https://dashboard.example.com). Default "*" as before;
# the Android app is not a browser and is unaffected by CORS.
_origins = [o.strip() for o in (os.environ.get("ALLOWED_ORIGINS") or "*").split(",") if o.strip()]
app.add_middleware(idempotency.IdempotencyMiddleware)
app.add_middleware(background.TriggerMiddleware)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=_origins,
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition", "Idempotent-Replay"])


@app.get("/health", include_in_schema=False)
@app.head("/health", include_in_schema=False)
async def health():
    """Liveness: answers as soon as the process is up (Railway health check, app wake-up probe). No DB call."""
    return {"status": "ok", "build": SERVER_BUILD}


@app.get("/health/ready", include_in_schema=False)
async def health_ready():
    """Readiness: database reachable and storage configured. 503 when not ready."""
    from fastapi.responses import JSONResponse
    db_ok = True
    try:
        await asyncio.wait_for(core.client.admin.command("ping"), 5)
    except Exception:
        db_ok = False
    storage = getattr(app.state, "storage_status", {}) or {}
    wp = storage.get("write_provider")
    ok = db_ok and storage.get(wp) == "ok"
    return JSONResponse({"status": "ok" if ok else "degraded", "build": SERVER_BUILD, "database": "ok" if db_ok else "error",
                         "storage": storage, "serverless_mode": core.SERVERLESS_MODE}, status_code=200 if ok else 503)


api_router = APIRouter(prefix="/api")
for module in (auth_routes, admin_routes, cases_routes, reports_routes, evidence_routes,
               dashboard_routes, export_routes, audit_routes, ops_routes, requests_routes, case_uploads_routes):
    api_router.include_router(module.router)
app.include_router(api_router)


@app.on_event("startup")
async def startup():
    app.state.index_task = asyncio.create_task(ensure_indexes())
    try:
        app.state.storage_status = await storage_service.init_storage_async()
        logger.info("media storage: %s", app.state.storage_status)
    except Exception as exc:
        app.state.storage_status = {"error": type(exc).__name__}
        logger.error("media storage NOT ready (uploads/downloads will fail): %s", exc)
    # Demo users/cases are only ever created when explicitly enabled AND the database is a local throwaway one
    # (seed.seeding_allowed refuses Atlas/production, so demo logins can never appear in production).
    if os.environ.get("SEED_DEMO_DATA", "").strip().lower() == "true":
        try:
            created = await seed_if_empty()
            if created:
                logger.warning("Demo data seeded (local throwaway database only)")
        except Exception as exc:
            logger.error("Seed not run: %s", exc)
    background.start()


@app.on_event("shutdown")
async def shutdown():
    """SIGTERM (Railway redeploy / sleep): uvicorn stops accepting connections and lets in-flight requests finish
    (--timeout-graceful-shutdown), then this runs. Uploads are recorded only after their files are stored, so an
    interrupted upload leaves no evidence record and the app's queue retries it with the same upload_id."""
    app.state.index_task.cancel()
    with suppress(asyncio.CancelledError):
        await app.state.index_task
    await background.stop()
    core.client.close()
