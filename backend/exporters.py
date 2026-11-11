"""Word, PDF and Excel exporters for case reports and MIS."""
import io
from datetime import datetime, timedelta, timezone

import segno
from docx import Document as DocxDocument
from docx.shared import Inches, Pt
from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors as rl_colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from report_config import DISCLAIMER


def fmt_dt(v) -> str:
    if not v:
        return "-"
    if isinstance(v, str):
        return v
    try:
        return v.strftime("%d-%b-%Y %H:%M:%S")
    except Exception:
        return str(v)


def qr_bytes(link: str) -> bytes:
    buf = io.BytesIO()
    segno.make(link, error="m").save(buf, scale=4)
    return buf.getvalue()


def _meta_rows(case, report, settings):
    gps = (report or {}).get("gps") or {}
    return [
        ["Company", settings.get("company_name", "CheckSphere")],
        ["Client", case.get("client_name", "-")],
        ["Client Branch", case.get("branch_name", "-")],
        ["Internal Case ID", case.get("internal_case_id", "-")],
        ["Client Case ID", case.get("client_case_id", "-")],
        ["Applicant", case.get("applicant_name", "-")],
        ["Co-applicant", case.get("co_applicant_name") or "-"],
        ["Verification Type", (report or {}).get("report_type_name") or case.get("report_type", "-")],
        ["Report Version", f"v{(report or {}).get('version', 1)}"],
        ["Visit Date & Time", fmt_dt((report or {}).get("submitted_at"))],
        ["GPS Coordinates", f"{gps.get('lat', '-')}, {gps.get('lon', '-')} (±{gps.get('accuracy', '-')}m)" if gps else "-"],
        ["Agent", (report or {}).get("submitted_by_name") or "-"],
        ["Supervisor", (report or {}).get("reviewed_by_name") or "Pending review"],
        ["Approval Date/Time", fmt_dt((report or {}).get("reviewed_at"))],
        ["Exceptions/Mismatches", (report or {}).get("data", {}).get("exceptions") or "None reported"],
    ]


def build_case_docx(case, report, evidence, config, settings, review_url) -> bytes:
    doc = DocxDocument()
    h = doc.add_paragraph()
    run = h.add_run(settings.get("company_name", "CheckSphere"))
    run.bold = True
    run.font.size = Pt(20)
    doc.add_paragraph("Field Verification Report")
    doc.add_paragraph(f"Verification Type: {config.get('name', case.get('report_type', ''))}")

    doc.add_paragraph("Report Details").runs[0].bold = True
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for k, v in _meta_rows(case, report, settings):
        row = t.add_row().cells
        row[0].text = k
        row[1].text = str(v)
        row[0].paragraphs[0].runs[0].bold = True

    doc.add_paragraph("Factual Findings").runs[0].bold = True
    data = (report or {}).get("data") or {}
    for section in config.get("sections", []):
        doc.add_paragraph(section["title"]).runs[0].bold = True
        ft = doc.add_table(rows=0, cols=2)
        ft.style = "Table Grid"
        for f in section.get("fields", []):
            val = data.get(f["key"], "")
            row = ft.add_row().cells
            row[0].text = f["label"]
            row[1].text = str(val) if val not in (None, "") else "-"
            row[0].paragraphs[0].runs[0].bold = True

    doc.add_paragraph("Agent Declaration").runs[0].bold = True
    doc.add_paragraph("I confirm that this report records my actual observations and authorised verification results. "
                      "I have not added unsupported opinions or conclusions."
                      if (report or {}).get("declaration") else "Declaration pending.")

    doc.add_paragraph("Evidence Photo References").runs[0].bold = True
    et = doc.add_table(rows=1, cols=4)
    et.style = "Table Grid"
    hdr = et.rows[0].cells
    for i, title in enumerate(["Slot", "File", "Captured At", "GPS"]):
        hdr[i].text = title
        hdr[i].paragraphs[0].runs[0].bold = True
    for e in evidence:
        row = et.add_row().cells
        row[0].text = e.get("slot", "-")
        row[1].text = e.get("filename", "-")
        row[2].text = fmt_dt(e.get("captured_at"))
        g = e.get("gps") or {}
        row[3].text = f"{g.get('lat', '-')}, {g.get('lon', '-')}" if g else "-"

    doc.add_paragraph("Disclaimer").runs[0].bold = True
    doc.add_paragraph(DISCLAIMER)
    doc.add_paragraph(f"Verification link: {review_url}")
    try:
        doc.add_picture(io.BytesIO(qr_bytes(review_url)), width=Inches(1.2))
    except Exception:
        pass
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_case_pdf(case, report, evidence, config, settings, review_url) -> bytes:
    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Field Verification Report")
    story = []
    story.append(Paragraph(f"<b>{settings.get('company_name', 'CheckSphere')}</b>", styles["Title"]))
    story.append(Paragraph("Field Verification Report", styles["Heading2"]))
    story.append(Paragraph(f"Verification Type: {config.get('name', case.get('report_type', ''))}", styles["Normal"]))
    story.append(Spacer(1, 8))

    meta_data = [[k, str(v)] for k, v in _meta_rows(case, report, settings)]
    t = Table(meta_data, colWidths=[120, 330])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), rl_colors.Color(0.93, 0.93, 0.9)),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Factual Findings", styles["Heading3"]))
    data = (report or {}).get("data") or {}
    for section in config.get("sections", []):
        story.append(Paragraph(section["title"], styles["Heading4"]))
        rows = [[f["label"], str(data.get(f["key"]) or "-")] for f in section.get("fields", [])]
        if rows:
            ft = Table(rows, colWidths=[190, 260])
            ft.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.lightgrey),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(ft)
        story.append(Spacer(1, 6))

    story.append(Paragraph("Evidence Photo References", styles["Heading3"]))
    ev_rows = [["Slot", "File", "Captured At", "GPS"]]
    for e in evidence:
        g = e.get("gps") or {}
        ev_rows.append([e.get("slot", "-"), e.get("filename", "-"), fmt_dt(e.get("captured_at")),
                        f"{g.get('lat', '-')}, {g.get('lon', '-')}"])
    et = Table(ev_rows, colWidths=[80, 160, 120, 90])
    et.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, rl_colors.lightgrey), ("FONTSIZE", (0, 0), (-1, -1), 7)]))
    story.append(et)

    story.append(Spacer(1, 8))
    story.append(Paragraph("Disclaimer", styles["Heading3"]))
    story.append(Paragraph(DISCLAIMER, styles["Normal"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Verification link: {review_url}", styles["Normal"]))
    try:
        story.append(RLImage(ImageReader(io.BytesIO(qr_bytes(review_url))), width=70, height=70))
    except Exception:
        pass
    doc.build(story)
    return buf.getvalue()


CASE_XLSX_HEADERS = ["Internal Case ID", "Client Case ID", "Client", "Branch", "Bank State", "Applicant", "Co-applicant", "Seller",
                     "Primary Contact", "Alternate Phone", "Report Type", "Status", "Priority", "Full Address", "Pincode",
                     "State of Verification", "City", "State", "Notes", "Agent", "Created", "Due (SLA)", "Submitted", "Approved", "Flags"]


def _case_row(c):
    return [c.get("internal_case_id"), c.get("client_case_id"), c.get("client_name"), c.get("branch_name"), c.get("bank_state"),
            c.get("applicant_name"), c.get("co_applicant_name"), c.get("seller_name"), c.get("primary_phone"), c.get("alt_phone"),
            c.get("report_type_name") or c.get("report_type"),
            (c.get("status") or "").replace("_", " ").title(), c.get("priority"), c.get("assigned_address"), c.get("pincode"),
            c.get("verification_state"), c.get("city"), c.get("state"), c.get("notes"),
            c.get("assigned_agent_name"), fmt_dt(c.get("created_at")), fmt_dt(c.get("due_at")),
            fmt_dt(c.get("last_submitted_at")), fmt_dt(c.get("approved_at")), ", ".join(c.get("flags") or [])]


def _style_sheet(ws, header_row):
    for cell in ws[header_row]:
        cell.font = Font(bold=True)


def build_cases_xlsx(cases) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Cases"
    ws.append(CASE_XLSX_HEADERS)
    for c in cases:
        ws.append(_case_row(c))
    _style_sheet(ws, 1)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_import_template_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Cases Import"
    headers = ["Client Case ID", "Client Name", "Branch Name", "Bank State", "Applicant Name", "Co-applicant Name", "Seller Name",
               "Primary Contact Number", "Alternate Phone", "Loan/Product Type", "Report Type", "Assigned Address", "Pincode",
               "State of Verification", "City", "State", "Priority", "Due Date (YYYY-MM-DD)", "Notes"]
    ws.append(headers)
    ws.append(["C-2024-0001", "Metro Capital Finance", "Andheri", "Maharashtra", "Rahul Sharma", "", "", "9876543210", "",
               "Home Loan", "Applicant Residence Verification", "B-402, Green Meadows, Andheri West", "400058",
               "Maharashtra", "Mumbai", "Maharashtra", "High", "2026-06-30", ""])
    _style_sheet(ws, 1)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_mis_xlsx(stats: dict, period: str, settings: dict) -> bytes:
    wb = Workbook()

    ws = wb.active
    ws.title = "Summary"
    ws.append(["CheckSphere MIS Report", period])
    ws.append(["Generated At", fmt_dt(datetime.now(timezone.utc))])
    ws.append([])
    ws.append(["Metric", "Count"])
    for k, v in (stats.get("counts") or {}).items():
        ws.append([k.replace("_", " ").title(), v])
    ws.append(["Unassigned", stats.get("unassigned", 0)])
    ws.append(["Overdue", stats.get("overdue", 0)])
    ws.append(["Average TAT (hours)", round(stats.get("avg_tat_hours") or 0, 1)])
    ws.append(["Cases Received (period)", stats.get("received", 0)])
    _style_sheet(ws, 4)

    def write_group(sheet_name, rows, headers, keys):
        s = wb.create_sheet(sheet_name)
        s.append(headers)
        for r in rows:
            s.append([r.get(k, 0) if isinstance(r, dict) else r for k in keys] if isinstance(r, dict) else list(r))
        _style_sheet(s, 1)

    write_group("Agents", stats.get("agents") or [], ["Agent", "Total", "Submitted", "Approved", "Overdue"],
                ["name", "total", "submitted", "approved", "overdue"])
    write_group("Supervisors", stats.get("supervisors") or [], ["Supervisor", "Approved", "Returned", "Inconclusive", "Exceptions"],
                ["name", "approved", "returned", "inconclusive", "exception"])
    grp_keys = ["name", "total", "approved", "overdue"]
    write_group("Clients", stats.get("clients") or [], ["Client", "Total", "Approved", "Overdue"], grp_keys)
    write_group("Branches", stats.get("branches") or [], ["Branch", "Total", "Approved", "Overdue"], grp_keys)
    write_group("States", stats.get("states") or [], ["State", "Total", "Approved", "Overdue"], grp_keys)
    write_group("Cities", stats.get("cities") or [], ["City", "Total", "Approved", "Overdue"], grp_keys)
    od = wb.create_sheet("Overdue Cases")
    od.append(CASE_XLSX_HEADERS)
    for c in stats.get("overdue_cases") or []:
        od.append(_case_row(c))
    _style_sheet(od, 1)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def period_range(period: str, date_str: str | None):
    base = datetime.now(timezone.utc)
    if date_str:
        try:
            base = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if period == "weekly":
        start = base - timedelta(days=base.weekday())
        end = start + timedelta(days=7)
        return start, end
    if period == "monthly":
        start = base.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        nxt = base.replace(day=28) + timedelta(days=4)
        end = nxt.replace(day=1)
        return start, end
    start = base.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)
