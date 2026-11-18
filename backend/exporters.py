"""Word, PDF and Excel exporters for case reports and MIS."""
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reportlab import rl_config

# Embed photos as their original JPEG bytes (DCTDecode), not ASCII85 text: same pixels, ~25% smaller PDFs.
rl_config.useA85 = 0

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
import core
from report_config import DISCLAIMER


def fmt_dt(v) -> str:
    """Stored timestamps are UTC; reports show Indian Standard Time."""
    if not v:
        return "-"
    if isinstance(v, str):
        return v
    try:
        return core.fmt_ist(v)
    except Exception:
        return str(v)


def fmt_gps(g: dict | None) -> str:
    g = g or {}
    if g.get("lat") is None:
        return f"No GPS ({g.get('status')})" if g.get("status") else "-"
    acc = f" ±{g['accuracy']:.0f}m" if isinstance(g.get("accuracy"), (int, float)) else ""
    extra = " MOCK?" if g.get("mocked") else ""
    return f"{g['lat']:.6f}, {g['lon']:.6f}{acc}{extra}"


def qr_bytes(link: str) -> bytes:
    buf = io.BytesIO()
    segno.make(link, error="m").save(buf, scale=4)
    return buf.getvalue()


SOURCE_LABELS = {
    "agent_created": "Agent-created verification (direct)",
    "supervisor_created": "Supervisor-created and assigned",
    "agent_request": "Agent request approved by supervisor",
    "excel_import": "Excel import",
    "admin_created": "Created by Super Admin",
}
SLOT_TITLES = {"exterior": "Exterior – Front", "exterior_2": "Exterior – Second Angle", "interior": "Interior",
               "selfie": "Selfie", "document": "Supporting Document"}


def photo_grid_items(evidence: list, config: dict, images: dict) -> list[dict]:
    """Ordered photo cells: category order of the form's photo slots, capture order within a category.
    Every configured slot appears; a slot without a usable stored image gets an 'unavailable' notice."""
    slots = [s_["key"] for s_ in config.get("photo_slots", [])]
    photos = [e for e in evidence if e.get("kind") == "photo"]
    for e in photos:
        if e.get("slot") not in slots:
            slots.append(e.get("slot"))
    items = []
    for slot in slots:
        mine = sorted((e for e in photos if e.get("slot") == slot), key=lambda e: str(e.get("captured_at") or ""))
        title = SLOT_TITLES.get(slot) or next((x["label"] for x in config.get("photo_slots", []) if x["key"] == slot), slot)
        if not mine:
            items.append({"title": title, "image": None, "notice": "Image unavailable – no photograph was captured for this category."})
            continue
        for i, e in enumerate(mine):
            data = images.get(str(e.get("id") or e.get("_id")))
            g = e.get("gps") or {}
            items.append({
                "title": title + (f" ({i + 1} of {len(mine)})" if len(mine) > 1 else ""),
                "image": data,
                "notice": None if data else "Image unavailable – the stored photograph could not be retrieved.",
                "captured": fmt_dt(e.get("captured_at")),
                "gps": f"{g['lat']:.6f}, {g['lon']:.6f}" if g.get("lat") is not None else "GPS not available",
            })
    return items


def _fit(data: bytes, max_w: float, max_h: float) -> tuple[float, float]:
    """Scale (w, h) to fit the box while preserving the photo's aspect ratio (no stretching or cropping)."""
    from PIL import Image as _PIL
    w, h = _PIL.open(io.BytesIO(data)).size
    k = min(max_w / w, max_h / h)
    return w * k, h * k


def _meta_rows(case, report, settings):
    gps = (report or {}).get("gps") or {}
    return [
        ["Company", settings.get("company_name", "CheckSphere")],
        ["Client", case.get("client_name", "-")],
        ["Client Branch", case.get("branch_name", "-")],
        ["Internal Case ID", case.get("internal_case_id") or "-"],
        ["Client / External Case ID", case.get("client_case_id") or "Not provided"],
        ["Applicant", case.get("applicant_name", "-")],
        ["Co-applicant", case.get("co_applicant_name") or "-"],
        ["Verification Type", (report or {}).get("report_type_name") or case.get("report_type", "-")],
        ["Report Version", f"v{(report or {}).get('version', 1)}"],
        ["Case Source", SOURCE_LABELS.get(case.get("source"), "Assigned case")],
        ["Visit Date & Time", ((report or {}).get("data") or {}).get("visit_datetime") or fmt_dt((report or {}).get("submitted_at"))],
        ["GPS Coordinates", f"{gps.get('lat', '-')}, {gps.get('lon', '-')} (±{gps.get('accuracy', '-')}m)" if gps else "-"],
        ["Agent", (report or {}).get("submitted_by_name") or "-"],
        ["Supervisor", (report or {}).get("reviewed_by_name") or "Pending review"],
        ["Approval Date/Time", fmt_dt((report or {}).get("reviewed_at"))],
        ["Exceptions/Mismatches", (report or {}).get("data", {}).get("exceptions") or "None reported"],
    ]


BRANDING_DIR = Path(__file__).parent / "assets" / "branding"
# Header_CheckSphere (supplied by the owner) replaces the AADITYA ENTERPRISE banner as soon as the file is placed in
# assets/branding/. The legacy banner is only a fallback until then; remove the fallback once the new header is approved.
HEADER_CHECKSPHERE_FILES = ("Header_CheckSphere.png", "Header_CheckSphere.jpg", "Header_CheckSphere.jpeg")
LEGACY_HEADER_IMAGE = BRANDING_DIR / "aaditya_enterprise_header.jpg"


def report_header_image() -> Path | None:
    """The header artwork for Word and PDF reports, used exactly as supplied (never redrawn)."""
    for name in HEADER_CHECKSPHERE_FILES:
        if (BRANDING_DIR / name).exists():
            return BRANDING_DIR / name
    return LEGACY_HEADER_IMAGE if LEGACY_HEADER_IMAGE.exists() else None


def report_header_is_legacy() -> bool:
    return report_header_image() == LEGACY_HEADER_IMAGE


DOCX_HEADER_IMAGE = report_header_image()  # kept for older imports; builders call report_header_image() each time
DOCX_HEADER_DISTANCE = Inches(0.3)   # gap between the top edge of the page and the header artwork
DOCX_HEADER_BODY_GAP = Inches(0.2)   # gap between the header artwork and the report body


def _docx_apply_header(doc) -> None:
    """Place the supplied header artwork (Header_CheckSphere, or the legacy banner until it arrives; used as-is, never redrawn) in the page header of every section.
    The header part repeats automatically on every page. The banner is scaled to the full width between the page margins
    with its original aspect ratio, and the top margin is set so the body always starts below it (nothing is covered)."""
    header_img = report_header_image()
    if not header_img:
        return
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from PIL import Image as _PIL
    with _PIL.open(header_img) as im:
        px_w, px_h = im.size
    for section in doc.sections:
        width = section.page_width - section.left_margin - section.right_margin
        height = int(width * px_h / px_w)
        section.different_first_page_header_footer = False
        section.header_distance = DOCX_HEADER_DISTANCE
        section.top_margin = DOCX_HEADER_DISTANCE + height + DOCX_HEADER_BODY_GAP
        header = section.header
        header.is_linked_to_previous = False
        p = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.left_indent = 0
        p.paragraph_format.right_indent = 0
        p.add_run().add_picture(str(header_img), width=width, height=height)


def build_case_docx(case, report, evidence, config, settings, review_url, images: dict | None = None) -> bytes:
    doc = DocxDocument()
    _docx_apply_header(doc)
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

    # (The "Evidence Photo References" table of slots / file names / times / GPS was removed on request; the
    # photographs themselves follow, embedded, with their category labels.)
    _docx_photo_grid(doc, photo_grid_items(evidence, config, images or {}))

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


def _docx_photo_grid(doc, items: list[dict]):
    from docx.enum.text import WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    doc.add_paragraph("Evidence Photographs").runs[0].bold = True
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for i in range(0, len(items), 2):
        row = table.add_row()
        tr_pr = row._tr.get_or_add_trPr()          # keep each photo row on one page (never cut a photo)
        cant = OxmlElement("w:cantSplit")
        cant.set(qn("w:val"), "true")
        tr_pr.append(cant)
        for cell, it in zip(row.cells, items[i:i + 2]):
            p = cell.paragraphs[0]
            p.add_run(it["title"]).bold = True
            if it["image"]:
                try:
                    w, h = _fit(it["image"], 3.05, 3.9)
                    cell.add_paragraph().add_run().add_picture(io.BytesIO(it["image"]), width=Inches(w), height=Inches(h))
                except Exception:
                    cell.add_paragraph("Image unavailable – the stored photograph could not be read.")
                cap = cell.add_paragraph(f"Captured: {it['captured']}\nGPS: {it['gps']}")
                for r in cap.runs:
                    r.font.size = Pt(8)
            else:
                cell.add_paragraph(it["notice"]).runs[0].italic = True
            if len(items[i:i + 2]) == 1:
                row.cells[1].text = ""


def build_case_pdf(case, report, evidence, config, settings, review_url, images: dict | None = None) -> bytes:
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

    # (Evidence Photo References table removed on request; the embedded photographs follow.)

    items = photo_grid_items(evidence, config, images or {})
    if items:
        from reportlab.platypus import PageBreak
        story.append(PageBreak())
        story.append(Paragraph("Evidence Photographs", styles["Heading3"]))
        cap_style = styles["Normal"].clone("cap", fontSize=7.5, leading=9.5)
        cells = []
        for it in items:
            cell = [Paragraph(f"<b>{it['title']}</b>", styles["Normal"]), Spacer(1, 3)]
            if it["image"]:
                try:
                    w, h = _fit(it["image"], 215, 285)
                    cell.append(RLImage(io.BytesIO(it["image"]), width=w, height=h))
                    cell.append(Spacer(1, 3))
                    cell.append(Paragraph(f"Captured: {it['captured']}<br/>GPS: {it['gps']}", cap_style))
                except Exception:
                    cell.append(Paragraph("<i>Image unavailable – the stored photograph could not be read.</i>", cap_style))
            else:
                cell.append(Paragraph(f"<i>{it['notice']}</i>", cap_style))
            cells.append(cell)
        rows = [cells[i:i + 2] + ([""] if len(cells[i:i + 2]) == 1 else []) for i in range(0, len(cells), 2)]
        grid = Table(rows, colWidths=[228, 228])   # rows never split, so a photo is never cut across pages
        grid.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, rl_colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story.append(grid)

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
                     "State of Verification", "City", "State", "Notes", "Agent", "Created", "Due (SLA)", "Submitted", "Approved", "Flags",
                     "Case Source"]


def _case_row(c):
    return [c.get("internal_case_id"), c.get("client_case_id"), c.get("client_name"), c.get("branch_name"), c.get("bank_state"),
            c.get("applicant_name"), c.get("co_applicant_name"), c.get("seller_name"), c.get("primary_phone"), c.get("alt_phone"),
            c.get("report_type_name") or c.get("report_type"),
            (c.get("status") or "").replace("_", " ").title(), c.get("priority"), c.get("assigned_address"), c.get("pincode"),
            c.get("verification_state"), c.get("city"), c.get("state"), c.get("notes"),
            c.get("assigned_agent_name"), fmt_dt(c.get("created_at")), fmt_dt(c.get("due_at")),
            fmt_dt(c.get("last_submitted_at")), fmt_dt(c.get("approved_at")), ", ".join(c.get("flags") or []),
            SOURCE_LABELS.get(c.get("source"), "Assigned case")]


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
