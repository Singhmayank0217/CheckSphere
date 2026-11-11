"""Export routes: Word/PDF case reports, Excel case list, MIS workbook."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

import core
import security
from cases_routes import can_access_case, get_case_or_404
from report_config import config_for

router = APIRouter()

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
    case = await get_case_or_404(case_id)
    if not await can_access_case(ctx["user"], case):
        raise HTTPException(403, "Not allowed")
    if ctx["user"]["role"] == "supervisor" and case.get("status") not in ("approved", "exported"):
        raise HTTPException(403, "Supervisors can export approved reports only")
    report = await core.db.reports.find_one({"case_id": str(case["_id"]), "status": {"$in": ["approved", "exported"]}},
                                            sort=[("version", -1)])
    if not report:
        report = await core.db.reports.find_one({"case_id": str(case["_id"])}, sort=[("version", -1)])
    if not report:
        raise HTTPException(400, "No report submitted for this case yet")
    settings = await core.get_settings()
    config = config_for(case["report_type"], settings)
    evidence = [core.clean(e) async for e in core.db.evidence.find({"case_id": str(case["_id"])}).sort("created_at", 1)]
    data = core.mask_mapping(report.get("data") or {}) if not ctx["user"]["role"] == "super_admin" else report.get("data") or {}
    report = {**report, "data": data}
    review_url = _review_url(request, str(case["_id"]))
    from exporters import build_case_docx, build_case_pdf
    if fmt == "docx":
        content = build_case_docx(case, report, evidence, config, settings, review_url)
        fname = f"{case['internal_case_id']}-v{report.get('version', 1)}.docx"
        mime = DOCX_MIME
    else:
        content = build_case_pdf(case, report, evidence, config, settings, review_url)
        fname = f"{case['internal_case_id']}-v{report.get('version', 1)}.pdf"
        mime = "application/pdf"
    await core.audit(ctx["user"], "report_exported", "case", str(case["_id"]), {"format": fmt, "version": report.get("version")}, request)
    if case.get("status") == "approved":
        from cases_routes import tl
        await core.db.cases.update_one({"_id": case["_id"]}, {"$set": {"status": "exported", "updated_at": core.now()},
                                                             "$push": {"timeline": tl("report_exported", ctx["user"], {"format": fmt})}})
    return Response(content=content, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/exports/cases.xlsx")
async def export_cases_xlsx(request: Request, status: str | None = None, client_id: str | None = None,
                            agent_id: str | None = None, report_type: str | None = None, ctx=Depends(security.admin_sup)):
    from cases_routes import list_cases as _  # noqa: F401
    from exporters import build_cases_xlsx
    query = {"deleted_at": None}
    query.update(security.case_scope_query(ctx["user"]))
    if status:
        query["status"] = {"$in": [s.strip() for s in status.split(",")]}
    if client_id:
        query["client_id"] = client_id
    if agent_id:
        query["assigned_agent_id"] = agent_id
    if report_type:
        query["report_type"] = report_type
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
