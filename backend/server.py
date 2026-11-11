"""CheckSphere API server."""
import asyncio
import logging
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
                 IndexModel([("sha256", ASCENDING)], name="sha256")],
    "call_logs": [IndexModel([("case_id", ASCENDING)], name="case_id")],
    "audit_logs": [IndexModel([("created_at", DESCENDING)], name="created_desc")],
}


async def ensure_indexes() -> None:
    for collection, models in INDEXES.items():
        for model in models:
            try:
                await core.db[collection].create_indexes([model])
            except Exception as exc:
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)


app = FastAPI(title="CheckSphere API")

app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


@app.get("/health", include_in_schema=False)
@app.head("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


api_router = APIRouter(prefix="/api")
for module in (auth_routes, admin_routes, cases_routes, reports_routes, evidence_routes,
               dashboard_routes, export_routes, audit_routes, ops_routes, requests_routes):
    api_router.include_router(module.router)
app.include_router(api_router)


@app.on_event("startup")
async def startup():
    app.state.index_task = asyncio.create_task(ensure_indexes())
    try:
        await storage_service.init_storage_async()
        logger.info("Object storage initialised")
    except Exception as exc:
        logger.error("Object storage init failed: %s", exc)
    try:
        created = await seed_if_empty()
        if created:
            logger.info("Demo data seeded")
    except Exception as exc:
        logger.error("Seed failed: %s", exc)
    app.state.backup_task = asyncio.create_task(ops_routes.daily_backup_loop())
    app.state.alert_task = asyncio.create_task(requests_routes.pending_alert_loop())


@app.on_event("shutdown")
async def shutdown():
    app.state.index_task.cancel()
    app.state.backup_task.cancel()
    with suppress(asyncio.CancelledError):
        await app.state.index_task
    core.client.close()
