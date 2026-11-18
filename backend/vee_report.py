"""VEE-format verification reports (Word + PDF): the client's "VEE FORMAT (1).docx" reproduced with BOTH its red and
its black content, per verification type.

Colour rule (owner, 14-Nov-2026): RED content = mandatory fields, BLACK content = optional fields. Both are printed in
their original colour, font, size, bold/underline, table position and order; a black field that was not provided
prints "N/A". Field mapping per type: docs/report-format/VEE_FIELD_MAPPING.md.
Other rules kept from earlier decisions:
  * the AADITYA ENTERPRISE banner is the page header on every page of both Word and PDF (the master's "VEE
    TECHNOLOGIES PVT.LTD" verifier text is the template company and is not printed; the verifier's name is);
  * photographs: only the case's own stored, watermarked photos, embedded under category labels; a missing photo gets a
    notice and is never substituted; there is no evidence reference table;
  * the Internal Case ID is kept in the file name and the document properties for traceability.

Word and PDF are rendered from the same layout description (build_layout), so they stay the same.
Values are never invented.
"""
import io
import os
from pathlib import Path

from reportlab import rl_config

# Embed photos as their original JPEG bytes (DCTDecode), not ASCII85 text: same pixels, ~25% smaller PDFs.
rl_config.useA85 = 0

RED = "FF0000"
BLACK = "000000"
NA = "N/A"
TICK = "\u2714"
PHOTO_BOX_H_IN = 2.2   # photo height (inches): 3 rows of 2 labelled photos fit under the header on one Letter page
PHOTO_LABEL_PT = 9     # category label above each photo
PHOTO_SINGLE_H_IN = 6.0  # a lone photo (e.g. the KYC/GST supporting document) gets most of the page
GRID = 6  # VEE tables use a 6-column grid; cells span 6 (full), 3 (half) or 2 (third) columns

TITLES = {
    "residence_applicant": "Applicant Residence Verification Report",
    "residence_coapplicant": "Co-Applicant Residence Verification Report",
    "office_coapplicant": "Office Verification Report",
    "business_applicant": "Office Verification Report",
    "tel_residence": "Residence Tele Verification Report",
    "tel_office": "Office Tele Verification Report",
    "kyc": "K Y C    Verification    Report",
    "gst": "G.S.T. Verification Report",
}
PHOTO_TITLES = {
    "residence_applicant": "RESIDENCE VERIFICATION PHOTO", "residence_coapplicant": "RESIDENCE VERIFICATION PHOTO",
    "office_coapplicant": "OFFICE VERIFICATION PHOTO", "business_applicant": "OFFICE VERIFICATION PHOTO",
    "tel_residence": "TELE VERIFICATION DOCUMENT", "tel_office": "TELE VERIFICATION DOCUMENT",
    "kyc": "KYC VERIFICATION PHOTO", "gst": "G.S.T. VERIFICATION PHOTO",
}
# VEE tele outcome codes ("Outcome: C= (Confirmed), B= (Busy tone), Cl = (Call later) Nr = (No Response)")
CALL_CODES = {"Confirmed": "C", "Busy": "B", "Call Later": "Cl", "No Response": "Nr"}


def vee_supported(report_type: str) -> bool:
    return report_type in TITLES


# ------------------------------------------------------------------ values
def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def _val(data: dict, case: dict, *keys, upper=True) -> str:
    for k in keys:
        s = _clean((data or {}).get(k)) or _clean((case or {}).get(k))
        if s:
            return s.upper() if upper else s
    return NA


def _dob(data: dict) -> str:
    """Date of Birth from the date picker ('YYYY-MM-DD') printed as DD-MMM-YYYY; older free text exactly as stored."""
    from core import fmt_date
    s = fmt_date((data or {}).get("applicant_dob"))
    return s.upper() if s else NA


def _visit_parts(data: dict, report: dict, key="visit_datetime") -> tuple:
    """'13-Nov-2026 07:03:24 PM IST' -> ('13-Nov-2026', '07:03 PM IST')."""
    raw = _clean((data or {}).get(key))
    if not raw:
        return NA, NA
    parts = raw.split(" ")
    date = parts[0]
    time = " ".join(parts[1:]).replace(" IST", "").strip()
    if time.count(":") == 2:  # drop seconds
        hh, mm, rest = time.split(":", 2)
        time = f"{hh}:{mm}{rest[2:]}"
    return (date.upper() or NA), ((time + " IST") if time else NA)


def _yes_no(outcome: str) -> str:
    o = _clean(outcome).lower()
    return {"confirmed": "YES", "not confirmed": "NO", "inconclusive": "INCONCLUSIVE"}.get(o, o.upper() or NA)


def _verifier(data: dict, report: dict) -> str:
    name = _val(data, {}, "agent_name", "verifier_name")
    return name if name != NA else (_clean((report or {}).get("submitted_by_name")).upper() or NA)


def _ticked(data: dict) -> set:
    return {p.strip() for p in str((data or {}).get("not_recommended_reasons") or "").split(";") if p.strip()}


# ------------------------------------------------------------------ layout description
# Block types (all text styled explicitly; colours are RED or BLACK as in the master document):
#   ("title", text, font, size)                    black, bold, underlined, centred
#   ("text", runs, align, space_after_pt)          a paragraph; runs = [(text, font, size, bold, underline, color)]
#   ("grid", font, size, rows)                     6-column bordered table; rows = [[cell, ...]], a cell is
#                                                   (span, label, value, color, label_bold, value_bold)
#   ("box", font, size, runs)                      single bordered cell holding styled runs
#   ("table", font, size, rows, widths)            plain bordered table; a cell is "" or (text, color, bold, italic)
#   ("ticks", font, size, items, widths, bold)     VEE "Reasons for Not Recommended" list: items = [(label, ticked)]
#   ("photos", title, items)                       photo page; items {"title", "image": bytes|None, "notice"}
def _r(span, label, value, lb=False, vb=True):
    return (span, label, value, RED, lb, vb)


def _k(span, label, value, lb=False, vb=False):
    return (span, label, value, BLACK, lb, vb)


def _run(text, font, size, bold=False, underline=False, color=BLACK):
    return (text, font, size, bold, underline, color)


def _signature(data, report, after=0):
    name = _verifier(data, report)
    return [("text", [_run("Verifier Name: -", "Cambria", 10, True, True), _run("  " + name, "Cambria", 10)], None, 2),
            ("text", [_run("Authorized Signature with Seal", "Cambria", 10, True)], None, after)]


def _reasons(data, font, size, bold, label):
    picked = _ticked(data)
    from report_config import NOT_RECOMMENDED_REASONS
    items = [(r, r in picked) for r in NOT_RECOMMENDED_REASONS]
    return [("text", [_run(label, font, size, bold, True)], None, 2),
            ("ticks", font, size, items, [2354580, 685800, 2400300, 640080], bold)]


def _call_rows(call_logs):
    """VEE tele log: up to 4 attempts in time order (date, time, outcome code)."""
    from exporters import fmt_dt
    logs = sorted(call_logs or [], key=lambda c: str(c.get("attempt_at") or ""))[:4]
    dates, times, outs = [], [], []
    for c in logs:
        d, t = _visit_parts({"x": fmt_dt(c.get("attempt_at"))}, None, "x")
        dates.append(d)
        times.append(t)
        outs.append(CALL_CODES.get(c.get("result"), _clean(c.get("result")).upper()))
    while len(dates) < 4:
        dates.append("")
        times.append("")
        outs.append("")
    b = lambda t, color=BLACK: (t, color, True, False)  # noqa: E731
    return [[b("Attempt"), b("1st"), b("2nd"), b("3rd"), b("4th")],
            [b("Date of Calling", RED), *[(x, RED, False, False) if x else "" for x in dates]],
            [b("Time of Calling", RED), *[(x, RED, False, False) if x else "" for x in times]],
            [b("Outcome"), *[(x, BLACK, True, False) if x else "" for x in outs]]]


def _spoken(call_logs) -> dict:
    """Person spoken to / relationship / confirmation: the latest confirmed call, else the latest call."""
    logs = sorted(call_logs or [], key=lambda c: str(c.get("attempt_at") or ""), reverse=True)
    best = next((c for c in logs if c.get("result") == "Confirmed"), logs[0] if logs else {})
    return best or {}


def build_layout(case: dict, report: dict, call_logs: list, photos: list) -> list:
    rt = case.get("report_type")
    data = (report or {}).get("data") or {}
    blocks = []
    if rt in ("residence_applicant", "residence_coapplicant"):
        BA, S = "Book Antiqua", 9
        date, time = _visit_parts(data, report)
        bank_branch = " / ".join(x for x in (_clean(case.get("client_name")), _clean(case.get("branch_name"))) if x).upper() or NA
        blocks.append(("title", TITLES[rt], "Arial Black", 11))
        blocks.append(("text", [_run("The following information should be obtained if the applicant or his family members are contacted.", BA, S, True)], None, 4))
        blocks.append(("grid", BA, S, [
            [_r(6, "Bank / Branch Name:-", bank_branch)],
            [_r(6, "Name of Applicant:-", _val(data, case, "applicant_name"))],
            [_r(6, "Present Residence Address:-", _val(data, case, "observed_address", "assigned_address"))],
            [_r(2, "Date of Visit:-", date), _r(2, "Time of Visit:-", time), _r(2, "DOB:-", _dob(data))],
            [_r(3, "Address Confirmed:-", _yes_no(data.get("address_outcome"))), _r(3, "Address Confirmed by:-", _val(data, {}, "address_confirmed_by"))],
            [_r(3, "Person Met:-", _val(data, {}, "person_met")), _r(3, "Relationship:-", _val(data, {}, "relationship"))],
            [_r(3, "Marital Status:-", _val(data, {}, "marital_status")), _r(3, "Nearest Landmark:-", _val(data, {}, "landmark"))],
            [_r(2, "No of Residents in house:-", _val(data, {}, "residents_count")), _r(2, "Years at current residence:-", _val(data, {}, "years_at_residence")),
             _r(2, "No of Earning Family Members:-", _val(data, {}, "earning_members"))],
            [_r(2, "Residence Status:-", _val(data, {}, "residence_status")), _k(2, "Approx. Value(If Owned):-", _val(data, {}, "approx_value")),
             _k(2, "Approx. Rent:-", _val(data, {}, "approx_rent"))],
            [_r(3, "Unit:-", _val(data, {}, "unit")), _r(3, "Type of Roof:-", _val(data, {}, "roof_type"), vb=False)],
            [_r(3, "Vehicle:-", _val(data, {}, "vehicle")), _r(3, "Type of Loan:-", _val(data, case, "loan_type"))],
        ]))
        blocks.append(("text", [_run("Verifier Observation", BA, S, True), _run(".", BA, S)], None, 2))
        blocks.append(("grid", BA, S, [
            [_k(2, "Location:-", _val(data, {}, "accessibility")), _k(2, "Locality:-", _val(data, {}, "locality")),
             _k(2, "Accommodation Type:-", _val(data, {}, "accommodation_type"), vb=True)],
            [_k(2, "Interior Condition:-", _val(data, {}, "interior_condition")), _k(2, "Standard Living:-", _val(data, {}, "standard_of_living")),
             _k(2, "Approx. Area (sq. Ft.):-", _val(data, {}, "approx_area_sqft"), vb=True)],
            [_r(6, "Assets Seen (Y/N):-", _val(data, {}, "assets_seen"), vb=False)],
        ]))
        blocks.append(("text", [_run("If the house is locked the following information needs to be obtained from the neighbour / third party.", BA, S, True)], None, 2))
        blocks.append(("grid", BA, S, [
            [_k(2, "Applicant Name:-", _val(data, {}, "nb_applicant_name")), _k(2, "Person Met:-", _val(data, {}, "nb_person_met")),
             _k(2, "Relationship:-", _val(data, {}, "nb_relationship"))],
            [_k(3, "Applicant Age(Approx.):-", _val(data, {}, "nb_applicant_age")), _k(3, "No of Residents in House:-", _val(data, {}, "nb_residents"))],
            [_k(3, "Year Lived at this Residence:-", _val(data, {}, "nb_years_lived")), _k(3, "Occupation:-", _val(data, {}, "nb_occupation"))],
        ]))
        blocks.append(("text", [_run("Verifier Remarks:-", BA, S, True)], None, 2))
        blocks.append(("box", BA, S, [_run(_val(data, {}, "agent_remarks", upper=False), BA, S, True, False, RED)]))
        blocks.append(("grid", BA, S, [
            [_r(6, "Remarks:-", _val(data, {}, "vee_remarks"))],
            [_k(3, "Did the Customer Applied Previously:-", _val(data, {}, "previously_applied")),
             _k(3, "Date of  Previous File:-", _val(data, {}, "previous_file_date"))],
            [_r(3, "Recommendation:-", _val(data, {}, "vee_recommendation"), vb=False), _k(3, "", NA)],
        ]))
        blocks += _reasons(data, BA, S, False, "Reasons for Not Recommended (please tick):-")
        blocks += _signature(data, report)
    elif rt in ("office_coapplicant", "business_applicant"):
        BA, S = "Book Antiqua", 10
        date, time = _visit_parts(data, report)
        branch = _clean(case.get("branch_name")) or _clean(case.get("client_name"))
        blocks.append(("title", TITLES[rt], "Arial Black", 12))
        blocks.append(("text", [_run("T", BA, S), _run("he following information should be obtained if the applicant/ colleagues are contacted in the office.", BA, S, True)], None, 4))
        blocks.append(("grid", BA, S, [
            [_r(6, "Branch Name:-", branch.upper() if branch else NA)],
            [_r(6, "Name of Applicant:-", _val(data, case, "applicant_name"))],
            [_r(6, "Name of Employer:-", _val(data, {}, "employer_name"))],
            [_r(6, "Office Address:-", _val(data, case, "observed_address", "assigned_address"))],
            [_r(3, "PH No:-", _val(data, {}, "office_phone")), _r(3, "DOB:-", _dob(data))],
            [_r(3, "Date of Visit:-", date), _r(3, "Time of Visit:-", time)],
            [_r(3, "Person Met:-", _val(data, {}, "person_met")), _r(3, "Designation:-", _val(data, {}, "person_designation"))],
            [_r(3, "Designation of Applicant:-", _val(data, {}, "applicant_designation")),
             _r(3, "No of Years Worked Here:-", _val(data, {}, "years_employed"))],
            [_k(3, "Previous Employment:-", _val(data, {}, "previous_employment"), vb=True),
             _k(3, "Year of establishment:-", _val(data, {}, "year_of_establishment"), vb=True)],
            [_k(3, "Office Board Present?", _val(data, {}, "board_present")), _r(3, "Terms of Employment:-", _val(data, {}, "employment_terms"))],
            [_r(3, "Type of Employer Co.:-", _val(data, {}, "employer_type")), _r(3, "Nature of Business:-", _val(data, {}, "nature_of_business"))],
            [_k(6, "Approx. Area of the Office (Sq. Ft.):-", _val(data, {}, "office_area_sqft"))],
            [_k(3, "No. of Employees:-", _val(data, {}, "employees_count")), _k(3, "No. of Branch / Office:-", _val(data, {}, "branches_count"))],
            [_k(6, "Premises:-", _val(data, {}, "premises_type"))],
            [_k(6, "Assets Seen? (Y/N):-", _val(data, {}, "office_assets_seen"))],
        ]))
        blocks.append(("text", [_run("Comments:-", BA, S, True, True)], None, 2))
        blocks.append(("grid", BA, S, [
            [_k(6, "Accessibility of the Office with Direction:-", _val(data, {}, "accessibility", upper=False), lb=True)],
            [_k(6, "Neighbor\u2019s Feedback:-", _val(data, {}, "neighbour_feedback"), lb=True)],
        ]))
        blocks.append(("box", BA, S, [_run("Verifier Remarks: -- ", BA, S, True, True, RED),
                                      _run(_val(data, {}, "agent_remarks", upper=False), BA, S, True, False, RED)]))
        blocks.append(("grid", BA, S, [
            [_r(6, "Remarks:-", _val(data, {}, "vee_remarks"), lb=True, vb=False)],
            [_k(3, "Did the Customer Applied Previously?", _val(data, {}, "previously_applied"), lb=True),
             _k(3, "Date of Previous File:-", _val(data, {}, "previous_file_date"), lb=True)],
            [_r(3, "Recommendation:-", _val(data, {}, "vee_recommendation"), lb=True, vb=False), _k(3, "", "")],
        ]))
        blocks += _reasons(data, BA, S, True, "Reasons for Not Recommended (please Tick):-")
        blocks += _signature(data, report)
    elif rt in ("tel_residence", "tel_office"):
        BA, S = "Book Antiqua", 10
        spoken = _spoken(call_logs)
        phone = _clean(spoken.get("phone_number")) or _clean(case.get("primary_phone")) or NA
        if rt == "tel_residence":
            blocks.append(("title", TITLES[rt], "Arial Black", 12))
            blocks.append(("grid", BA, S, [
                [_k(3, "Name of Applicant:-", "", lb=True), _k(3, "", _val(data, case, "applicant_name"), vb=True)],
                [_k(3, "Date of Birth:-", "", lb=True), _k(3, "", _dob(data), vb=True)],
                [_k(3, "Name of the Co-Applicant:-", "", lb=True), _k(3, "", _val(data, case, "co_applicant_name"), vb=True)],
                [_k(3, "Residence Address of the Applicant:-", "", lb=True), _k(3, "", _val({}, case, "assigned_address"), vb=True)],
                [_k(3, "Permanent Address of the Applicant:-", "", lb=True), _k(3, "", _val(data, {}, "permanent_address"), vb=True)],
            ]))
            blocks.append(("grid", BA, S, [
                [_k(3, "Contact No(Telephone /Mobile No):-", "", lb=True), _k(3, "", phone, vb=True)],
                [_k(3, "Person Spoken To:-", "", lb=True), _k(3, "", _val(spoken, {}, "person_met"), vb=True)],
                [_k(3, "Relationship:-", "", lb=True), _k(3, "", _val(spoken, {}, "relationship"), vb=True)],
                [_k(3, "Address of the Applicant Confirmed? (Y/N):-", "", lb=True), _k(3, "", _val(spoken, {}, "info_confirmed"), vb=True)],
                [_k(2, "Reference Tele Number:-", _val(data, {}, "ref_tele_number"), lb=True, vb=True),
                 _k(2, "Person Spoken:-", _val(data, {}, "ref_person_spoken"), lb=True, vb=True),
                 _k(2, "Confirmed:-", _val(data, {}, "ref_confirmed"), lb=True, vb=True)],
            ]))
        else:
            blocks.append(("title", TITLES[rt], "Book Antiqua", 12))
            blocks.append(("grid", BA, S, [
                [_k(3, "Name of Applicant:-", "", lb=True), _k(3, "", _val(data, case, "applicant_name"), vb=True)],
                [_k(3, "Employer Name & Address:-", "", lb=True), _k(3, "", _val(data, {}, "employer_name_address"), vb=True)],
                [_k(3, "Designation of the Applicant:-", "", lb=True), _k(3, "", _val(data, {}, "applicant_designation"), vb=True)],
                [_k(3, "Nature of Business /Office: -", "", lb=True), _k(3, "", _val(data, {}, "nature_of_business"), vb=True)],
                [_k(3, "No of Years at Present Employment: -", "", lb=True), _k(3, "", _val(data, {}, "years_at_employment"), vb=True)],
                [_k(3, "Office Contactable Number:-", "", lb=True), _k(3, "", phone, vb=True)],
                [_k(3, "Person Spoken To: -", "", lb=True), _k(3, "", _val(spoken, {}, "person_met"), vb=True)],
                [_k(3, "Designation: -", "", lb=True), _k(3, "", _val(data, {}, "spoken_designation"), vb=True)],
                [_k(3, "Address of the Office Confirmed? (Y/N):-", "", lb=True), _k(3, "", _val(spoken, {}, "info_confirmed"), vb=True)],
            ]))
            blocks.append(("text", [_run("Tele calling Log:-", BA, S, True)], None, 2))
        blocks.append(("table", BA, S, _call_rows(call_logs), None))
        blocks.append(("text", [_run("Outcome: C= (Confirmed), B= (Busy tone), Cl = (Call later) Nr = (No Response)", BA, S)], None, 4))
        blocks.append(("text", [_run("Tele Verification Result: -", BA, S, True), _run(" " + _val(data, {}, "tele_result"), BA, S, True)], None, 6))
        blocks += _signature(data, report)
    elif rt == "kyc":
        BA = "Book Antiqua"
        h = lambda t, it=True: (t, BLACK, True, it)  # noqa: E731
        v = lambda t: (t, BLACK, False, False)  # noqa: E731
        rows = [[h("SL NO", False), h("Name of Applicant"), h("Pan Card No."), h("Remarks"), h("Voter Card No."), h("Remarks"), h("Aadhar Card No."), h("Remarks")],
                [v("1."), v(_val(data, case, "applicant_name")), v(_val(data, {}, "kyc_pan_no")), v(_val(data, {}, "kyc_remarks_1", upper=False)),
                 v(_val(data, {}, "kyc_voter_no")), v(_val(data, {}, "kyc_remarks_2", upper=False)), v(_val(data, {}, "kyc_aadhaar_no")),
                 v(_val(data, {}, "kyc_remarks_3", upper=False))],
                [v("2."), v(_val(data, case, "kyc2_name", "co_applicant_name")), v(_val(data, {}, "kyc2_pan_no")), v(_val(data, {}, "kyc2_remarks_1", upper=False)),
                 v(_val(data, {}, "kyc2_voter_no")), v(_val(data, {}, "kyc2_remarks_2", upper=False)), v(_val(data, {}, "kyc2_aadhaar_no")),
                 v(_val(data, {}, "kyc2_remarks_3", upper=False))]]
        blocks.append(("title", TITLES[rt], "Arial Black", 12))
        blocks.append(("table", BA, 10, rows, [448945, 1444625, 905510, 704215, 911225, 704215, 929640, 704215]))  # VEE column widths
        blocks += _signature(data, report)
    elif rt == "gst":
        C, S = "Cambria", 11
        date, time = _visit_parts(data, report, "verification_datetime")
        blocks.append(("title", TITLES[rt], "Cambria", 16))
        blocks.append(("grid", C, S, [
            [_k(2, "Date of Visit:-", "", lb=True), _k(4, "", date, vb=True)],
            [_k(2, "Time of Visit:-", "", lb=True), _k(4, "", time, vb=True)],
            [_k(2, "Name of the applicant:-", "", lb=True), _k(4, "", _val(data, case, "applicant_name"), vb=True)],
            [_k(2, "Business Name:-", "", lb=True), _k(4, "", _val(data, {}, "business_name"), vb=True)],
            [_k(2, "Business Address:-", "", lb=True), _k(4, "", _val(data, {}, "business_address"), vb=True)],
            [_k(2, "Registration no.:-", "", lb=True), _k(4, "", _val(data, {}, "gst_registration_no"), vb=True)],
            [_k(2, "Designation of the applicant:-", "", lb=True), _k(4, "", _val(data, {}, "applicant_designation"), vb=True)],
            [_k(2, "Assessment year:-", "", lb=True), _k(4, "", _val(data, {}, "assessment_year"), vb=True)],
        ]))
        blocks.append(("text", [_run("Status: -", C, S, True, True), _run(_val(data, {}, "gst_status"), C, S, True)], None, 6))
        blocks.append(("box", C, S, [_run("Remarks: ", C, S, True, True), _run(_val(data, {}, "factual_remarks", upper=False), C, S)]))
        blocks += _signature(data, report)
    else:
        raise ValueError(f"No VEE format for report type {rt}")
    if photos:
        name = _clean(case.get("applicant_name")).upper()
        blocks.append(("photos", f"{name} {PHOTO_TITLES[rt]}".strip(), photos))
        blocks += _signature(data, report)
    return blocks


# ------------------------------------------------------------------ Word
def _docx_run(p, text, font, size, bold=False, italic=False, underline=False, color=RED):
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    r = p.add_run(text)
    r.font.name = font
    r._element.rPr.rFonts.set(qn("w:cs"), font)
    r._element.rPr.rFonts.set(qn("w:eastAsia"), font)
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.italic = italic
    r.font.underline = underline
    r.font.color.rgb = RGBColor.from_string(color)
    return r


def _docx_tight(p, after=0):
    from docx.shared import Pt
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = 1.0


def _docx_table(doc, n_rows, n_cols, width_in, borders=True, rel=None):
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.shared import Inches
    t = doc.add_table(rows=n_rows, cols=n_cols)
    if borders:
        t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    rel = rel or [1] * n_cols
    for row in t.rows:
        for ci, c in enumerate(row.cells):
            c.width = Inches(width_in * rel[ci] / sum(rel))
    return t


def _docx_spacer(doc, pt=6):
    from docx.shared import Pt
    p = doc.add_paragraph()
    _docx_tight(p)
    p.paragraph_format.line_spacing = Pt(pt)


def _ticks_rows(items):
    rows = []
    for i in range(0, len(items), 2):
        pair = items[i:i + 2] + [("", False)] * (2 - len(items[i:i + 2]))
        rows.append([pair[0][0], pair[0][1], pair[1][0], pair[1][1]])
    return rows


def _render_docx(blocks, meta: dict) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.shared import Inches
    from exporters import _docx_apply_header, _fit

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)      # VEE FORMAT page: Letter
    sec.left_margin = sec.right_margin = Inches(0.7)               # VEE FORMAT side margins
    sec.bottom_margin = Inches(0.5)
    _docx_apply_header(doc)                                        # AADITYA banner on every page; sets top margin
    width = (sec.page_width - sec.left_margin - sec.right_margin) / 914400
    doc.core_properties.title = meta.get("title") or ""
    doc.core_properties.subject = meta.get("subject") or ""
    doc.core_properties.identifier = meta.get("identifier") or ""

    for b in blocks:
        kind = b[0]
        if kind == "title":
            _, text, font, size = b
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _docx_tight(p, 8)
            _docx_run(p, text, font, size, bold=True, underline=True, color=BLACK)
        elif kind == "text":
            _, runs, align, after = b
            p = doc.add_paragraph()
            if align == "center":
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _docx_tight(p, after)
            for text, font, size, bold, underline, color in runs:
                _docx_run(p, text, font, size, bold=bold, underline=underline, color=color)
        elif kind == "grid":
            _, font, size, rows = b
            t = _docx_table(doc, len(rows), GRID, width)
            for ri, cells in enumerate(rows):
                col = 0
                for span, label, value, color, label_bold, value_bold in cells:
                    cell = t.cell(ri, col)
                    if span > 1:
                        cell = cell.merge(t.cell(ri, col + span - 1))
                    cell.width = Inches(width * span / GRID)
                    p = cell.paragraphs[0]
                    _docx_tight(p)
                    if label:
                        _docx_run(p, label + (" " if value else ""), font, size, bold=label_bold, color=color)
                    if value:
                        _docx_run(p, value, font, size, bold=value_bold, color=color)
                    col += span
            _docx_spacer(doc)
        elif kind == "box":
            _, font, size, runs = b
            t = _docx_table(doc, 1, 1, width)
            p = t.cell(0, 0).paragraphs[0]
            _docx_tight(p)
            for text, f, s, bold, underline, color in runs:
                _docx_run(p, text, f, s, bold=bold, underline=underline, color=color)
            _docx_spacer(doc)
        elif kind in ("table", "ticks"):
            if kind == "table":
                _, font, size, rows, rel = b
                tick_bold = False
            else:
                _, font, size, items, rel, tick_bold = b
                rows = _ticks_rows(items)
            n_cols = len(rows[0])
            t = _docx_table(doc, len(rows), n_cols, width, rel=rel)
            for ri, row in enumerate(rows):
                for ci, cellv in enumerate(row):
                    p = t.cell(ri, ci).paragraphs[0]
                    _docx_tight(p)
                    if kind == "ticks":
                        if ci % 2 == 0 and cellv:
                            _docx_run(p, cellv, font, size, bold=tick_bold, color=BLACK)
                        elif ci % 2 == 1 and cellv is True:
                            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            _docx_run(p, TICK, "Segoe UI Symbol", size, bold=True, color=BLACK)
                    elif cellv:
                        text, color, bold, italic = cellv
                        _docx_run(p, str(text), font, size if not italic else min(size, 9), bold=bold, italic=italic, color=color)
            _docx_spacer(doc)
        elif kind == "photos":
            _, title, items = b
            p = doc.add_paragraph()
            p.add_run().add_break(WD_BREAK.PAGE)
            _docx_tight(p)
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _docx_tight(p, 8)
            _docx_run(p, title, "Arial Black", 10, bold=True, underline=True, color=BLACK)
            cols = 2 if len(items) > 1 else 1
            t = _docx_table(doc, (len(items) + cols - 1) // cols, cols, width, borders=False)
            box_w, box_h = width / cols - 0.15, (PHOTO_BOX_H_IN if cols > 1 else PHOTO_SINGLE_H_IN)  # five photos fit on one page
            for i, it in enumerate(items):
                cell = t.cell(i // cols, i % cols)
                lp = cell.paragraphs[0]
                lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _docx_tight(lp, 2)
                _docx_run(lp, it["title"], "Book Antiqua", PHOTO_LABEL_PT, bold=True)
                cp = cell.add_paragraph()
                cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _docx_tight(cp, 6)
                if it.get("image"):
                    w, h = _fit(it["image"], box_w, box_h)          # keeps the photo's proportions
                    cp.add_run().add_picture(io.BytesIO(it["image"]), width=Inches(w), height=Inches(h))
                else:
                    _docx_run(cp, it.get("notice") or "Photograph missing.", "Book Antiqua", PHOTO_LABEL_PT, italic=True)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ PDF
_FONT_FILES = {
    "Book Antiqua": ("BKANT.TTF", "ANTQUAB.TTF", "ANTQUAI.TTF", "ANTQUABI.TTF"),
    "Cambria": (("cambria.ttc", 0), "cambriab.ttf", "cambriai.ttf", "cambriaz.ttf"),
    "Arial Black": ("ariblk.ttf", "ariblk.ttf", "ariblk.ttf", "ariblk.ttf"),
}
_FALLBACK = {"Book Antiqua": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
             "Cambria": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
             "Arial Black": ("Helvetica-Bold",) * 4}
_registered: dict = {}


def _font_dirs() -> list:
    dirs = [Path(d) for d in (os.environ.get("REPORT_FONT_DIR") or "").split(os.pathsep) if d]
    dirs += [Path(__file__).parent / "assets" / "fonts", Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
             Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts"]
    return [d for d in dirs if d.exists()]


def _find_font(name: str):
    for d in _font_dirs():
        hit = next((p for p in d.rglob("*") if p.name.lower() == name.lower()), None)
        if hit:
            return hit
    return None


def _pdf_fonts(family: str) -> tuple:
    """(regular, bold, italic, bold-italic) reportlab font names. Uses the real font file when it is installed on the
    server (the same font Word uses); otherwise a close built-in face, so the PDF always renders."""
    if family in _registered:
        return _registered[family]
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    names = []
    for i, spec in enumerate(_FONT_FILES[family]):
        fname, idx = (spec if isinstance(spec, tuple) else (spec, None))
        path = _find_font(fname)
        if not path:
            names = list(_FALLBACK[family])
            break
        rl = f"{family.replace(' ', '')}-{i}"
        try:
            pdfmetrics.registerFont(TTFont(rl, str(path), subfontIndex=idx) if idx is not None else TTFont(rl, str(path)))
        except Exception:
            names = list(_FALLBACK[family])
            break
        names.append(rl)
    _registered[family] = tuple(names)
    return _registered[family]


def _tick_html(size) -> str:
    """Check mark for the PDF tick boxes, from an embedded font that has the glyph (viewers do not reliably draw the
    non-embedded ZapfDingbats mark). Falls back to a bold X when no such font is installed on the server."""
    if "tick" not in _registered:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        _registered["tick"] = None
        for fname in ("seguisym.ttf", "DejaVuSans.ttf", "NotoSansSymbols2-Regular.ttf"):
            path = _find_font(fname)
            if path:
                try:
                    pdfmetrics.registerFont(TTFont("VeeTick", str(path)))
                    _registered["tick"] = "VeeTick"
                    break
                except Exception:
                    continue
    if _registered["tick"]:
        return f'<font name="VeeTick" size="{size}">{TICK}</font>'
    return _rl_span("X", "Book Antiqua", size, bold=True, color=BLACK)


def _rl_text(text: str) -> str:
    # runs of spaces are kept as typed (VEE title "K Y C    Verification    Report")
    return _rl_escape(text).replace("  ", "&nbsp; ")


def _rl_escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _rl_span(text, family, size, bold=False, italic=False, underline=False, color=RED):
    f = _pdf_fonts(family)[(1 if bold else 0) + (2 if italic else 0)]
    t = f'<font name="{f}" size="{size}" color="#{color}">{_rl_text(text)}</font>'
    return f"<u>{t}</u>" if underline else t


def _rl_photo(raw: bytes, w: float, h: float):
    """ReportLab image flowable for a stored JPEG. ReportLab embeds a JPEG unchanged (DCTDecode) but, by default, fully
    decodes it just to name it internally (about 0.5 s per 12 MP photo). The name is taken from the file's SHA-256
    instead; the embedded bytes are identical either way. Non-JPEG input keeps ReportLab's default handling."""
    import hashlib
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image as RLImage

    class _StoredJpeg(ImageReader):
        def __init__(self, data: bytes):
            super().__init__(io.BytesIO(data))
            self._raw = data
            if not hasattr(self, "_dataA"):
                self._dataA = None

        def getRGBData(self):
            if getattr(self, "jpeg_fh", None):
                return hashlib.sha256(self._raw).digest()
            return super().getRGBData()

    fl = RLImage(io.BytesIO(raw), width=w, height=h)
    fl._img = _StoredJpeg(raw)
    return fl


def _render_pdf(blocks, meta: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from PIL import Image as PILImage
    from exporters import DOCX_HEADER_BODY_GAP, DOCX_HEADER_DISTANCE, _fit, report_header_image, report_header_is_legacy

    page_w, page_h = 8.5 * inch, 11 * inch
    side = 0.7 * inch
    width = page_w - 2 * side
    hdr_dist = DOCX_HEADER_DISTANCE / 914400 * inch
    gap = DOCX_HEADER_BODY_GAP / 914400 * inch
    header_img = report_header_image()
    if header_img:
        with PILImage.open(header_img) as im:
            hw, hh = im.size
        banner_h = width * hh / hw
    else:
        banner_h = 0

    def on_page(canvas, _doc):
        if header_img:  # same artwork as the Word header, on every page, aspect ratio kept
            canvas.drawImage(str(header_img), side, page_h - hdr_dist - banner_h, width=width, height=banner_h, mask="auto")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(page_w, page_h), leftMargin=side, rightMargin=side,
                            topMargin=hdr_dist + banner_h + gap, bottomMargin=0.5 * inch,
                            title=meta.get("title") or "", subject=meta.get("subject") or "", author="AADITYA ENTERPRISE" if report_header_is_legacy() else os.environ.get("COMPANY_NAME", "CheckSphere"))
    story = []
    base = ParagraphStyle("vee", leading=12, spaceBefore=0, spaceAfter=0)
    pad = [("LEFTPADDING", (0, 0), (-1, -1), 5.4), ("RIGHTPADDING", (0, 0), (-1, -1), 5.4),
           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    grid_line = [("GRID", (0, 0), (-1, -1), 0.5, colors.black)]

    def para(html, size, align=None):
        st = base.clone("x", leading=size * 1.22)
        if align:
            st.alignment = align
        return Paragraph(html, st)

    def runs_html(runs):
        return "".join(_rl_span(t, f, s, bold=b, underline=u, color=c) for t, f, s, b, u, c in runs)

    for b in blocks:
        kind = b[0]
        if kind == "title":
            _, text, font, size = b
            story.append(para(_rl_span(text, font, size, bold=True, underline=True, color=BLACK), size, TA_CENTER))
            story.append(Spacer(1, 8))
        elif kind == "text":
            _, runs, align, after = b
            size = max(r[2] for r in runs)
            story.append(para(runs_html(runs), size, TA_CENTER if align == "center" else None))
            if after:
                story.append(Spacer(1, after))
        elif kind == "grid":
            _, font, size, rows = b
            data, spans = [], []
            for ri, cells in enumerate(rows):
                row, col = [""] * GRID, 0
                for span, label, value, color, label_bold, value_bold in cells:
                    html = ""
                    if label:
                        html += _rl_span(label + (" " if value else ""), font, size, bold=label_bold, color=color)
                    if value:
                        html += _rl_span(value, font, size, bold=value_bold, color=color)
                    row[col] = para(html, size)
                    if span > 1:
                        spans.append(("SPAN", (col, ri), (col + span - 1, ri)))
                    col += span
                data.append(row)
            t = Table(data, colWidths=[width / GRID] * GRID)
            t.setStyle(TableStyle(grid_line + pad + spans))
            story += [t, Spacer(1, 6)]
        elif kind == "box":
            _, font, size, runs = b
            t = Table([[para(runs_html(runs), size)]], colWidths=[width])
            t.setStyle(TableStyle(grid_line + pad))
            story += [t, Spacer(1, 6)]
        elif kind in ("table", "ticks"):
            if kind == "table":
                _, font, size, rows, rel = b
                tick_bold = False
            else:
                _, font, size, items, rel, tick_bold = b
                rows = _ticks_rows(items)
            n = len(rows[0])
            rel = rel or [1] * n
            data = []
            for row in rows:
                out = []
                for ci, cellv in enumerate(row):
                    if kind == "ticks":
                        if ci % 2 == 0:
                            out.append(para(_rl_span(cellv, font, size, bold=tick_bold, color=BLACK), size) if cellv else "")
                        else:
                            out.append(para(_tick_html(size), size, TA_CENTER) if cellv is True else "")
                    elif cellv:
                        text, color, bold, italic = cellv
                        out.append(para(_rl_span(str(text), font, size if not italic else min(size, 9), bold=bold, italic=italic, color=color), size))
                    else:
                        out.append("")
                data.append(out)
            t = Table(data, colWidths=[width * r / sum(rel) for r in rel])
            t.setStyle(TableStyle(grid_line + pad))
            story += [t, Spacer(1, 6)]
        elif kind == "photos":
            _, title, items = b
            story.append(PageBreak())
            story.append(para(_rl_span(title, "Arial Black", 10, bold=True, underline=True, color=BLACK), 10, TA_CENTER))
            story.append(Spacer(1, 8))
            cols = 2 if len(items) > 1 else 1
            box_w, box_h = width / cols - 0.15 * inch, (PHOTO_BOX_H_IN if cols > 1 else PHOTO_SINGLE_H_IN) * inch
            cells = []
            for it in items:
                cell = [para(_rl_span(it["title"], "Book Antiqua", PHOTO_LABEL_PT, bold=True), PHOTO_LABEL_PT, TA_CENTER),
                        Spacer(1, 2)]
                if it.get("image"):
                    w, h = _fit(it["image"], box_w, box_h)          # keeps the photo's proportions
                    cell.append(_rl_photo(it["image"], w, h))
                else:
                    cell.append(para(_rl_span(it.get("notice") or "Photograph missing.", "Book Antiqua", PHOTO_LABEL_PT,
                                              italic=True), PHOTO_LABEL_PT, TA_CENTER))
                cells.append(cell)
            rows = [cells[i:i + cols] + [""] * (cols - len(cells[i:i + cols])) for i in range(0, len(cells), cols)]
            t = Table(rows, colWidths=[width / cols] * cols)
            t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            story.append(t)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


# ------------------------------------------------------------------ public API
def _photos(evidence: list, config: dict, images: dict) -> list:
    """One labelled cell per photo category, in the form's photo-slot order: the case's own stored watermarked
    photograph (embedded bytes, never a link), or a missing-evidence notice. Time/GPS are on the watermark itself."""
    from exporters import photo_grid_items
    return [{"title": it["title"], "image": it["image"], "notice": it["notice"]}
            for it in photo_grid_items(evidence, config, images)]


def _meta(case: dict) -> dict:
    title = TITLES.get(case.get("report_type"), "Verification Report")
    return {"title": f"{case.get('internal_case_id', '')} - {title}".strip(" -"), "subject": title,
            "identifier": case.get("internal_case_id") or ""}


def build_vee_docx(case, report, evidence, config, call_logs=None, images: dict | None = None) -> bytes:
    return _render_docx(build_layout(case, report, call_logs or [], _photos(evidence, config, images or {})), _meta(case))


def build_vee_pdf(case, report, evidence, config, call_logs=None, images: dict | None = None) -> bytes:
    return _render_pdf(build_layout(case, report, call_logs or [], _photos(evidence, config, images or {})), _meta(case))
