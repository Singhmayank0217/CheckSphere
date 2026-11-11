# Iteration 5 UI prep: agent1 raises a TEST_ request to sup1, sup1 approves allocating to agent1 -> assignment notification for agent1
import json
import sys

sys.path.insert(0, "/app/backend/tests")
from test_iter5_scoping_fixes import BASE, H, PNG, login, uid, req_data  # noqa: E402
import requests  # noqa: E402

sup = login("sup1@checksphere.app", "Super@12345")
a1 = login("agent1@checksphere.app", "Agent@12345")
sid, a1id = uid(sup), uid(a1)
d = req_data(sid, applicant_name="TEST_UI5_Accept")
rid = requests.post(f"{BASE}/requests", json={"data": d, "declaration": True}, headers=H(a1)).json()["id"]
requests.post(f"{BASE}/requests/{rid}/document", files={"file": ("t.png", PNG, "image/png")}, headers=H(a1))
assert requests.post(f"{BASE}/requests/{rid}/submit", json={"data": d, "declaration": True}, headers=H(a1)).status_code == 200
r = requests.post(f"{BASE}/requests/{rid}/action", json={"action": "approve", "agent_id": a1id}, headers=H(sup))
assert r.status_code == 200, r.text
it = [i for i in requests.get(f"{BASE}/requests", headers=H(a1)).json()["items"] if i["id"] == rid][0]
json.dump({"rid": rid, "case_id": it["case_id"]}, open("/tmp/ui5.json", "w"))
print(rid, it["case_id"], it["internal_case_id"])
