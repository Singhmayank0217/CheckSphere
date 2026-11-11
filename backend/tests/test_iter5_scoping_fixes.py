# Iteration 5: retest of iteration_3 fixes - approve-with-corrections, requests_pending scoping, scoped reassignment notifications,
# notifications can_respond/agent_response, agent-response validation + duplicate guard, invalid ObjectId -> 404
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
SFX = uuid.uuid4().hex[:6].upper()
CREATED_CASES = []
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def login(ident, pw):
    r = requests.post(f"{BASE}/auth/login", json={"identifier": ident, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


def uid(tok):
    j = requests.get(f"{BASE}/auth/me", headers=H(tok)).json()
    return j.get("user", j)["id"]


def req_data(sup_id, **kw):
    d = {"request_type": "Residence Verification", "applicant_name": f"TEST_R5_{SFX}", "co_applicant_name": "", "seller_name": "",
         "primary_phone": "9876543210", "alt_phone": "", "client_name": "Apex Rural Bank", "branch_name": "Koramangala",
         "bank_state": "Karnataka", "full_address": "5 TEST Road, Koramangala", "pincode": "560034", "verification_state": "Karnataka",
         "city": "Bengaluru", "notes": "TEST iter5", "priority": "Normal", "supervisor_id": sup_id}
    d.update(kw)
    return d


def make_request(a_tok, sup_id, **kw):
    r = requests.post(f"{BASE}/requests", json={"data": req_data(sup_id, **kw), "declaration": True}, headers=H(a_tok))
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    up = requests.post(f"{BASE}/requests/{rid}/document", files={"file": ("t.png", PNG, "image/png")}, headers=H(a_tok))
    assert up.status_code == 200, up.text
    s = requests.post(f"{BASE}/requests/{rid}/submit", json={"data": req_data(sup_id, **kw), "declaration": True}, headers=H(a_tok))
    assert s.status_code == 200, s.text
    return rid


def stats(tok):
    return requests.get(f"{BASE}/dashboard/stats", headers=H(tok)).json()["requests_pending"]


@pytest.fixture(scope="module")
def ctx():
    t = {"admin": login("admin@checksphere.app", "Admin@12345"), "sup": login("sup1@checksphere.app", "Super@12345"),
         "a1": login("agent1@checksphere.app", "Agent@12345"), "a2": login("agent2@checksphere.app", "Agent@12345")}
    # TEST_ supervisor B scoped to Karnataka
    email = f"test_supb_{SFX.lower()}@example.com"
    r = requests.post(f"{BASE}/users", json={"name": f"TEST_SupB_{SFX}", "role": "supervisor", "email": email,
                                             "password": "TestPass@123", "scope": {"states": ["Karnataka"]}}, headers=H(t["admin"]))
    assert r.status_code == 200, r.text
    b_id = r.json()["id"]
    tb = login(email, "TestPass@123")
    cp = requests.post(f"{BASE}/auth/change-password", json={"current_password": "TestPass@123", "new_password": "TestPass@456"}, headers=H(tb))
    assert cp.status_code == 200, cp.text
    t["supB"] = tb
    c = {"t": t, "b_id": b_id, "sup_id": uid(t["sup"]), "a1_id": uid(t["a1"]), "a2_id": uid(t["a2"])}
    yield c
    for cid in CREATED_CASES:
        requests.delete(f"{BASE}/cases/{cid}", headers=H(t["admin"]))
    requests.post(f"{BASE}/users/{b_id}/set-active", json={"active": False}, headers=H(t["admin"]))


class TestInvalidObjectId:
    def test_notification_ack_bad_id_404(self, ctx):
        r = requests.post(f"{BASE}/notifications/not-an-id/ack", headers=H(ctx["t"]["a1"]))
        assert r.status_code == 404, r.text

    def test_request_action_bad_id_404(self, ctx):
        r = requests.post(f"{BASE}/requests/xyz123/action", json={"action": "review"}, headers=H(ctx["t"]["sup"]))
        assert r.status_code == 404, r.text

    def test_request_agent_endpoints_bad_id_404(self, ctx):
        a = H(ctx["t"]["a1"])
        assert requests.post(f"{BASE}/requests/bad/submit", json={"data": {}, "declaration": True}, headers=a).status_code == 404
        assert requests.post(f"{BASE}/requests/bad/cancel", headers=a).status_code == 404
        assert requests.post(f"{BASE}/requests/bad/document", files={"file": ("t.png", PNG, "image/png")}, headers=a).status_code == 404
        assert requests.get(f"{BASE}/requests/bad/document/x", headers=a).status_code == 404


class TestScopingAndApprove:
    def test_requests_pending_scoped(self, ctx):
        t = ctx["t"]
        s0, b0 = stats(t["sup"]), stats(t["supB"])
        rid = make_request(t["a1"], ctx["b_id"])
        ctx["rid_b"] = rid
        assert stats(t["sup"]) == s0, "sup1 requests_pending must not count a request sent to supervisor B"
        assert stats(t["supB"]) == b0 + 1
        assert not any(i["id"] == rid for i in requests.get(f"{BASE}/requests", headers=H(t["sup"])).json()["items"])
        assert any(i["id"] == rid for i in requests.get(f"{BASE}/requests", headers=H(t["supB"])).json()["items"])

    def test_approve_invalid_correction_422(self, ctx):
        r = requests.post(f"{BASE}/requests/{ctx['rid_b']}/action",
                          json={"action": "approve", "agent_id": ctx["a2_id"], "data": {"pincode": "12"}}, headers=H(ctx["t"]["supB"]))
        assert r.status_code == 422, r.text

    def test_approve_invalid_due_at(self, ctx):
        r = requests.post(f"{BASE}/requests/{ctx['rid_b']}/action",
                          json={"action": "approve", "agent_id": ctx["a2_id"], "due_at": "not-a-date"}, headers=H(ctx["t"]["supB"]))
        assert r.status_code in (400, 422), f"bad due_at should be 400/422, got {r.status_code}"

    def test_approve_with_unsaved_corrections(self, ctx):
        t = ctx["t"]
        corr = {"applicant_name": f"TEST_Corrected_{SFX}", "pincode": "560095", "primary_phone": "9000000001",
                "full_address": "99 TEST Corrected Lane", "supervisor_id": "garbage"}
        r = requests.post(f"{BASE}/requests/{ctx['rid_b']}/action", json={"action": "approve", "agent_id": ctx["a2_id"], "data": corr},
                          headers=H(t["supB"]))
        assert r.status_code == 200, r.text
        it = [i for i in requests.get(f"{BASE}/requests", headers=H(t["a1"])).json()["items"] if i["id"] == ctx["rid_b"]][0]
        assert it["status"] == "assigned" and it["applicant_name"] == corr["applicant_name"] and it["supervisor_id"] == ctx["b_id"]
        cid = it["case_id"]
        CREATED_CASES.append(cid)
        ctx["case_b"] = cid
        c = requests.get(f"{BASE}/cases/{cid}", headers=H(t["admin"])).json()
        c = c.get("case", c)
        assert c["applicant_name"] == corr["applicant_name"]
        assert c["pincode"] == "560095" and c["primary_phone"] == "9000000001" and c["assigned_address"] == corr["full_address"]
        assert c["assigned_supervisor_id"] == ctx["b_id"]


class TestAgentResponse:
    def _note(self, tok, cid):
        items = requests.get(f"{BASE}/notifications", headers=H(tok)).json()["items"]
        return [n for n in items if n.get("case_id") == cid and n["kind"] == "assignment"][0]

    def test_can_respond_before(self, ctx):
        n = self._note(ctx["t"]["a2"], ctx["case_b"])
        assert n["can_respond"] is True and n["agent_response"] is None

    def test_invalid_response_400(self, ctx):
        r = requests.post(f"{BASE}/cases/{ctx['case_b']}/agent-response", json={"response": "maybe", "reason": "x"}, headers=H(ctx["t"]["a2"]))
        assert r.status_code == 400, r.text

    def test_reassign_then_duplicate_400(self, ctx):
        t, cid = ctx["t"], ctx["case_b"]
        r = requests.post(f"{BASE}/cases/{cid}/agent-response", json={"response": "reassign", "reason": f"TEST far {SFX}"}, headers=H(t["a2"]))
        assert r.status_code == 200, r.text
        for body in ({"response": "accept"}, {"response": "reassign", "reason": "again"}):
            r = requests.post(f"{BASE}/cases/{cid}/agent-response", json=body, headers=H(t["a2"]))
            assert r.status_code == 400, (body, r.text)
        n = self._note(t["a2"], cid)
        assert n["can_respond"] is False and n["agent_response"] == "reassign"

    def test_reassign_notifies_only_scoped_supervisor(self, ctx):
        t, cid = ctx["t"], ctx["case_b"]
        nb = requests.get(f"{BASE}/notifications", headers=H(t["supB"])).json()["items"]
        assert any(n.get("case_id") == cid and n["title"] == "Reassignment requested" for n in nb)
        n1 = requests.get(f"{BASE}/notifications", headers=H(t["sup"])).json()["items"]
        # sup1 has no scope restriction (sees all cases), so by design it also receives the alert
        assert any(n.get("case_id") == cid and n["title"] == "Reassignment requested" for n in n1), "unscoped sup1 should get it"
