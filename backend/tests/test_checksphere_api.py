# CheckSphere backend regression tests: auth, role isolation, users, master data, cases, reports, evidence, review, exports
import io
import os
import uuid
import pytest
import requests

def _base():
    url = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
    if not url:
        for line in open("/app/frontend/.env"):
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
    return url.rstrip("/")

BASE = _base() + "/api"
ADMIN = ("admin@checksphere.app", "Admin@12345")
SUFFIX = uuid.uuid4().hex[:6].upper()
PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64 + uuid.uuid4().bytes)


def login(ident, pw):
    return requests.post(f"{BASE}/auth/login", json={"identifier": ident, "password": pw}, timeout=30)


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin():
    r = login(*ADMIN)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def master(admin):
    clients = requests.get(f"{BASE}/clients", headers=H(admin)).json()["items"]
    branches = requests.get(f"{BASE}/branches", headers=H(admin)).json()["items"]
    return clients[0], [b for b in branches if b["client_id"] == clients[0]["id"]][0]


def make_user(admin, role, tag):
    pw = "Temp@12345"
    body = {"name": f"TEST_{tag}_{SUFFIX}", "role": role, "password": pw,
            "email": f"test_{tag.lower()}_{SUFFIX.lower()}@example.com"}
    if role in ("agent", "supervisor"):
        body["agent_id"] = f"TST{tag}{SUFFIX}"
    r = requests.post(f"{BASE}/users", json=body, headers=H(admin))
    assert r.status_code in (200, 201), r.text
    u = r.json().get("user", r.json())
    return u, body


def activate(ident, pw):
    r = login(ident, pw)
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is True
    tok = r.json()["access_token"]
    g = requests.get(f"{BASE}/cases", headers=H(tok))
    assert g.status_code == 403 and "password_change_required" in g.text
    c = requests.post(f"{BASE}/auth/change-password", headers=H(tok),
                      json={"current_password": pw, "new_password": "NewPass@12345"})
    assert c.status_code == 200, c.text
    r2 = login(ident, "NewPass@12345")
    assert r2.status_code == 200 and r2.json()["must_change_password"] is False
    return r2.json()["access_token"]


@pytest.fixture(scope="module")
def agents(admin):
    a1, b1 = make_user(admin, "agent", "A")
    a2, b2 = make_user(admin, "agent", "B")
    t1 = activate(b1["agent_id"], b1["password"])  # login by agent id
    t2 = activate(b2["email"], b2["password"])     # login by email
    yield {"a1": a1, "t1": t1, "a2": a2, "t2": t2}
    for a in (a1, a2):
        requests.post(f"{BASE}/users/{a['id']}/set-active", json={"active": False}, headers=H(admin))


def new_case(admin, master, report_type, agent_id=None, **kw):
    client, branch = master
    body = {"client_case_id": f"TEST_{report_type}_{uuid.uuid4().hex[:6]}", "client_id": client["id"],
            "branch_id": branch["id"], "applicant_name": "TEST_Applicant", "report_type": report_type,
            "assigned_address": "TEST 1 Road, Mumbai", "city": "Mumbai", "state": "Maharashtra",
            "assigned_lat": 19.07, "assigned_lon": 72.87, **kw}
    r = requests.post(f"{BASE}/cases", json=body, headers=H(admin))
    assert r.status_code in (200, 201), r.text
    c = r.json().get("case", r.json())
    if agent_id:
        a = requests.post(f"{BASE}/cases/{c['id']}/assign", json={"agent_id": agent_id}, headers=H(admin))
        assert a.status_code == 200, a.text
    return c


def fill(config, word="Observed"):
    data = {}
    for s in config["sections"]:
        for f in s["fields"]:
            if f.get("required"):
                data[f["key"]] = (f.get("options") or [None])[0] or ("3" if f["type"] == "number" else f"{word} value")
    return data


# --- Auth ---
class TestAuth:
    def test_admin_me(self, admin):
        r = requests.get(f"{BASE}/auth/me", headers=H(admin))
        assert r.status_code == 200 and r.json()["user"]["role"] == "super_admin"

    def test_bad_password(self):
        assert login("admin@checksphere.app", "wrong").status_code == 401

    def test_supervisor_gate(self):
        r = login("SPV01", "Super@12345")
        if r.status_code != 200:
            pytest.skip("supervisor creds changed")
        tok = r.json()["access_token"]
        if r.json()["must_change_password"]:
            assert requests.get(f"{BASE}/cases", headers=H(tok)).status_code == 403
            assert requests.get(f"{BASE}/auth/me", headers=H(tok)).status_code == 200


# --- Role isolation ---
class TestIsolation:
    def test_agent_isolation(self, admin, agents, master):
        c = new_case(admin, master, "residence_applicant", agents["a1"]["id"])
        l1 = requests.get(f"{BASE}/cases", headers=H(agents["t1"])).json()["items"]
        assert c["id"] in [x["id"] for x in l1]
        assert all(x.get("assigned_agent_id") == agents["a1"]["id"] for x in l1)
        assert requests.get(f"{BASE}/cases/{c['id']}", headers=H(agents["t2"])).status_code == 403
        assert requests.get(f"{BASE}/users", headers=H(agents["t1"])).status_code == 403
        assert requests.get(f"{BASE}/reports/case/{c['id']}", headers=H(agents["t2"])).status_code == 403

    def test_supervisor_cannot_create_user(self, admin):
        s, b = make_user(admin, "supervisor", "S")
        tok = activate(b["email"], b["password"])
        r = requests.post(f"{BASE}/users", headers=H(tok), json={"name": "TEST_x", "role": "agent", "password": "Abcdefgh1"})
        assert r.status_code == 403
        requests.post(f"{BASE}/users/{s['id']}/set-active", json={"active": False}, headers=H(admin))


# --- Users & sessions ---
class TestUsers:
    def test_reset_revokes_and_set_active(self, admin):
        u, b = make_user(admin, "agent", "R")
        tok = activate(b["agent_id"], b["password"])
        ss = requests.get(f"{BASE}/users/{u['id']}/sessions", headers=H(admin))
        assert ss.status_code == 200 and len(ss.json()["items"]) >= 1
        r = requests.post(f"{BASE}/users/{u['id']}/reset-password", json={"password": "Reset@12345"}, headers=H(admin))
        assert r.status_code == 200
        assert requests.get(f"{BASE}/auth/me", headers=H(tok)).status_code == 401
        lr = login(b["agent_id"], "Reset@12345")
        assert lr.status_code == 200 and lr.json()["must_change_password"] is True
        # explicit session revoke
        tok2 = lr.json()["access_token"]
        sid = lr.json()["session_id"]
        rv = requests.post(f"{BASE}/auth/sessions/{sid}/revoke", headers=H(admin))
        assert rv.status_code == 200
        assert requests.get(f"{BASE}/auth/me", headers=H(tok2)).status_code == 401
        # deactivate
        d = requests.post(f"{BASE}/users/{u['id']}/set-active", json={"active": False}, headers=H(admin))
        assert d.status_code == 200
        assert login(b["agent_id"], "Reset@12345").status_code in (401, 403)


# --- Master data ---
class TestMaster:
    def test_client_branch_regions_settings(self, admin):
        c = requests.post(f"{BASE}/clients", json={"name": f"TEST_Client_{SUFFIX}"}, headers=H(admin))
        assert c.status_code in (200, 201), c.text
        cid = c.json().get("id") or c.json().get("client", {}).get("id")
        b = requests.post(f"{BASE}/branches", json={"client_id": cid, "name": "TEST_Br", "city": "TESTCity", "state": "TESTState"}, headers=H(admin))
        assert b.status_code in (200, 201), b.text
        assert any(x["name"] == f"TEST_Client_{SUFFIX}" for x in requests.get(f"{BASE}/clients", headers=H(admin)).json()["items"])
        assert requests.get(f"{BASE}/regions", headers=H(admin)).status_code == 200
        s = requests.get(f"{BASE}/settings", headers=H(admin))
        assert s.status_code == 200
        p = requests.put(f"{BASE}/settings", json={"updates": {"telephone_min_attempts": s.json()["telephone_min_attempts"]}}, headers=H(admin))
        assert p.status_code == 200, p.text
        rt = requests.get(f"{BASE}/report-types", headers=H(admin))
        assert rt.status_code == 200 and len(rt.json()["items"]) >= 8


# --- Cases ---
class TestCases:
    def test_filters(self, admin):
        for q in ["status=submitted", "q=TEST", "due=overdue", "due=today"]:
            r = requests.get(f"{BASE}/cases?{q}", headers=H(admin))
            assert r.status_code == 200, q
        sub = requests.get(f"{BASE}/cases?status=submitted", headers=H(admin)).json()["items"]
        assert all(x["status"] == "submitted" for x in sub)

    def test_import(self, admin, master):
        t = requests.get(f"{BASE}/cases/import-template", headers=H(admin))
        assert t.status_code == 200 and len(t.content) > 100
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(t.content))
        ws = wb.active
        headers = [c.value for c in ws[1]]
        print("import headers", headers)
        client, branch = master
        sample = {c.value: c.value for c in ws[2]} if ws.max_row >= 2 else {}
        print("template row2", [c.value for c in ws[2]] if ws.max_row >= 2 else None)
        out = io.BytesIO(); wb.save(out)
        imp = requests.post(f"{BASE}/cases/import", headers=H(admin), files={"file": ("t.xlsx", out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        print("import", imp.status_code, imp.text[:300])
        assert imp.status_code == 200
        bad = requests.post(f"{BASE}/cases/import", headers=H(admin), files={"file": ("x.txt", b"hello", "text/plain")})
        assert bad.status_code in (400, 422), f"non-xlsx import returned {bad.status_code}"


# --- Reports / evidence / review / exports ---
class TestReportFlow:
    def test_full_flow(self, admin, agents, master):
        c = new_case(admin, master, "residence_applicant", agents["a1"]["id"])
        t1 = agents["t1"]
        ctx = requests.get(f"{BASE}/reports/case/{c['id']}", headers=H(t1)).json()
        cfg = ctx["config"]
        # draft
        d = requests.put(f"{BASE}/reports/case/{c['id']}/draft", json={"data": {"person_met": "x"}}, headers=H(t1))
        assert d.status_code == 200 and d.json()["status"] == "draft"
        # incomplete submit
        s = requests.post(f"{BASE}/reports/case/{c['id']}/submit", json={"data": {}}, headers=H(t1))
        assert s.status_code == 422
        det = s.json()["detail"]
        assert det["missing_fields"] and det["problems"]
        # blocked word
        data = fill(cfg)
        data["agent_remarks"] = "Applicant seems genuine"
        s2 = requests.post(f"{BASE}/reports/case/{c['id']}/submit", json={"data": data, "gps": {"lat": 19.07, "lon": 72.87, "accuracy": 10}, "declaration": True}, headers=H(t1))
        assert s2.status_code == 422 and s2.json()["detail"]["blocked_words"]
        data.pop("agent_remarks")
        # evidence
        for slot in [p["key"] for p in cfg.get("photo_slots", []) if p.get("required")]:
            up = requests.post(f"{BASE}/evidence/upload", headers=H(t1),
                               files={"file": (f"{slot}.png", PNG + slot.encode(), "image/png")},
                               data={"case_id": c["id"], "slot": slot, "lat": "19.07", "lon": "72.87", "accuracy": "10"})
            assert up.status_code in (200, 201), up.text
        ev = up.json()
        assert requests.get(f"{BASE}/files/{ev['id']}").status_code == 401
        assert requests.get(f"{BASE}/files/{ev['id']}?token={t1}").status_code == 200
        assert requests.get(f"{BASE}/files/{ev['id']}?token={agents['t2']}").status_code == 403
        ok = requests.post(f"{BASE}/reports/case/{c['id']}/submit", json={"data": data, "gps": {"lat": 19.07, "lon": 72.87, "accuracy": 10}, "declaration": True}, headers=H(t1))
        assert ok.status_code == 200, ok.text
        rid = ok.json()["id"]
        assert ok.json()["status"] == "submitted"
        dup = requests.post(f"{BASE}/reports/case/{c['id']}/submit", json={"data": data, "gps": {"lat": 19.07, "lon": 72.87, "accuracy": 10}, "declaration": True}, headers=H(t1))
        assert dup.status_code == 400
        # review payload
        rv = requests.get(f"{BASE}/reports/{rid}", headers=H(admin))
        assert rv.status_code == 200
        assert requests.get(f"{BASE}/cases/{c['id']}", headers=H(admin)).json()["status"] == "under_review"
        assert requests.get(f"{BASE}/reports/{rid}?reveal=1", headers=H(admin)).status_code == 200
        assert requests.get(f"{BASE}/reports/{rid}", headers=H(t1)).status_code == 403
        # return without comment
        assert requests.post(f"{BASE}/reports/{rid}/review", json={"action": "return"}, headers=H(admin)).status_code in (400, 422)
        r1 = requests.post(f"{BASE}/reports/{rid}/review", json={"action": "return", "comment": "TEST fix address"}, headers=H(admin))
        assert r1.status_code == 200, r1.text
        assert requests.get(f"{BASE}/cases/{c['id']}", headers=H(admin)).json()["status"] == "returned"
        ok2 = requests.post(f"{BASE}/reports/case/{c['id']}/submit", json={"data": data, "gps": {"lat": 19.07, "lon": 72.87, "accuracy": 10}, "declaration": True}, headers=H(t1))
        assert ok2.status_code == 200 and ok2.json()["version"] > ok.json()["version"]
        ap = requests.post(f"{BASE}/reports/{ok2.json()['id']}/review", json={"action": "approve", "comment": "ok"}, headers=H(admin))
        assert ap.status_code == 200, ap.text
        assert requests.get(f"{BASE}/cases/{c['id']}", headers=H(admin)).json()["status"] == "approved"
        vs = requests.get(f"{BASE}/reports/case/{c['id']}/versions", headers=H(admin)).json()["items"]
        print("versions", [(v["version"], v["status"]) for v in vs])
        for fmt in ("pdf", "docx"):
            e = requests.get(f"{BASE}/exports/case/{c['id']}/{fmt}", headers=H(admin))
            assert e.status_code == 200 and len(e.content) > 500, fmt
        assert requests.get(f"{BASE}/exports/case/{c['id']}/pdf", headers=H(agents["t2"])).status_code == 403

    def test_other_review_actions(self, admin, agents, master):
        # inconclusive / exception / escalate on a telephone case (min call attempts)
        c = new_case(admin, master, "tel_residence", agents["a1"]["id"])
        t1 = agents["t1"]
        cfg = requests.get(f"{BASE}/reports/case/{c['id']}", headers=H(t1)).json()["config"]
        data = fill(cfg)
        s = requests.post(f"{BASE}/reports/case/{c['id']}/submit", json={"data": data, "declaration": True}, headers=H(t1))
        assert s.status_code == 422 and any("call attempts" in p for p in s.json()["detail"]["problems"])
        for i in range(3):
            cl = requests.post(f"{BASE}/cases/{c['id']}/call-logs", headers=H(t1),
                               json={"phone_number": "9876543210", "result": "No Response" if i < 2 else "Confirmed"})
            assert cl.status_code in (200, 201), cl.text
        assert len(requests.get(f"{BASE}/cases/{c['id']}/call-logs", headers=H(t1)).json()["items"]) == 3
        s = requests.post(f"{BASE}/reports/case/{c['id']}/submit", json={"data": data, "declaration": True}, headers=H(t1))
        assert s.status_code == 200, s.text
        rid = s.json()["id"]
        codes = {}
        for act in ("escalate", "exception", "inconclusive"):
            codes[act] = requests.post(f"{BASE}/reports/{rid}/review", json={"action": act, "comment": f"TEST {act}"}, headers=H(admin)).status_code
        # exception is terminal -> a further inconclusive must be rejected
        assert codes == {"escalate": 200, "exception": 200, "inconclusive": 400}, codes
        assert requests.get(f"{BASE}/cases/{c['id']}", headers=H(admin)).json()["status"] == "exception"

    def test_duplicate_photo_flag_survives_submit(self, admin, agents, master):
        t1 = agents["t1"]
        shared = PNG + b"DUPLICATE" + SUFFIX.encode()
        ids = []
        for _ in range(2):
            c = new_case(admin, master, "residence_applicant", agents["a1"]["id"])
            ids.append(c["id"])
            up = requests.post(f"{BASE}/evidence/upload", headers=H(t1), files={"file": ("d.png", shared, "image/png")},
                               data={"case_id": c["id"], "slot": "exterior", "lat": "19.07", "lon": "72.87", "accuracy": "10"})
            assert up.status_code in (200, 201), up.text
        flags = requests.get(f"{BASE}/cases/{ids[1]}", headers=H(admin)).json().get("flags") or []
        assert "duplicate_photo_cross_case" in flags
        cfg = requests.get(f"{BASE}/reports/case/{ids[1]}", headers=H(t1)).json()["config"]
        for p in cfg.get("photo_slots", []):
            if p.get("required") and p["key"] != "exterior":
                requests.post(f"{BASE}/evidence/upload", headers=H(t1), files={"file": ("x.png", PNG + p["key"].encode() + SUFFIX.encode() + b"z", "image/png")},
                              data={"case_id": ids[1], "slot": p["key"], "lat": "19.07", "lon": "72.87", "accuracy": "10"})
        s = requests.post(f"{BASE}/reports/case/{ids[1]}/submit", json={"data": fill(cfg), "gps": {"lat": 19.07, "lon": 72.87, "accuracy": 10}, "declaration": True}, headers=H(t1))
        assert s.status_code == 200, s.text
        after = requests.get(f"{BASE}/cases/{ids[1]}", headers=H(admin)).json().get("flags") or []
        assert "duplicate_photo_cross_case" in after, f"flag lost after submit: {after}"


class TestExportsDashboard:
    def test_exports_and_stats(self, admin):
        assert requests.get(f"{BASE}/exports/cases.xlsx", headers=H(admin)).status_code == 200
        for p in ("daily", "weekly", "monthly"):
            r = requests.get(f"{BASE}/exports/mis.xlsx?period={p}", headers=H(admin))
            assert r.status_code == 200 and r.content[:2] == b"PK", p
        st = requests.get(f"{BASE}/dashboard/stats", headers=H(admin))
        assert st.status_code == 200
        assert requests.get(f"{BASE}/dashboard/map", headers=H(admin)).status_code == 200
        au = requests.get(f"{BASE}/audit", headers=H(admin))
        assert au.status_code == 200 and len(au.json()["items"]) > 0


# --- Iteration 2 retests: report flags, review on returned, draft->v1 ---
class TestIteration2Retests:
    def _submit_ready(self, admin, agents, master, draft_first=False):
        t1 = agents["t1"]
        c = new_case(admin, master, "residence_applicant", agents["a1"]["id"])
        cfg = requests.get(f"{BASE}/reports/case/{c['id']}", headers=H(t1)).json()["config"]
        if draft_first:
            d = requests.put(f"{BASE}/reports/case/{c['id']}/draft", json={"data": {"person_met": "TEST"}}, headers=H(t1))
            assert d.status_code == 200 and d.json()["version"] == 1, d.text
        for p in cfg.get("photo_slots", []):
            if p.get("required"):
                requests.post(f"{BASE}/evidence/upload", headers=H(t1), files={"file": ("x.png", PNG + p["key"].encode() + uuid.uuid4().bytes, "image/png")},
                              data={"case_id": c["id"], "slot": p["key"], "lat": "19.07", "lon": "72.87", "accuracy": "10"})
        s = requests.post(f"{BASE}/reports/case/{c['id']}/submit", json={"data": fill(cfg), "gps": {"lat": 19.07, "lon": 72.87, "accuracy": 10}, "declaration": True}, headers=H(t1))
        assert s.status_code == 200, s.text
        return c, s.json()

    def test_draft_then_first_submit_is_v1(self, admin, agents, master):
        c, s = self._submit_ready(admin, agents, master, draft_first=True)
        assert s["version"] == 1, s["version"]
        vs = requests.get(f"{BASE}/reports/case/{c['id']}/versions", headers=H(admin)).json()["items"]
        print("versions", [(v["version"], v["status"]) for v in vs])
        assert [v for v in vs if v["status"] == "submitted"][0]["version"] == 1
        assert not any(v["status"] == "draft" for v in vs)

    def test_review_on_returned_is_400(self, admin, agents, master):
        c, s = self._submit_ready(admin, agents, master)
        rid = s["id"]
        r = requests.post(f"{BASE}/reports/{rid}/review", json={"action": "return", "comment": "TEST fix"}, headers=H(admin))
        assert r.status_code == 200, r.text
        for act in ("approve", "return", "escalate"):
            again = requests.post(f"{BASE}/reports/{rid}/review", json={"action": act, "comment": "TEST again"}, headers=H(admin))
            assert again.status_code == 400, f"{act} on returned -> {again.status_code}"
        assert requests.get(f"{BASE}/cases/{c['id']}", headers=H(admin)).json()["status"] == "returned"

    def test_duplicate_flag_on_report(self, admin, agents, master):
        t1 = agents["t1"]
        shared = PNG + b"DUP2" + uuid.uuid4().bytes
        ids = []
        for _ in range(2):
            c = new_case(admin, master, "residence_applicant", agents["a1"]["id"])
            ids.append(c["id"])
            requests.post(f"{BASE}/evidence/upload", headers=H(t1), files={"file": ("d.png", shared, "image/png")},
                          data={"case_id": c["id"], "slot": "exterior", "lat": "19.07", "lon": "72.87", "accuracy": "10"})
        cfg = requests.get(f"{BASE}/reports/case/{ids[1]}", headers=H(t1)).json()["config"]
        for p in cfg.get("photo_slots", []):
            if p.get("required") and p["key"] != "exterior":
                requests.post(f"{BASE}/evidence/upload", headers=H(t1), files={"file": ("x.png", PNG + uuid.uuid4().bytes, "image/png")},
                              data={"case_id": ids[1], "slot": p["key"], "lat": "19.07", "lon": "72.87", "accuracy": "10"})
        s = requests.post(f"{BASE}/reports/case/{ids[1]}/submit", json={"data": fill(cfg), "gps": {"lat": 19.07, "lon": 72.87, "accuracy": 10}, "declaration": True}, headers=H(t1))
        assert s.status_code == 200, s.text
        print("submit flags", s.json().get("flags"))
        rep = requests.get(f"{BASE}/reports/{s.json()['id']}", headers=H(admin)).json()
        rflags = (rep.get("report") or rep).get("flags") or []
        print("report flags", rflags)
        assert "duplicate_photo_cross_case" in rflags
        assert "duplicate_photo_cross_case" in (requests.get(f"{BASE}/cases/{ids[1]}", headers=H(admin)).json().get("flags") or [])

    def test_dashboard_agent_productivity(self, admin):
        st = requests.get(f"{BASE}/dashboard/stats", headers=H(admin)).json()
        print("stats keys", list(st.keys()))
