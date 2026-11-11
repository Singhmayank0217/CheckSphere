"""Report type configuration: fields, photo slots, categories. Also call results and safe language."""
DISCLAIMER = ("This report records field observations and authorised verification results only. "
              "It does not assess creditworthiness, title, income adequacy, document authenticity, or loan eligibility.")

PHONE_RESULTS = ["Confirmed", "Busy", "No Response", "Switched Off", "Call Later", "Invalid Number", "Refused", "Other"]

DOC_OUTCOMES = ["Confirmed", "Could Not Be Independently Verified", "Mismatch/Exception"]


def _case_info(applicant_label: str = "Applicant Name", coapplicant: bool = False) -> dict:
    fields = [
        {"key": "client_name", "label": "Client Name", "type": "text", "required": True},
        {"key": "branch_name", "label": "Branch Name", "type": "text", "required": True},
        {"key": "internal_case_id", "label": "Internal Case ID", "type": "text", "required": True},
        {"key": "client_case_id", "label": "Client Case ID", "type": "text", "required": True},
        {"key": "applicant_name", "label": applicant_label, "type": "text", "required": True},
    ]
    if coapplicant:
        fields.append({"key": "co_applicant_name", "label": "Co-applicant Name", "type": "text", "required": False})
    return {"title": "Case Information", "fields": fields}


def _visit_info() -> dict:
    return {"title": "Visit Details", "fields": [
        {"key": "assigned_address", "label": "Assigned Address", "type": "textarea", "required": True},
        {"key": "observed_address", "label": "Observed Address", "type": "textarea", "required": True},
        {"key": "visit_datetime", "label": "Date & Time of Visit", "type": "text", "required": True},
        {"key": "agent_name", "label": "Agent Name & ID", "type": "text", "required": True},
        {"key": "person_met", "label": "Person Met", "type": "text", "required": True},
        {"key": "relationship", "label": "Relationship with Applicant", "type": "text", "required": True},
    ]}


RESIDENCE_FINDINGS = {"title": "Findings", "fields": [
    {"key": "address_outcome", "label": "Address Outcome", "type": "select",
     "options": ["Confirmed", "Not Confirmed", "Inconclusive"], "required": True},
    {"key": "residents_count", "label": "Number of Residents (if confirmed)", "type": "number", "required": False},
    {"key": "residence_status", "label": "Residence Status", "type": "select",
     "options": ["Owned", "Rented", "Company Accommodation", "Other", "Not Confirmed"], "required": True},
    {"key": "years_at_residence", "label": "Years at Residence (if stated)", "type": "text", "required": False},
    {"key": "landmark", "label": "Landmark", "type": "text", "required": False},
    {"key": "accessibility", "label": "Accessibility", "type": "text", "required": False},
    {"key": "locality", "label": "Locality", "type": "select",
     "options": ["Urban", "Semi-urban", "Rural"], "required": True},
    {"key": "property_type", "label": "Property Type", "type": "text", "required": False},
    {"key": "exterior_observation", "label": "Exterior Observation", "type": "textarea", "required": True},
    {"key": "interior_observation", "label": "Interior Observation (only where consent given)", "type": "textarea", "required": False},
    {"key": "neighbour_verification", "label": "Neighbour Verification (only where permitted)", "type": "textarea", "required": False},
    {"key": "neighbour_contact", "label": "Neighbour Name & Contact (only where authorised)", "type": "text", "required": False},
    {"key": "agent_remarks", "label": "Agent Remarks (factual observations only)", "type": "textarea", "required": False},
    {"key": "exceptions", "label": "Exceptions / Mismatches", "type": "textarea", "required": False},
]}

OFFICE_FINDINGS = {"title": "Findings", "fields": [
    {"key": "person_designation", "label": "Person's Designation", "type": "text", "required": False},
    {"key": "relationship_to_business", "label": "Relationship to Applicant/Business", "type": "text", "required": True},
    {"key": "applicant_designation", "label": "Applicant Designation / Business Role (if confirmed)", "type": "text", "required": False},
    {"key": "nature_of_business", "label": "Nature of Business / Office", "type": "text", "required": True},
    {"key": "board_present", "label": "Business Board Present", "type": "select",
     "options": ["Yes", "No", "Not Observed"], "required": True},
    {"key": "business_operational", "label": "Business Operational", "type": "select",
     "options": ["Yes", "No", "Inconclusive"], "required": True},
    {"key": "years_employed", "label": "Years in Employment / Business (if confirmed)", "type": "text", "required": False},
    {"key": "premises_type", "label": "Premises Type", "type": "text", "required": False},
    {"key": "landmark", "label": "Landmark", "type": "text", "required": False},
    {"key": "accessibility", "label": "Accessibility", "type": "text", "required": False},
    {"key": "exterior_observation", "label": "Exterior Observation", "type": "textarea", "required": True},
    {"key": "agent_remarks", "label": "Agent Remarks (factual observations only)", "type": "textarea", "required": False},
    {"key": "exceptions", "label": "Exceptions / Mismatches", "type": "textarea", "required": False},
]}

PHOTO_EXTERIOR = {"key": "exterior", "label": "Exterior Photo (house/office/business)", "required": True}
PHOTO_SELFIE = {"key": "selfie", "label": "Selfie at Location (with applicant/family member where required)", "required": True}
PHOTO_DOC = {"key": "document", "label": "Supporting Document / Evidence Photo", "required": True}
PHOTO_DOC_OPT = {"key": "document", "label": "Supporting Document / Evidence Photo", "required": False}

DOC_FIELDS = {"title": "Verification Details", "fields": [
    {"key": "applicant_name", "label": "Applicant Name", "type": "text", "required": True},
    {"key": "document_type", "label": "Document Type", "type": "text", "required": True},
    {"key": "document_period", "label": "Document Period / Date", "type": "text", "required": False},
    {"key": "document_ref_no", "label": "Document Reference Number", "type": "text", "required": False},
    {"key": "verification_method", "label": "Verification Method", "type": "select",
     "options": ["Tele-verification", "Physical Document Review", "Authorised Source Lookup", "Email Confirmation", "Site Visit"], "required": True},
    {"key": "authorised_source", "label": "Authorised Source Used", "type": "text", "required": True},
    {"key": "verification_datetime", "label": "Verification Date & Time", "type": "text", "required": True},
    {"key": "verifier_name", "label": "Agent / Verifier Name & ID", "type": "text", "required": True},
    {"key": "outcome", "label": "Outcome", "type": "select", "options": DOC_OUTCOMES, "required": True},
    {"key": "factual_remarks", "label": "Factual Remarks", "type": "textarea", "required": False},
    {"key": "exceptions", "label": "Exceptions / Mismatches", "type": "textarea", "required": False},
]}

REPORT_TYPES = {
    "residence_applicant": {
        "key": "residence_applicant", "name": "Applicant Residence Verification", "category": "physical",
        "requires_gps": True, "selfie_required": True, "min_call_attempts": 0,
        "sections": [_case_info(), _visit_info(), RESIDENCE_FINDINGS],
        "photo_slots": [PHOTO_EXTERIOR, PHOTO_SELFIE, PHOTO_DOC_OPT],
    },
    "residence_coapplicant": {
        "key": "residence_coapplicant", "name": "Co-applicant Residence Verification", "category": "physical",
        "requires_gps": True, "selfie_required": True, "min_call_attempts": 0,
        "sections": [_case_info("Co-applicant Name"), _visit_info(), RESIDENCE_FINDINGS],
        "photo_slots": [PHOTO_EXTERIOR, PHOTO_SELFIE, PHOTO_DOC_OPT],
    },
    "business_applicant": {
        "key": "business_applicant", "name": "Applicant Business Verification", "category": "physical",
        "requires_gps": True, "selfie_required": False, "min_call_attempts": 0,
        "sections": [
            _case_info(),
            {"title": "Visit Details", "fields": [
                {"key": "assigned_address", "label": "Assigned Office/Business Address", "type": "textarea", "required": True},
                {"key": "observed_address", "label": "Observed Office/Business Address", "type": "textarea", "required": True},
                {"key": "visit_datetime", "label": "Date & Time of Visit", "type": "text", "required": True},
                {"key": "agent_name", "label": "Agent Name & ID", "type": "text", "required": True},
                {"key": "employer_name", "label": "Employer / Business Name", "type": "text", "required": True},
                {"key": "person_met", "label": "Person Met", "type": "text", "required": True},
            ]},
            OFFICE_FINDINGS,
        ],
        "photo_slots": [PHOTO_EXTERIOR, PHOTO_DOC_OPT],
    },
    "office_coapplicant": {
        "key": "office_coapplicant", "name": "Co-applicant Office Verification", "category": "physical",
        "requires_gps": True, "selfie_required": False, "min_call_attempts": 0,
        "sections": [
            _case_info("Co-applicant Name"),
            {"title": "Visit Details", "fields": [
                {"key": "assigned_address", "label": "Assigned Office Address", "type": "textarea", "required": True},
                {"key": "observed_address", "label": "Observed Office Address", "type": "textarea", "required": True},
                {"key": "visit_datetime", "label": "Date & Time of Visit", "type": "text", "required": True},
                {"key": "agent_name", "label": "Agent Name & ID", "type": "text", "required": True},
                {"key": "employer_name", "label": "Employer Name", "type": "text", "required": True},
                {"key": "person_met", "label": "Person Met", "type": "text", "required": True},
            ]},
            OFFICE_FINDINGS,
        ],
        "photo_slots": [PHOTO_EXTERIOR, PHOTO_DOC_OPT],
    },
    "seller": {
        "key": "seller", "name": "Seller Residence/Office/Business Verification", "category": "physical",
        "requires_gps": True, "selfie_required": False, "min_call_attempts": 0,
        "sections": [
            _case_info("Seller Name"),
            _visit_info(),
            RESIDENCE_FINDINGS,
        ],
        "photo_slots": [PHOTO_EXTERIOR, PHOTO_DOC_OPT],
    },
    "tel_residence": {
        "key": "tel_residence", "name": "Residence Telephone Verification", "category": "telephone",
        "requires_gps": False, "selfie_required": False, "min_call_attempts": 3,
        "sections": [
            _case_info(),
            {"title": "Telephone Verification Summary", "fields": [
                {"key": "information_confirmed", "label": "Information Confirmed", "type": "textarea", "required": True},
                {"key": "factual_notes", "label": "Factual Notes", "type": "textarea", "required": False},
                {"key": "next_attempt", "label": "Next Attempt Date/Time (if required)", "type": "text", "required": False},
                {"key": "exceptions", "label": "Exceptions / Mismatches", "type": "textarea", "required": False},
            ]},
        ],
        "photo_slots": [PHOTO_DOC_OPT],
    },
    "tel_office": {
        "key": "tel_office", "name": "Office/Business Telephone Verification", "category": "telephone",
        "requires_gps": False, "selfie_required": False, "min_call_attempts": 3,
        "sections": [
            _case_info(),
            {"title": "Telephone Verification Summary", "fields": [
                {"key": "information_confirmed", "label": "Information Confirmed", "type": "textarea", "required": True},
                {"key": "factual_notes", "label": "Factual Notes", "type": "textarea", "required": False},
                {"key": "next_attempt", "label": "Next Attempt Date/Time (if required)", "type": "text", "required": False},
                {"key": "exceptions", "label": "Exceptions / Mismatches", "type": "textarea", "required": False},
            ]},
        ],
        "photo_slots": [PHOTO_DOC_OPT],
    },
    "income": {
        "key": "income", "name": "Income Verification", "category": "document",
        "requires_gps": False, "selfie_required": False, "min_call_attempts": 0,
        "sections": [_case_info(), DOC_FIELDS],
        "photo_slots": [PHOTO_DOC],
    },
    "kyc": {
        "key": "kyc", "name": "KYC Verification", "category": "document",
        "requires_gps": False, "selfie_required": False, "min_call_attempts": 0,
        "sections": [_case_info(), DOC_FIELDS],
        "photo_slots": [PHOTO_DOC],
    },
    "bank_account": {
        "key": "bank_account", "name": "Other Bank Account Verification (assigned only)", "category": "document",
        "requires_gps": False, "selfie_required": False, "min_call_attempts": 0,
        "sections": [_case_info(), DOC_FIELDS],
        "photo_slots": [PHOTO_DOC],
    },
    "custom": {
        "key": "custom", "name": "Custom Verification Form", "category": "document",
        "requires_gps": False, "selfie_required": False, "min_call_attempts": 0,
        "sections": [],  # filled from settings custom_form_fields
        "photo_slots": [PHOTO_DOC_OPT],
    },
}


def config_for(report_type: str, settings: dict | None = None) -> dict:
    cfg = REPORT_TYPES.get(report_type) or REPORT_TYPES["custom"]
    cfg = dict(cfg)
    if report_type == "custom" or not cfg["sections"]:
        fields = (settings or {}).get("custom_form_fields") or []
        cfg["sections"] = [{"title": "Custom Verification Details", "fields": fields}]
    if cfg.get("min_call_attempts", 0) and settings:
        cfg["min_call_attempts"] = int(settings.get("telephone_min_attempts", cfg["min_call_attempts"]))
    return cfg


def report_type_choices() -> list:
    return [{"key": k, "name": v["name"], "category": v["category"]} for k, v in REPORT_TYPES.items()]
