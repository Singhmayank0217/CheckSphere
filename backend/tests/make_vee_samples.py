"""Generate SAMPLE VEE-format Word + PDF reports for review (fictional data, synthetic photos; no database, no file storage).

Run from the repo root:  .venv\\Scripts\\python.exe backend\\tests\\make_vee_samples.py [OUT_DIR]
Default OUT_DIR: docs/report-format/samples
"""
import io
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")  # core imports need a value; nothing connects
os.environ.setdefault("DB_NAME", "unused")

from PIL import Image, ImageDraw  # noqa: E402

import watermark  # noqa: E402
from report_config import config_for  # noqa: E402
from reports_routes import apply_server_fields, validate_submission  # noqa: E402
from vee_report import build_vee_docx, build_vee_pdf  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else BACKEND.parent / "docs" / "report-format" / "samples"
VISIT = datetime(2026, 11, 13, 11, 42, tzinfo=timezone.utc)
VISIT_IST = "13-Nov-2026 05:12:30 PM IST"
PIN = (22.6411, 88.3549)


def scene(seed: int, w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), (120 + seed * 20 % 100, 150, 190 - seed * 15 % 80))
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(h * 0.62), w, h], fill=(110, 105, 95))                       # road
    d.rectangle([int(w * 0.18), int(h * 0.25), int(w * 0.78), int(h * 0.64)], fill=(225, 210, 180))  # building
    for i in range(4):
        x = int(w * (0.24 + i * 0.13))
        d.rectangle([x, int(h * 0.34), x + int(w * 0.07), int(h * 0.45)], fill=(70, 90, 120))
    d.rectangle([int(w * 0.44), int(h * 0.48), int(w * 0.52), int(h * 0.64)], fill=(90, 60, 40))
    return img


def wm_photo(seed, slot, w=1600, h=1200, minutes=0):
    lines = watermark.watermark_lines(VISIT + timedelta(minutes=minutes), PIN[0], PIN[1],
                                      {"text": "Sample Lane, Belur, Howrah, West Bengal 711202", "status": "approximate"}, slot)
    data, _ = watermark.render_watermark(scene(seed, w, h), lines, slot)
    return data


def evidence_set(slots):
    ev, images = [], {}
    for i, (slot, (w, h)) in enumerate(slots):
        eid = f"e{i}"
        ev.append({"id": eid, "kind": "photo", "slot": slot, "captured_at": VISIT + timedelta(minutes=i)})
        images[eid] = wm_photo(i + 1, slot, w, h, i)
    return ev, images


FIELD = [("exterior", (1600, 1200)), ("exterior_2", (1600, 1200)), ("interior", (1600, 1200)), ("selfie", (1200, 1600)), ("document", (1200, 1600))]
DOC = [("document", (1200, 1600))]

CASES = {
    "Applicant_Residence_Verification": (
        {"report_type": "residence_applicant", "internal_case_id": "CSV-SAMPLE-01", "client_name": "Sample Bank", "branch_name": "Belur Branch",
         "applicant_name": "Rahul Verma", "loan_type": "Home Loan", "assigned_address": "12 Sample Lane, Belur, Howrah 711202"},
        {"client_name": "Sample Bank", "branch_name": "Belur Branch", "internal_case_id": "CSV-SAMPLE-01", "client_case_id": "",
         "applicant_name": "Rahul Verma", "observed_address": "12 Sample Lane, Belur, Howrah 711202", "visit_datetime": VISIT_IST,
         "agent_name": "Sample Agent (AGT101)", "person_met": "Self", "relationship": "Self", "address_outcome": "Confirmed",
         "residents_count": "4", "residence_status": "Owned", "years_at_residence": "Since birth", "landmark": "Near Shiv Mandir",
         "accessibility": "Easy", "locality": "Urban", "property_type": "House", "exterior_observation": "Two-storey house, name plate seen.",
         "interior_observation": "", "neighbour_verification": "", "neighbour_contact": "",
         "agent_remarks": "I visited the provided address and met the applicant, who confirmed the address. A neighbour also confirmed that the applicant lives here.",
         "exceptions": "", "applicant_dob": "1988-08-05", "address_confirmed_by": "Applicant / Neighbour", "marital_status": "Married",
         "earning_members": "1", "approx_value": "Rs. 45,00,000", "approx_rent": "N/A", "unit": "S-1", "roof_type": "Cemented",
         "vehicle": "Two wheeler - 1", "assets_seen": "Yes", "vee_remarks": "Positive", "vee_recommendation": "Yes",
         "loan_type": "Home Loan", "accommodation_type": "House", "interior_condition": "Good", "standard_of_living": "Medium",
         "approx_area_sqft": "700+", "previously_applied": "No", "previous_file_date": "N/A", "not_recommended_reasons": "",
         "nb_applicant_name": "", "nb_person_met": "", "nb_relationship": "", "nb_applicant_age": "", "nb_residents": "",
         "nb_years_lived": "", "nb_occupation": ""},
        FIELD, []),
    "CoApplicant_Residence_Not_Recommended": (
        {"report_type": "residence_coapplicant", "internal_case_id": "CSV-SAMPLE-05", "client_name": "Sample Bank", "branch_name": "Belur Branch",
         "applicant_name": "Sunita Verma", "loan_type": "Home Loan", "assigned_address": "9 Sample Lane, Liluah, Howrah 711204"},
        {"client_name": "Sample Bank", "branch_name": "Belur Branch", "internal_case_id": "CSV-SAMPLE-05", "client_case_id": "",
         "applicant_name": "Sunita Verma", "co_applicant_name": "", "observed_address": "9 Sample Lane, Liluah, Howrah 711204", "visit_datetime": VISIT_IST,
         "agent_name": "Sample Agent (AGT101)", "person_met": "Neighbour", "relationship": "Neighbour", "address_outcome": "Inconclusive",
         "residents_count": "Not known", "residence_status": "Rented", "years_at_residence": "Not known", "landmark": "Near Liluah station",
         "accessibility": "Narrow lane", "locality": "Semi-urban", "property_type": "Flat", "exterior_observation": "Door locked at the time of visit.",
         "interior_observation": "", "neighbour_verification": "Neighbour said the family moved out last month.", "neighbour_contact": "",
         "agent_remarks": "I visited the provided address and found the house locked. A neighbour said the family moved out last month.",
         "exceptions": "House locked", "applicant_dob": "1991-03-02", "address_confirmed_by": "Neighbour", "marital_status": "Married",
         "earning_members": "Not known", "approx_value": "", "approx_rent": "Rs. 6,000", "unit": "S-2", "roof_type": "Tin",
         "vehicle": "None seen", "assets_seen": "No", "vee_remarks": "Negative", "vee_recommendation": "No",
         "loan_type": "Home Loan", "accommodation_type": "Flat", "interior_condition": "Not seen", "standard_of_living": "",
         "approx_area_sqft": "", "previously_applied": "Not Known", "previous_file_date": "",
         "not_recommended_reasons": "3. Negative Feedback from Neighbor; 9. False & Misleading information",
         "nb_applicant_name": "Sunita Verma", "nb_person_met": "Mr. Roy", "nb_relationship": "Neighbour", "nb_applicant_age": "35",
         "nb_residents": "3", "nb_years_lived": "2", "nb_occupation": "Housewife"},
        FIELD, []),
    "Office_Verification": (
        {"report_type": "office_coapplicant", "internal_case_id": "CSV-SAMPLE-02", "client_name": "Sample Bank", "branch_name": "Belur Branch",
         "applicant_name": "Priya Verma", "assigned_address": "3rd Floor, 45 Sample Road, Howrah 711101"},
        {"client_name": "Sample Bank", "branch_name": "Belur Branch", "internal_case_id": "CSV-SAMPLE-02", "client_case_id": "BANK-REF-1001",
         "applicant_name": "Priya Verma", "observed_address": "3rd Floor, 45 Sample Road, Howrah 711101", "visit_datetime": VISIT_IST,
         "agent_name": "Sample Agent (AGT101)", "employer_name": "Sample Engineering Pvt Ltd", "person_met": "Amit Das",
         "person_designation": "HR Manager", "relationship_to_business": "Colleague", "applicant_designation": "Senior Accountant",
         "nature_of_business": "Service", "board_present": "Yes", "business_operational": "Yes", "years_employed": "6 years",
         "premises_type": "Commercial", "landmark": "Opp. Howrah Maidan", "accessibility": "Easy", "exterior_observation": "Company board seen at entrance.",
         "agent_remarks": "I visited the provided address and met Mr. Amit Das (HR Manager), who confirmed the applicant's office address and employment.",
         "exceptions": "", "applicant_dob": "1990-02-14", "office_phone": "033-2600-0000", "employment_terms": "Permanent",
         "employer_type": "Pvt", "vee_remarks": "Positive", "vee_recommendation": "Yes",
         "previous_employment": "N/A", "year_of_establishment": "1998", "office_area_sqft": "2500", "employees_count": "40",
         "branches_count": "2", "office_assets_seen": "Yes", "neighbour_feedback": "Good", "previously_applied": "No",
         "previous_file_date": "", "not_recommended_reasons": ""},
        FIELD, []),
    "KYC_Verification": (
        {"report_type": "kyc", "internal_case_id": "CSV-SAMPLE-03", "client_name": "Sample Bank", "branch_name": "Belur Branch", "applicant_name": "Rahul Verma"},
        {"client_name": "Sample Bank", "branch_name": "Belur Branch", "internal_case_id": "CSV-SAMPLE-03", "client_case_id": "",
         "applicant_name": "Rahul Verma", "document_type": "PAN, Voter ID, Aadhaar", "document_period": "", "document_ref_no": "",
         "verification_method": "Authorised Source Lookup", "authorised_source": "Original documents sighted", "verification_datetime": VISIT_IST,
         "verifier_name": "Sample Agent (AGT101)", "outcome": "Confirmed", "factual_remarks": "", "exceptions": "",
         "kyc_pan_no": "ABCDE1234F", "kyc_remarks_1": "Positive", "kyc_voter_no": "N/A", "kyc_remarks_2": "N/A",
         "kyc_aadhaar_no": "XXXX XXXX 1234", "kyc_remarks_3": "Positive",
         "kyc2_name": "Sunita Verma", "kyc2_pan_no": "PQRSV6789K", "kyc2_remarks_1": "Positive", "kyc2_voter_no": "N/A",
         "kyc2_remarks_2": "N/A", "kyc2_aadhaar_no": "XXXX XXXX 9876", "kyc2_remarks_3": "Positive"},
        DOC, []),
    "GST_Verification": (
        {"report_type": "gst", "internal_case_id": "CSV-SAMPLE-04", "client_name": "Sample Bank", "branch_name": "Belur Branch", "applicant_name": "Rahul Verma"},
        {"client_name": "Sample Bank", "branch_name": "Belur Branch", "internal_case_id": "CSV-SAMPLE-04", "client_case_id": "",
         "applicant_name": "Rahul Verma", "verification_datetime": VISIT_IST, "business_name": "Verma Traders",
         "business_address": "7 Sample Market, Belur, Howrah 711202", "gst_registration_no": "19ABCDE1234F1Z5",
         "applicant_designation": "Proprietor", "assessment_year": "2025-26", "gst_status": "Positive",
         "factual_remarks": "I checked the original G.S.T. certificate and also checked it at the website https://services.gst.gov.in/services/searchtp. The registration for the assessment year 2025-26 is active.",
         "verifier_name": "Sample Agent (AGT101)"},
        DOC, []),
    "Residence_Tele_Verification": (
        {"report_type": "tel_residence", "internal_case_id": "CSV-SAMPLE-06", "client_name": "Sample Bank", "branch_name": "Belur Branch",
         "applicant_name": "Rahul Verma", "co_applicant_name": "Sunita Verma", "primary_phone": "98300 00000",
         "assigned_address": "12 Sample Lane, Belur, Howrah 711202"},
        {"client_name": "Sample Bank", "branch_name": "Belur Branch", "internal_case_id": "CSV-SAMPLE-06", "client_case_id": "",
         "applicant_name": "Rahul Verma", "information_confirmed": "Address and residence confirmed by the applicant.",
         "factual_notes": "", "next_attempt": "", "exceptions": "", "applicant_dob": "1988-08-05",
         "permanent_address": "Same as above", "ref_tele_number": "98300 11111", "ref_person_spoken": "Anil Verma (brother)",
         "ref_confirmed": "Yes", "tele_result": "Positive", "agent_name": "Sample Agent (AGT101)"},
        DOC, "res"),
    "Office_Tele_Verification": (
        {"report_type": "tel_office", "internal_case_id": "CSV-SAMPLE-07", "client_name": "Sample Bank", "branch_name": "Belur Branch",
         "applicant_name": "Priya Verma", "primary_phone": "033-2600-0000", "assigned_address": "3rd Floor, 45 Sample Road, Howrah 711101"},
        {"client_name": "Sample Bank", "branch_name": "Belur Branch", "internal_case_id": "CSV-SAMPLE-07", "client_case_id": "",
         "applicant_name": "Priya Verma", "information_confirmed": "Employment confirmed by HR.", "factual_notes": "", "next_attempt": "",
         "exceptions": "", "employer_name_address": "Sample Engineering Pvt Ltd, 45 Sample Road, Howrah 711101",
         "applicant_designation": "Senior Accountant", "nature_of_business": "Office", "years_at_employment": "6",
         "spoken_designation": "HR Manager", "tele_result": "Positive", "agent_name": "Sample Agent (AGT101)"},
        DOC, "off"),
}

CALLS = {
    "res": [{"attempt_at": VISIT + timedelta(minutes=m), "result": r, "phone_number": "98300 00000", "person_met": pm,
             "relationship": rel, "info_confirmed": ic} for m, r, pm, rel, ic in (
        (0, "No Response", "", "", ""), (40, "Busy", "", "", ""), (95, "Confirmed", "Self", "Self", "Yes"))],
    "off": [{"attempt_at": VISIT + timedelta(minutes=m), "result": r, "phone_number": "033-2600-0000", "person_met": pm,
             "relationship": rel, "info_confirmed": ic} for m, r, pm, rel, ic in (
        (0, "Call Later", "", "", ""), (30, "No Response", "", "", ""), (60, "Busy", "", "", ""),
        (120, "Confirmed", "Amit Das", "Colleague", "Yes"))],
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ok = True
    for name, (case, data, slots, calls) in CASES.items():
        call_logs = CALLS.get(calls, []) if isinstance(calls, str) else calls
        cfg = config_for(case["report_type"], {})
        ev, images = evidence_set(slots)
        data = apply_server_fields(case, data, cfg, ev, at_submit=True)  # exactly what the server does on submit
        missing, problems, blocked = validate_submission(data, {"lat": PIN[0], "lon": PIN[1], "accuracy": 6}, True, cfg, ev, max(3, len(call_logs)),
                                                         {"blocked_words": ["genuine", "good reputation", "satisfactory", "positive", "negative"]})
        if missing or problems or blocked:
            ok = False
            print(f"{name}: sample data does not pass the form rules: {missing} {problems} {blocked}")
        report = {"version": 1, "data": data, "declaration": True}
        (OUT / f"SAMPLE_{name}.docx").write_bytes(build_vee_docx(case, report, ev, cfg, call_logs, images))
        (OUT / f"SAMPLE_{name}.pdf").write_bytes(build_vee_pdf(case, report, ev, cfg, call_logs, images))
        print(f"wrote SAMPLE_{name}.docx / .pdf")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
