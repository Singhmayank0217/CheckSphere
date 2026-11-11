# Prepares TEST_ data for UI review testing: activated TEST agent + 2 submitted cases (prints JSON ids)
import json, sys
sys.path.insert(0, "/app/backend/tests")
import test_checksphere_api as T
import requests

adm = T.login(*T.ADMIN).json()["access_token"]
clients = requests.get(f"{T.BASE}/clients", headers=T.H(adm)).json()["items"]
branches = requests.get(f"{T.BASE}/branches", headers=T.H(adm)).json()["items"]
master = (clients[0], [b for b in branches if b["client_id"] == clients[0]["id"]][0])
u, b = T.make_user(adm, "agent", "UI")
tok = T.activate(b["agent_id"], b["password"])
out = {"agent_id": u["id"], "agent_code": b["agent_id"], "cases": []}
for i in range(2):
    c = T.new_case(adm, master, "tel_residence", u["id"])
    cfg = requests.get(f"{T.BASE}/reports/case/{c['id']}", headers=T.H(tok)).json()["config"]
    for _ in range(3):
        requests.post(f"{T.BASE}/cases/{c['id']}/call-logs", headers=T.H(tok), json={"phone_number": "9876543210", "result": "Confirmed"})
    s = requests.post(f"{T.BASE}/reports/case/{c['id']}/submit", json={"data": T.fill(cfg), "declaration": True}, headers=T.H(tok))
    out["cases"].append({"id": c["id"], "ccid": c.get("client_case_id"), "submit": s.status_code})
# an unassigned TEST case for the assign modal
c3 = T.new_case(adm, master, "residence_applicant")
out["unassigned"] = {"id": c3["id"], "ccid": c3.get("client_case_id")}
print(json.dumps(out))
