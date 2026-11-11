# Iteration 3: role-portal login, case list filters/sort, case audit, sessions, activation, incidents, backups, retention preview, scope, required_overrides
import os
import uuid
from datetime import datetime, timezone
import pytest
import requests


def _base():
    url = os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for line in open("/app/frontend/.env"):
            if line.startswith("EXPO_BACKEND_URL=") or line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
                break
    return url.rstrip("/")


BASE = _base() + "/api"
SFX = uuid.uuid4().hex[:6].upper()
CREATED_USERS = []


def login(ident, pw, role=None):
    body = {"identifier": ident, "password": pw}
    if role:
        body["expected_role"] = role
    return requests.post(f"{BASE}/auth/login", json=body, timeout=30)


def H(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin():
    r = login("admin@checksphere.app", "Admin@12345")
    assert r.status_code == 200
    tok = r.json()["access_token"]
    yield tok
    # cleanup: deactivate TEST users created by this module
    for uid in CREATED_USERS:
        requests.post(f"{BASE}/users/{uid}/set-active", json={"active": False}, headers=H(tok))


def mkuser(admin, role, scope=None):
    body = {"name": f"TEST_{role}_{SFX}_{len(CREATED_USERS)}", "role": role,
            "email": f"test_{role}_{SFX}_{len(CREATED_USERS)}@example.com".lower(), "password": "TempPass@123"}
    if scope is not None:
        body["scope"] = scope
    r = requests.post(f"{BASE}/users", json=body, headers=H(admin))
    assert r.status_code == 200, r.text
    u = r.json()
    CREATED_USERS.append(u["id"])
    return u, body


def sup_token(body):
    t = login(body["email"], "TempPass@123").json()["access_token"]
    r = requests.post(f"{BASE}/auth/change-password", json={"current_password": "TempPass@123", "new_password": "TempPass@456"}, headers=H(t))
    assert r.status_code == 200, r.text
    return t


def all_cases(tok, **params):
    params.setdefault("limit", 100)
    r = requests.get(f"{BASE}/cases", params=params, headers=H(tok))
    assert r.status_code == 200, r.text
    return r.json()


# --- auth expected_role
class TestPortalLogin:
    def test_wrong_portal_403(self):
        r = login("admin@checksphere.app", "Admin@12345", "supervisor")
        assert r.status_code == 403
        assert "Super Admin account" in r.json()["detail"]

    def test_right_portal_ok(self):
        r = login("admin@checksphere.app", "Admin@12345", "super_admin")
        assert r.status_code == 200 and r.json()["user"]["role"] == "super_admin"


# --- case list filters
class TestCaseFilters:
    def test_sort_applicant_asc_desc(self, admin):
        a = [c["applicant_name"] for c in all_cases(admin, sort="applicant_name", order="asc")["items"]]
        d = [c["applicant_name"] for c in all_cases(admin, sort="applicant_name", order="desc")["items"]]
        assert a == sorted(a) and d == sorted(d, reverse=True) and len(a) > 1

    def test_pending_review(self, admin):
        items = all_cases(admin, status="pending_review")["items"]
        assert items and all(c["status"] in ("submitted", "under_review") for c in items)

    def test_sla_overdue(self, admin):
        items = all_cases(admin, sla="overdue")["items"]
        now = datetime.now(timezone.utc)
        for c in items:
            assert c["due_at"] and datetime.fromisoformat(c["due_at"].replace("Z", "+00:00")).replace(tzinfo=timezone.utc) < now

    def test_flagged(self, admin):
        items = all_cases(admin, flagged=1)["items"]
        assert items and all(len(c.get("flags") or []) > 0 for c in items)

    def test_pagination(self, admin):
        p1 = all_cases(admin, limit=5, page=1)
        p2 = all_cases(admin, limit=5, page=2)
        assert len(p1["items"]) == 5 and p1["total"] >= 6
        assert not ({c["id"] for c in p1["items"]} & {c["id"] for c in p2["items"]})

    def test_case_audit(self, admin):
        cid = all_cases(admin, limit=1)["items"][0]["id"]
        r = requests.get(f"{BASE}/cases/{cid}/audit", headers=H(admin))
        assert r.status_code == 200 and isinstance(r.json()["items"], list)


# --- sessions / activation / activity
class TestUserOps:
    def test_sessions_list(self, admin):
        r = requests.get(f"{BASE}/sessions", headers=H(admin))
        assert r.status_code == 200
        items = r.json()["items"]
        assert items and "user_name" in items[0] and "_id" not in items[0]

    def test_activation_and_revoke_all(self, admin):
        u, body = mkuser(admin, "agent")
        r = requests.post(f"{BASE}/users/{u['id']}/activation-link", headers=H(admin))
        assert r.status_code == 200 and r.json()["path"].startswith("/activate?token=")
        tok = r.json()["token"]
        assert requests.post(f"{BASE}/auth/activate", json={"token": tok, "new_password": "NewPass@123"}).status_code == 200
        # token single use
        assert requests.post(f"{BASE}/auth/activate", json={"token": tok, "new_password": "NewPass@123"}).status_code == 400
        lr = login(body["email"], "NewPass@123")
        assert lr.status_code == 200 and lr.json()["must_change_password"] is False
        utok = lr.json()["access_token"]
        rv = requests.post(f"{BASE}/users/{u['id']}/revoke-all", headers=H(admin))
        assert rv.status_code == 200 and rv.json()["revoked"] >= 1
        assert requests.get(f"{BASE}/auth/me", headers=H(utok)).status_code == 401
        act = requests.get(f"{BASE}/users/{u['id']}/activity", headers=H(admin))
        assert act.status_code == 200 and any(a["action"] == "login" for a in act.json()["items"])

    def test_invalid_user_id_not_500(self, admin):
        r = requests.post(f"{BASE}/users/not-an-id/activation-link", headers=H(admin))
        assert r.status_code in (400, 404, 422), f"got {r.status_code}"


# --- incidents / backups / retention
class TestOps:
    def test_incident_crud(self, admin):
        r = requests.post(f"{BASE}/incidents", json={"title": f"TEST_inc_{SFX}", "severity": "Low"}, headers=H(admin))
        assert r.status_code == 200
        iid = r.json()["id"]
        assert any(i["id"] == iid for i in requests.get(f"{BASE}/incidents", headers=H(admin)).json()["items"])
        assert requests.post(f"{BASE}/incidents/{iid}/close", headers=H(admin)).status_code == 200
        got = [i for i in requests.get(f"{BASE}/incidents", headers=H(admin)).json()["items"] if i["id"] == iid][0]
        assert got["status"] == "Closed"

    def test_incident_bad_severity(self, admin):
        r = requests.post(f"{BASE}/incidents", json={"title": "TEST_x", "severity": "Huge"}, headers=H(admin))
        assert r.status_code == 422

    def test_backup_run(self, admin):
        r = requests.post(f"{BASE}/backups/run", headers=H(admin), timeout=60)
        assert r.status_code == 200 and r.json()["size"] > 0 and r.json()["counts"]["cases"] > 0
        assert requests.get(f"{BASE}/backups", headers=H(admin)).json()["items"]

    def test_retention_preview(self, admin):
        r = requests.get(f"{BASE}/retention/preview", headers=H(admin))
        assert r.status_code == 200 and isinstance(r.json()["eligible_cases"], int)


# --- supervisor scope
class TestScope:
    def test_agent_scope_restricts(self, admin):
        agents = requests.get(f"{BASE}/users", params={"role": "agent", "q": "AGT101"}, headers=H(admin)).json()["items"]
        a1 = agents[0]["id"]
        u, body = mkuser(admin, "supervisor", {"agent_ids": [a1]})
        tok = sup_token(body)
        items = all_cases(tok)["items"]
        assert items and all(c.get("assigned_agent_id") == a1 for c in items)
        # admin supervisor_id filter
        items2 = all_cases(admin, supervisor_id=u["id"])["items"]
        assert {c["id"] for c in items2} == {c["id"] for c in items}

    def test_multi_scope_search_no_bypass(self, admin):
        agents = requests.get(f"{BASE}/users", params={"role": "agent", "q": "AGT101"}, headers=H(admin)).json()["items"]
        a1 = agents[0]["id"]
        clients = requests.get(f"{BASE}/clients", headers=H(admin)).json()["items"]
        u, body = mkuser(admin, "supervisor", {"agent_ids": [a1], "client_ids": [clients[0]["id"]]})
        tok = sup_token(body)
        allowed = {c["id"] for c in all_cases(tok)["items"]}
        searched = all_cases(tok, q="a")["items"]
        leaked = [c["internal_case_id"] for c in searched if c["id"] not in allowed]
        assert not leaked, f"scope bypass via q search; out-of-scope cases returned: {leaked}"


# --- required overrides
class TestRequiredOverrides:
    def test_override_applies(self, admin):
        s = requests.get(f"{BASE}/settings", headers=H(admin)).json()
        orig = s.get("required_overrides") or {}
        cfg = requests.get(f"{BASE}/report-types", headers=H(admin)).json()["configs"]["residence_applicant"]
        f = cfg["sections"][0]["fields"][0]
        new = {**orig, "residence_applicant": {**(orig.get("residence_applicant") or {}), f["key"]: not f.get("required")}}
        try:
            assert requests.put(f"{BASE}/settings", json={"updates": {"required_overrides": new}}, headers=H(admin)).status_code == 200
            cfg2 = requests.get(f"{BASE}/report-types", headers=H(admin)).json()["configs"]["residence_applicant"]
            f2 = [x for x in cfg2["sections"][0]["fields"] if x["key"] == f["key"]][0]
            assert f2["required"] == (not f.get("required"))
        finally:
            requests.put(f"{BASE}/settings", json={"updates": {"required_overrides": orig}}, headers=H(admin))
