"""CheckSphere core: DB connection, base document models, masking, audit, settings."""
import os
import re
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Annotated

from bson import ObjectId
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field, BeforeValidator

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
# SERVERLESS_MODE=true (Railway Serverless): background jobs run on demand instead of on timers, and the MongoDB
# driver polls the cluster rarely and drops idle connections, so the service has a chance to go idle and sleep.
SERVERLESS_MODE = os.environ.get("SERVERLESS_MODE", "").strip().lower() == "true"
_mongo_opts: dict = {"tz_aware": True}
if SERVERLESS_MODE:
    _mongo_opts.update(heartbeatFrequencyMS=int(os.environ.get("MONGO_HEARTBEAT_MS", "900000")),
                       maxIdleTimeMS=int(os.environ.get("MONGO_MAX_IDLE_MS", "60000")), minPoolSize=0)
client = AsyncIOMotorClient(mongo_url, **_mongo_opts)
db = client[os.environ["DB_NAME"]]

COMPANY_NAME = os.environ.get("COMPANY_NAME", "CheckSphere")


def now() -> datetime:
    return datetime.now(timezone.utc)


IST = timezone(timedelta(hours=5, minutes=30), "IST")


def fmt_ist(v) -> str:
    """Format a stored (UTC) datetime for display in Indian Standard Time."""
    if not isinstance(v, datetime):
        return "-" if not v else str(v)
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(IST).strftime("%d-%b-%Y %I:%M:%S %p IST")


def oid_str(v):
    return str(v) if isinstance(v, ObjectId) else v


PyObjectId = Annotated[Optional[str], BeforeValidator(oid_str)]


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    id: PyObjectId = Field(default=None, alias="_id")

    @classmethod
    def from_mongo(cls, doc):
        if not doc:
            return None
        d = dict(doc)
        if "_id" in d:
            d["_id"] = str(d["_id"])
        return cls(**d)

    def to_mongo(self) -> dict:
        d = self.model_dump(by_alias=True, exclude_none=True)
        if d.get("_id"):
            d["_id"] = ObjectId(d["_id"])
        return d


def clean(doc: dict) -> dict:
    """Serialize a raw mongo doc: _id -> id (str), drop _id."""
    out = dict(doc or {})
    if "_id" in out:
        out["id"] = str(out.pop("_id"))
    return out


# ---------------------------------------------------------------------------
# Current report of a case
# ---------------------------------------------------------------------------
# A draft and the submission made from it share a version number (submitting draft v1 creates submitted v1 and marks
# the draft "superseded"). Sorting by version alone therefore returned whichever of the two MongoDB happened to list
# first, often the stale draft. Superseded drafts are never the current report, and ties go to the newest document.
REPORT_ORDER = [("version", -1), ("created_at", -1), ("_id", -1)]


async def current_report(case_id: str, statuses: list | None = None):
    q = {"case_id": case_id, "status": {"$in": statuses} if statuses else {"$ne": "superseded"}}
    return await db.reports.find_one(q, sort=REPORT_ORDER)


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

class UserDoc(BaseDocument):
    role: str
    name: str
    agent_id: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    password_hash: str = ""
    must_change_password: bool = True
    disabled: bool = False
    scope: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now)
    password_changed_at: Optional[datetime] = None


class ClientDoc(BaseDocument):
    name: str
    code: Optional[str] = None
    active: bool = True
    created_at: datetime = Field(default_factory=now)


class BranchDoc(BaseDocument):
    client_id: str
    name: str
    city: Optional[str] = None
    state: Optional[str] = None
    active: bool = True
    created_at: datetime = Field(default_factory=now)


class CaseDoc(BaseDocument):
    internal_case_id: str                      # system-generated (CSV-######), mandatory and unique
    client_case_id: Optional[str] = None       # client / external reference, optional
    client_id: str
    client_name: str
    branch_id: Optional[str] = None
    branch_name: Optional[str] = None
    applicant_name: str
    co_applicant_name: Optional[str] = None
    loan_type: Optional[str] = None
    report_type: str
    assigned_address: str
    city: Optional[str] = None
    state: Optional[str] = None
    priority: str = "Medium"
    due_at: Optional[datetime] = None
    assigned_lat: Optional[float] = None
    assigned_lon: Optional[float] = None
    status: str = "new"
    assigned_agent_id: Optional[str] = None
    assigned_agent_name: Optional[str] = None
    created_by: Optional[str] = None
    flags: list = Field(default_factory=list)
    timeline: list = Field(default_factory=list)
    visit: Optional[dict] = None
    last_submitted_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    deleted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class ReportDoc(BaseDocument):
    case_id: str
    version: int = 1
    status: str = "draft"  # draft|submitted|under_review|approved|returned|inconclusive|exception
    report_type: str
    data: dict = Field(default_factory=dict)
    gps: dict = Field(default_factory=dict)
    declaration: bool = False
    flags: list = Field(default_factory=list)
    offline_synced: bool = False
    submitted_by: Optional[str] = None
    submitted_by_name: Optional[str] = None
    submitted_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    reviewed_by_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_comment: Optional[str] = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class EvidenceDoc(BaseDocument):
    case_id: str
    slot: str
    kind: str = "photo"
    storage_path: str
    filename: str
    sha256: str
    gps: dict = Field(default_factory=dict)
    captured_at: Optional[datetime] = None
    uploaded_by: Optional[str] = None
    device_id: Optional[str] = None
    mime: str = "image/jpeg"
    size: int = 0
    created_at: datetime = Field(default_factory=now)


class CallLogDoc(BaseDocument):
    case_id: str
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    phone_number: str
    result: str
    person_met: Optional[str] = None
    relationship: Optional[str] = None
    info_confirmed: Optional[str] = None
    notes: Optional[str] = None
    next_attempt_at: Optional[datetime] = None
    attempt_at: datetime = Field(default_factory=now)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

async def audit(user, action: str, entity: str, entity_id: str, details: dict | None = None, request=None):
    u = user or {}
    doc = {
        "user_id": str(u.get("_id") or u.get("id") or ""),
        "user_name": u.get("name") or "unknown",
        "user_role": u.get("role") or "system",
        "action": action,
        "entity": entity,
        "entity_id": str(entity_id or ""),
        "details": details or {},
        "ip": (request.client.host if request and request.client else None),
        "created_at": now(),
    }
    await db.audit_logs.insert_one(doc)


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------

SENSITIVE_KEY_RE = re.compile(r"aadhaar|aadhar|pan|account|passport|voter|driving|licen|ref_no|reference", re.I)


def mask_value(v) -> str:
    s = re.sub(r"\s+", "", str(v))
    if len(s) <= 4:
        return "XXXX"
    return "X" * (len(s) - 4) + s[-4:]


def mask_mapping(data: dict):
    if not isinstance(data, dict):
        return data
    out = {}
    for k, v in data.items():
        if isinstance(v, str) and SENSITIVE_KEY_RE.search(k):
            out[k] = mask_value(v)
        elif isinstance(v, dict):
            out[k] = mask_mapping(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Blocked / judgemental language
# ---------------------------------------------------------------------------

def find_blocked_words(text: str, blocked: list) -> list:
    found = []
    t = (text or "").lower()
    for w in blocked:
        if re.search(r"\b" + re.escape(w.lower()) + r"\b", t):
            found.append(w)
    return found


def scan_data_for_blocked(data: dict, blocked: list, skip_keys=()) -> dict:
    """skip_keys: fixed-choice (select) fields whose options are set by the business (e.g. VEE Remarks Positive/Negative).
    Free text typed by agents is always scanned."""
    hits = {}
    for k, v in (data or {}).items():
        if k in skip_keys:
            continue
        if isinstance(v, str):
            words = find_blocked_words(v, blocked)
            if words:
                hits[k] = words
    return hits


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    "company_name": COMPANY_NAME,
    "company_logo_url": "",
    "disclaimer": "This report records field observations and authorised verification results only. It does not assess creditworthiness, title, income adequacy, document authenticity, or loan eligibility.",
    "flag_distance_m": 500,
    "flag_accuracy_m": 150,
    "flag_travel_kmh": 500,
    "flag_same_place_min": 10,
    "flag_clock_skew_min": 5,          # device capture time ahead of server receipt by more than this -> flag
    "flag_capture_max_age_h": 72,      # photo uploaded more than this long after capture -> flag for review
    "telephone_min_attempts": 3,
    "retention_days": 3650,
    "blocked_words": [
        "positive", "negative", "genuine", "good reputation", "satisfactory",
        "signature confirmed", "owner", "fraud", "forged", "loan recommended",
        "creditworthy", "loan eligible",
    ],
    "custom_form_fields": [
        {"key": "details_checked", "label": "Details Checked", "type": "textarea", "required": True},
        {"key": "outcome", "label": "Outcome", "type": "select",
         "options": ["Confirmed", "Could Not Be Independently Verified", "Mismatch/Exception"], "required": True},
        {"key": "factual_remarks", "label": "Factual Remarks", "type": "textarea", "required": False},
        {"key": "exceptions", "label": "Exceptions / Mismatches", "type": "textarea", "required": False},
    ],
}

STATUS_LABELS = {
    "new": "New", "assigned": "Assigned", "in_progress": "In Progress", "submitted": "Submitted",
    "under_review": "Under Review", "returned": "Returned for Correction", "approved": "Approved",
    "inconclusive": "Inconclusive", "exception": "Mismatch/Exception", "exported": "Exported",
}

ACTIVE_STATUSES = ["new", "assigned", "in_progress", "returned"]

FLAG_LABELS = {
    "missing_gps": "Missing GPS",
    "low_gps_accuracy": "Low GPS accuracy",
    "far_from_assigned_address": "Far from assigned address",
    "duplicate_photo_cross_case": "Duplicate photo across cases",
    "same_evidence_reused": "Same evidence photo reused",
    "impossible_travel": "Impossible travel distance/time",
    "late_submission": "Late submission against SLA",
    "incomplete_evidence": "Incomplete evidence",
    "multiple_same_place_time": "Multiple reports from same place/time",
    "no_visit_started": "Visit not started at location",
    "photo_far_from_assigned": "Photo taken outside allowed distance (agent reason recorded)",
    "photo_without_gps": "Photo taken without GPS (agent reason recorded)",
    "possible_mock_location": "Possible mock/simulated location reported by device",
    "device_clock_suspect": "Device clock differs from server time",
    "no_reference_location": "Case has no reference location; distance not checked",
    "location_uncertain": "Distance uncertain: GPS accuracy / approximate case location (may be within range)",
    "stale_gps_fix": "GPS position older than the photo",
}


async def get_settings() -> dict:
    doc = await db.settings.find_one({"_id": "app"})
    merged = dict(DEFAULT_SETTINGS)
    if doc and isinstance(doc.get("value"), dict):
        merged.update(doc["value"])
    return merged


async def save_settings(update: dict) -> dict:
    current = await get_settings()
    current.update(update or {})
    await db.settings.update_one({"_id": "app"}, {"$set": {"value": current}}, upsert=True)
    return current


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (TypeError, ValueError):
        return -1.0
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- calendar dates (e.g. Date of Birth)
# Stored as plain "YYYY-MM-DD" strings: no time and no timezone, so they can never shift by a day.
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def parse_iso_date(v):
    """Return a datetime.date for a valid 'YYYY-MM-DD' string, else None."""
    import re
    from datetime import date
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(v or "").strip())
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def today_ist():
    from datetime import timedelta as _td
    return (datetime.now(timezone.utc) + _td(hours=5, minutes=30)).date()


def fmt_date(v) -> str:
    """'1988-08-05' -> '05-Aug-1988'. Historical free-text values are returned exactly as stored."""
    d = parse_iso_date(v)
    if not d:
        return "" if v is None else str(v).strip()
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


# ---------------------------------------------------------------- distance check (photo GPS vs case reference)
# How far the case reference point itself may be from the real address, by how it was obtained.
# A manually pinned point is exact; a geocoded point is only as good as the geocoder's match.
REFERENCE_UNCERTAINTY_M = {"exact": 0.0, "street": 75.0, "locality": 1500.0, "pincode": 3000.0}


def assess_location(ref_lat, ref_lon, ref_precision, lat, lon, accuracy, allowed_m: float,
                    max_accuracy_m: float = 150.0) -> dict:
    """Decide whether a GPS fix is within the allowed distance of the case reference location.

    Uses the geodesic (haversine) distance between the reference and the captured fix, then widens it by the two
    known uncertainties: the fix's reported accuracy radius and the reference point's own precision.
      within        the measured position is within the allowed distance
      uncertain     measured outside, but accuracy + reference precision mean the agent may be within range
      outside       outside even after allowing for both uncertainties  -> reason + supervisor review
      no_reference  the case has no usable reference point -> distance cannot be checked (nothing is invented)
    The accuracy allowance is capped at max_accuracy_m (the 'poor accuracy' setting): a very poor fix (e.g. +/-5 km)
    must not turn a genuinely distant photo into 'uncertain'. Such fixes are flagged low_gps_accuracy anyway.
    """
    has_ref = ref_lat is not None and ref_lon is not None
    precision = (ref_precision or "exact") if has_ref else None
    if precision is None or precision not in REFERENCE_UNCERTAINTY_M:
        why = ("The case has no reference location, so the distance cannot be checked." if precision is None else
               "The case location is only known roughly (region level), so the distance cannot be checked.")
        return {"status": "no_reference", "distance_m": None, "margin_m": None, "allowed_m": allowed_m,
                "reference_precision": precision, "explanation": why}
    d = haversine_m(ref_lat, ref_lon, lat, lon)
    acc = min(float(accuracy), float(max_accuracy_m)) if accuracy is not None else 0.0
    ref_u = REFERENCE_UNCERTAINTY_M[precision]
    margin = acc + ref_u
    out = {"distance_m": round(d, 1), "margin_m": round(margin, 1), "allowed_m": allowed_m,
           "reference_precision": precision, "reference_uncertainty_m": ref_u, "accuracy_m": accuracy}
    if d <= allowed_m:
        return {**out, "status": "within", "explanation": f"Within {allowed_m:.0f} m of the case location."}
    if d - margin <= allowed_m:
        parts = []
        if ref_u:
            parts.append(f"the case location is approximate ({precision} level, up to about {ref_u:.0f} m off)")
        if acc:
            parts.append(f"the phone GPS accuracy is +/-{acc:.0f} m")
        return {**out, "status": "uncertain",
                "explanation": f"Measured {d:.0f} m from the case location, but {' and '.join(parts)}, so the agent may be "
                               f"within the allowed {allowed_m:.0f} m. Flagged for supervisor review; no reason needed."}
    return {**out, "status": "outside",
            "explanation": f"About {d:.0f} m from the case location (allowed {allowed_m:.0f} m), outside even after "
                           f"allowing {margin:.0f} m for GPS accuracy and case-location precision."}


# A case is "live" (shown in lists, dashboards, search, exports and alerts) unless it was soft-deleted by the
# Super Admin, or it is still an unsubmitted agent "Create New Verification" draft (is_draft) that has not become a case.
LIVE_CASE_FILTER = {"deleted_at": None, "is_draft": {"$ne": True}}


async def next_internal_case_id() -> str:
    """The mandatory, unique, system-generated Internal Case ID (never derived from a client/external ID)."""
    return f"CSV-{await next_seq('case_seq'):06d}"


async def next_seq(name: str) -> int:
    doc = await db.counters.find_one_and_update({"_id": name}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
    return int((doc or {}).get("seq", 1))
