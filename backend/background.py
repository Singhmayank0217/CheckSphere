"""Background jobs: daily backup, 24h/48h pending alerts, case-address geocoding.

Normal mode: each job runs on its own timer, as before.
SERVERLESS_MODE=true: no timers. A job runs (at most once per interval) when a real API request arrives, so the
service makes no outbound traffic of its own while nobody is using it and Railway Serverless can put it to sleep.
There is deliberately NO keep-alive: nothing here generates requests to keep the service awake. All jobs are
idempotent, so a job interrupted by sleep or shutdown simply runs again later.
"""
import asyncio
import logging
import time
from contextlib import suppress

import core
import geocoding
import ops_routes
import push_service
import requests_routes

logger = logging.getLogger(__name__)

# name: (minimum seconds between on-demand runs, one-pass coroutine function)
JOBS = {
    "backup": (3600, ops_routes.backup_if_due),
    "alerts": (300, requests_routes.pending_alert_pass),
    "geocode": (60, geocoding.geocode_pass),
    "push": (60, push_service.push_pass),  # retries failed push sends, reads delivery receipts (no-op when push is off)
}
_tasks: dict[str, asyncio.Task] = {}
_last: dict[str, float] = {}


def start() -> None:
    if core.SERVERLESS_MODE:
        logger.info("SERVERLESS_MODE: background jobs run on demand (no timers)")
        return
    _tasks["backup"] = asyncio.create_task(ops_routes.daily_backup_loop())
    _tasks["alerts"] = asyncio.create_task(requests_routes.pending_alert_loop())
    _tasks["geocode"] = asyncio.create_task(geocoding.geocode_loop())
    if push_service.ENABLED:
        _tasks["push"] = asyncio.create_task(push_service.push_loop())


async def _run(name: str, fn) -> None:
    try:
        await fn()
    except Exception as exc:
        logger.error("background job %s failed: %s", name, exc)


def on_request() -> None:
    """Called for each API request. In serverless mode, start any job that is due and not already running."""
    if not core.SERVERLESS_MODE:
        return
    now = time.monotonic()
    for name, (interval, fn) in JOBS.items():
        task = _tasks.get(name)
        if (task is None or task.done()) and now - _last.get(name, -1e9) >= interval:
            _last[name] = now
            _tasks[name] = asyncio.create_task(_run(name, fn))


class TriggerMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/"):
            on_request()
        return await self.app(scope, receive, send)


async def stop(timeout: float = 10) -> None:
    """Graceful shutdown: cancel the jobs and wait briefly (every job is safe to interrupt and re-run)."""
    for t in _tasks.values():
        t.cancel()
    for t in list(_tasks.values()):
        with suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(t, timeout)
    _tasks.clear()
