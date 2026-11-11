"""CheckSphere core: DB connection, base document models, masking, audit, settings."""
import os
import re
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Annotated

from bson import ObjectId
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field, BeforeValidator

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url, tz_aware=True)
db = client[os.environ["DB_NAME"]]

COMPANY_NAME = os.environ.get("COMPANY_NAME", "CheckSphere")


def now() -> datetime:
    return datetime.now(timezone.utc)


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
    internal_case_id: str
    client_case_id: str
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


def scan_data_for_blocked(data: dict, blocked: list) -> dict:
    hits = {}
    for k, v in (data or {}).items():
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


async def next_seq(name: str) -> int:
    doc = await db.counters.find_one_and_update({"_id": name}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
    return int((doc or {}).get("seq", 1))
