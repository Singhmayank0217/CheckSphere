"""Export routes: Word/PDF case reports, Excel case list, MIS workbook."""
import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

import core
import exporters  # noqa: F401  (imported at start-up so the first download doesn't pay ~1-2 s of imports)
import report_cache
import security
import vee_report
from cases_routes import can_access_case, get_case_or_404
from report_config import config_for

router = APIRouter()
logger = logging.getLogger(__name__)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _review_url(request: Request, case_id: str) -> str:
    host = request.headers.get("host", "localhost:3000")
    scheme = "https" if request.headers.get("x-forwarded-proto") == "https" else "http"
    return f"{scheme}://{host}/cases/{case_id}"


@router.get("/exports/case/{case_id}/docx")
async def export_case_docx(case_id: str, request: Request, ctx=Depends(security.admin_sup)):
    return await _export_case(case_id, "docx", request, ctx)


@router.get("/exports/case/{case_id}/pdf")
async def export_case_pdf(case_id: str, request: Request, ctx=Depends(security.admin_sup)):
    return await _export_case(case_id, "pdf", request, ctx)


async def _export_case(case_id: str, fmt: str, request: Request, ctx):
    t0 = time.monotonic()
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    if ctx["user"]["role"] == "supervisor" and case.get("status") not in ("approved", "exported"):
        raise HTTPException(403, "Supervisors can export approved reports only")
    report = await core.current_report(str(case["_id"]), ["approved", "exported"])
    if not report:
        report = await core.current_report(str(case["_id"]))
    if not report:
        raise HTTPException(400, "No report submitted for this case yet")
    settings = await core.get_settings()
    config = config_for(case["report_type"], settings)
    evidence = [core.clean(e) async for e in core.db.evidence.find({"case_id": str(case["_id"])}).sort("created_at", 1)]
    call_logs = [core.clean(c) async for c in core.db.call_logs.find({"case_id": str(case["_id"])}).sort("attempt_at", 1)]
    masked = ctx["user"]["role"] != "super_admin"
    data = core.mask_mapping(report.get("data") or {}) if masked else report.get("data") or {}
    report = {**report, "data": data}
    use_vee = vee_report.vee_supported(case.get("report_type"))
    review_url = _review_url(request, str(case["_id"]))
    ext = "docx" if fmt == "docx" else "pdf"
    fname = f"{case['internal_case_id']}-v{report.get('version', 1)}.{ext}"
    mime = DOCX_MIME if fmt == "docx" else "application/pdf"
    key = report_cache.report_key(fmt, case, report, evidence, call_logs, settings, masked,
                                  extra="vee" if use_vee else review_url)
    t_db = time.monotonic()
    content = report_cache.cached_report(key)
    cache_state = "hit" if content is not None else "miss"
    t_img = t_db
    if content is None:
        # The case's own stored, watermarked photographs (fetched in parallel, checksum-verified, embedded as bytes).
        images = await report_cache.load_case_photos(case, evidence)
        t_img = time.monotonic()
        if use_vee:  # the approved VEE red-only format for this verification type
            build = vee_report.build_vee_docx if fmt == "docx" else vee_report.build_vee_pdf
            content = await asyncio.to_thread(build, case, report, evidence, config, call_logs, images)
        else:        # report types without a VEE format keep the standard CheckSphere layout
            from exporters import build_case_docx, build_case_pdf
            build = build_case_docx if fmt == "docx" else build_case_pdf
            content = await asyncio.to_thread(build, case, report, evidence, config, settings, review_url, images)
        report_cache.store_report(key, content)
    t_build = time.monotonic()
    await core.audit(ctx["user"], "report_exported", "case", str(case["_id"]),
                     {"format": fmt, "version": report.get("version"), "layout": "vee" if use_vee else "standard",
                      "cache": cache_state}, request)
    if case.get("status") == "approved":
        from cases_routes import tl
        await core.db.cases.update_one({"_id": case["_id"]}, {"$set": {"status": "exported", "updated_at": core.now()},
                                                             "$push": {"timeline": tl("report_exported", ctx["user"], {"format": fmt})}})
    logger.info("export %s case %s: %s, %d bytes | db %.2fs, photos %.2fs, build %.2fs, total %.2fs", fmt, case["_id"],
                cache_state, len(content), t_db - t0, t_img - t_db, t_build - t_img, time.monotonic() - t0)
    return Response(content=content, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="{fname}"', "Content-Length": str(len(content)),
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "X-Report-Cache": cache_state,
        "Server-Timing": f"total;dur={(time.monotonic() - t0) * 1000:.0f}"})


@router.get("/exports/cases.xlsx")
async def export_cases_xlsx(request: Request, status: str | None = None, client_id: str | None = None,
                            agent_id: str | None = None, report_type: str | None = None, ctx=Depends(security.admin_sup)):
    from cases_routes import list_cases as _  # noqa: F401
    from exporters import build_cases_xlsx
    query = dict(core.LIVE_CASE_FILTER)
    if status:
        query["status"] = {"$in": [s.strip() for s in status.split(",")]}
    if client_id:
        query["client_id"] = client_id
    if agent_id:
        query["assigned_agent_id"] = agent_id
    if report_type:
        query["report_type"] = report_type
    scope = security.case_scope_query(ctx["user"])
    if scope:
        query = {"$and": [query, scope]}
    cases = await core.db.cases.find(query).sort("created_at", -1).limit(5000).to_list(5000)
    content = build_cases_xlsx(cases)
    await core.audit(ctx["user"], "cases_exported", "case", "bulk", {"count": len(cases)}, request)
    return Response(content=content, media_type=XLSX_MIME,
                    headers={"Content-Disposition": 'attachment; filename="checksphere-cases.xlsx"'})


@router.get("/exports/mis.xlsx")
async def export_mis(request: Request, period: str = "daily", date: str | None = None, ctx=Depends(security.admin_sup)):
    from exporters import build_mis_xlsx, period_range
    from dashboard_routes import stats as stats_route
    start, end = period_range(period, date)
    stats = await stats_route(request=request, from_date=start.date().isoformat(),
                              to_date=end.date().isoformat(), client_id=None, branch_id=None, state=None,
                              city=None, agent_id=None, report_type=None, ctx=ctx)
    stats["received"] = stats.get("total", 0)
    content = build_mis_xlsx(stats, f"{period.title()} ({start.date()} to {end.date()})", await core.get_settings())
    await core.audit(ctx["user"], "mis_exported", "report", "mis", {"period": period}, request)
    return Response(content=content, media_type=XLSX_MIME,
                    headers={"Content-Disposition": f'attachment; filename="checksphere-mis-{period}.xlsx"'})
