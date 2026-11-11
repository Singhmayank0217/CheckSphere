# Iteration 4: agent case requests -> supervisor approve/allocate, notifications, agent accept/reassign, pending alerts stats, new case fields, import/export columns
import io
import os
import uuid
import pytest
import requests
from openpyxl import Workbook, load_workbook


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
NEW_COLS = ["Co-applicant Name", "Seller Name", "Primary Contact Number", "Alternate Phone", "Bank State", "Pincode",
            "State of Verification", "Notes"]


def login(ident, pw):
    r = requests.post(f"{BASE}/auth/login", json={"identifier": ident, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def H(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def toks():
    t = {"admin": login("admin@checksphere.app", "Admin@12345"), "sup": login("sup1@checksphere.app", "Super@12345"),
         "a1": login("agent1@checksphere.app", "Agent@12345"), "a2": login("agent2@checksphere.app", "Agent@12345")}
    yield t
    for cid in CREATED_CASES:
        requests.delete(f"{BASE}/cases/{cid}", headers=H(t["admin"]))


def me(tok):
    return requests.get(f"{BASE}/auth/me", headers=H(tok)).json()


def req_data(sup_id, **kw):
    d = {"request_type": "Residence Verification", "applicant_name": f"TEST_Req_{SFX}", "co_applicant_name": "TEST_Co",
         "seller_name": "", "primary_phone": "9876543210", "alt_phone": "9123456780", "client_name": "Metro Capital Finance",
         "branch_name": "Andheri", "bank_state": "Maharashtra", "full_address": "12 Test Street, Andheri", "pincode": "400053",
         "verification_state": "Maharashtra", "city": "Mumbai", "notes": "TEST note", "priority": "Normal", "supervisor_id": sup_id}
    d.update(kw)
    return d


@pytest.fixture(scope="module")
def flow(toks):
    """agent1 creates + uploads doc + submits a request to sup1"""
    sups = requests.get(f"{BASE}/requests/supervisors", headers=H(toks["a1"])).json()["items"]
    sup_me = me(toks["sup"])
    sup_id = sup_me.get("id") or sup_me.get("user", {}).get("id")
    assert any(s["id"] == sup_id for s in sups), (sups, sup_me)
    r = requests.post(f"{BASE}/requests", json={"data": req_data(sup_id), "declaration": False}, headers=H(toks["a1"]))
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    return {"rid": rid, "sup_id": sup_id}


class TestRequestSubmit:
    def test_submit_without_doc_422(self, toks, flow):
        r = requests.post(f"{BASE}/requests/{flow['rid']}/submit", json={"data": req_data(flow["sup_id"]), "declaration": True}, headers=H(toks["a1"]))
        assert r.status_code == 422
        assert any("document" in p.lower() for p in r.json()["detail"]["problems"])

    def test_submit_validation_missing_sup_pin_phone(self, toks, flow):
        r = requests.post(f"{BASE}/requests/{flow['rid']}/submit",
                          json={"data": req_data("", pincode="1234", primary_phone=""), "declaration": False}, headers=H(toks["a1"]))
        assert r.status_code == 422
        probs = " ".join(r.json()["detail"]["problems"]).lower()
        for s in ("supervisor", "pincode", "primary contact", "declaration"):
            assert s in probs, probs

    def test_upload_doc_and_submit(self, toks, flow):
        files = {"file": ("test_doc.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png")}
        r = requests.post(f"{BASE}/requests/{flow['rid']}/document", files=files, headers=H(toks["a1"]))
        assert r.status_code == 200, r.text
        assert "path" not in r.json() and r.json()["filename"] == "test_doc.png"
        r = requests.post(f"{BASE}/requests/{flow['rid']}/submit", json={"data": req_data(flow["sup_id"]), "declaration": True}, headers=H(toks["a1"]))
        assert r.status_code == 200, r.text
        items = requests.get(f"{BASE}/requests", headers=H(toks["a1"])).json()["items"]
        mine = [i for i in items if i["id"] == flow["rid"]][0]
        assert mine["status"] == "sent_for_allocation" and mine["supervisor_id"] == flow["sup_id"]
        assert "_id" not in mine

    def test_double_submit_400(self, toks, flow):
        r = requests.post(f"{BASE}/requests/{flow['rid']}/submit", json={"data": req_data(flow["sup_id"]), "declaration": True}, headers=H(toks["a1"]))
        assert r.status_code == 400

    def test_agent2_cannot_see_agent1_request(self, toks, flow):
        items = requests.get(f"{BASE}/requests", headers=H(toks["a2"])).json()["items"]
        assert not any(i["id"] == flow["rid"] for i in items)


class TestSupervisorActions:
    def test_supervisor_sees_request(self, toks, flow):
        items = requests.get(f"{BASE}/requests", headers=H(toks["sup"])).json()["items"]
        assert any(i["id"] == flow["rid"] for i in items)
        notes = requests.get(f"{BASE}/notifications", headers=H(toks["sup"])).json()["items"]
        assert any(n["title"] == "New case request" for n in notes)

    def test_agent_cannot_action(self, toks, flow):
        r = requests.post(f"{BASE}/requests/{flow['rid']}/action", json={"action": "review"}, headers=H(toks["a1"]))
        assert r.status_code == 403

    def test_clarify_reject_need_comment(self, toks, flow):
        for a in ("clarify", "reject"):
            r = requests.post(f"{BASE}/requests/{flow['rid']}/action", json={"action": a, "comment": " "}, headers=H(toks["sup"]))
            assert r.status_code == 400, (a, r.text)

    def test_edit(self, toks, flow):
        r = requests.post(f"{BASE}/requests/{flow['rid']}/action", json={"action": "edit", "data": {"notes": "TEST edited"}}, headers=H(toks["sup"]))
        assert r.status_code == 200 and r.json()["status"] == "under_review"
        it = [i for i in requests.get(f"{BASE}/requests", headers=H(toks["sup"])).json()["items"] if i["id"] == flow["rid"]][0]
        assert it["notes"] == "TEST edited"

    def test_approve_requires_agent(self, toks, flow):
        r = requests.post(f"{BASE}/requests/{flow['rid']}/action", json={"action": "approve"}, headers=H(toks["sup"]))
        assert r.status_code == 400

    def test_approve_allocate_agent2(self, toks, flow):
        a2 = me(toks["a2"])
        a2_id = a2.get("id") or a2.get("user", {}).get("id")
        r = requests.post(f"{BASE}/requests/{flow['rid']}/action", json={"action": "approve", "agent_id": a2_id}, headers=H(toks["sup"]))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "assigned"
        it = [i for i in requests.get(f"{BASE}/requests", headers=H(toks["a1"])).json()["items"] if i["id"] == flow["rid"]][0]
        assert it["internal_case_id"].startswith("CSV-") and it["assigned_agent_id"] == a2_id
        flow["case_id"] = it["case_id"]
        CREATED_CASES.append(it["case_id"])
        c = requests.get(f"{BASE}/cases/{it['case_id']}", headers=H(toks["a2"])).json()
        c = c.get("case", c)
        assert c["primary_phone"] == "9876543210" and c["pincode"] == "400053" and c["status"] == "assigned"
        n2 = requests.get(f"{BASE}/notifications", headers=H(toks["a2"])).json()
        assert any(n.get("case_id") == it["case_id"] and n["kind"] == "assignment" for n in n2["items"])
        n1 = requests.get(f"{BASE}/notifications", headers=H(toks["a1"])).json()["items"]
        assert any(n["title"] == "Your request was approved" for n in n1)

    def test_approve_again_400(self, toks, flow):
        r = requests.post(f"{BASE}/requests/{flow['rid']}/action", json={"action": "reject", "comment": "x"}, headers=H(toks["sup"]))
        assert r.status_code == 400


class TestNotificationsAgentResponse:
    def test_ack(self, toks, flow):
        n = requests.get(f"{BASE}/notifications", headers=H(toks["a2"])).json()
        nid = [x for x in n["items"] if x.get("case_id") == flow["case_id"]][0]["id"]
        assert requests.post(f"{BASE}/notifications/{nid}/ack", headers=H(toks["a2"])).status_code == 200
        n2 = requests.get(f"{BASE}/notifications", headers=H(toks["a2"])).json()
        assert [x for x in n2["items"] if x["id"] == nid][0]["acknowledged_at"]
        assert n2["unread"] == n["unread"] - 1

    def test_accept_and_reassign(self, toks, flow):
        cid = flow["case_id"]
        assert requests.post(f"{BASE}/cases/{cid}/agent-response", json={"response": "reassign"}, headers=H(toks["a2"])).status_code == 400
        assert requests.post(f"{BASE}/cases/{cid}/agent-response", json={"response": "accept"}, headers=H(toks["a1"])).status_code == 403
        r = requests.post(f"{BASE}/cases/{cid}/agent-response", json={"response": "accept"}, headers=H(toks["a2"]))
        assert r.status_code == 200
        # iter5: a second response after accepting is rejected (duplicate guard)
        r = requests.post(f"{BASE}/cases/{cid}/agent-response", json={"response": "reassign", "reason": "TEST too far"}, headers=H(toks["a2"]))
        assert r.status_code == 400
        c = requests.get(f"{BASE}/cases/{cid}", headers=H(toks["admin"])).json()
        c = c.get("case", c)
        assert c.get("agent_response") == "accept"


class TestStatsCasesImportExport:
    def test_dashboard_stats(self, toks):
        for k in ("admin", "sup"):
            d = requests.get(f"{BASE}/dashboard/stats", headers=H(toks[k])).json()
            for f in ("pending_24h", "pending_48h", "requests_pending"):
                assert isinstance(d.get(f), int), (k, f, d)

    def test_create_case_validation(self, toks):
        cl = requests.get(f"{BASE}/clients", headers=H(toks["admin"])).json()["items"][0]
        base = {"client_case_id": f"TEST_new_{SFX}", "client_id": cl["id"], "applicant_name": "TEST_App", "report_type": "residence_applicant",
                "assigned_address": "TEST addr"}
        assert requests.post(f"{BASE}/cases", json=base, headers=H(toks["admin"])).status_code == 400
        assert requests.post(f"{BASE}/cases", json={**base, "primary_phone": "98765", "pincode": "12345"}, headers=H(toks["admin"])).status_code == 400
        r = requests.post(f"{BASE}/cases", json={**base, "primary_phone": "9876500000", "pincode": "560034", "seller_name": "TEST_Seller",
                                                 "bank_state": "Karnataka", "verification_state": "Karnataka", "notes": "n"}, headers=H(toks["admin"]))
        assert r.status_code in (200, 201), r.text
        c = r.json().get("case", r.json())
        CREATED_CASES.append(c["id"])
        assert c["seller_name"] == "TEST_Seller" and c["pincode"] == "560034"

    def test_import_template_columns(self, toks):
        r = requests.get(f"{BASE}/cases/import-template", headers=H(toks["admin"]))
        hdr = [c.value for c in load_workbook(io.BytesIO(r.content)).active[1]]
        for col in NEW_COLS:
            assert col in hdr, (col, hdr)

    def test_import_new_columns(self, toks):
        r = requests.get(f"{BASE}/cases/import-template", headers=H(toks["admin"]))
        hdr = [c.value for c in load_workbook(io.BytesIO(r.content)).active[1]]
        wb = Workbook()
        ws = wb.active
        ws.append(hdr)
        vals = {"Client Case ID": f"TEST_imp_{SFX}", "Client Name": "Metro Capital Finance", "Branch Name": "Andheri", "Applicant Name": "TEST_Imp",
                "Report Type": None, "Assigned Address": "TEST", "Primary Contact Number": 9876511111, "Pincode": 400001,
                "Seller Name": "TEST_ImpSeller", "State of Verification": "Maharashtra"}
        # report type display name taken from the template's sample row
        sample = list(load_workbook(io.BytesIO(r.content)).active.iter_rows(min_row=2, max_row=2, values_only=True))
        vals["Report Type"] = sample[0][hdr.index("Report Type")] if sample else "Residence Verification - Applicant"
        ws.append([vals.get(h) for h in hdr])
        bad = dict(vals, **{"Client Case ID": f"TEST_impbad_{SFX}", "Pincode": "12"})
        ws.append([bad.get(h) for h in hdr])
        buf = io.BytesIO()
        wb.save(buf)
        res = requests.post(f"{BASE}/cases/import", files={"file": ("t.xlsx", buf.getvalue())}, headers=H(toks["admin"])).json()
        assert res["created"] == 1, res
        assert any("pincode" in e for e in res["errors"])
        items = requests.get(f"{BASE}/cases", params={"q": f"TEST_imp_{SFX}", "limit": 50}, headers=H(toks["admin"])).json()["items"]
        m = [c for c in items if c.get("client_case_id") == f"TEST_imp_{SFX}"]
        assert m, "imported case not found via q"
        CREATED_CASES.append(m[0]["id"])
        assert m[0].get("primary_phone") == "9876511111" and m[0].get("pincode") == "400001", m[0]

    def test_export_cases_columns(self, toks):
        r = requests.get(f"{BASE}/exports/cases.xlsx", headers=H(toks["admin"]))
        assert r.status_code == 200
        hdr = [c.value for c in load_workbook(io.BytesIO(r.content)).active[1]]
        for col in ("Co-applicant", "Seller", "Primary Contact", "Alternate Phone", "Bank State", "Pincode", "State of Verification", "Notes"):
            assert any(col.lower() in str(h).lower() for h in hdr), (col, hdr)
