# Iteration 2 UI prep: TEST_ case assigned to AGT102 (for draft/back-btn tests); prints JSON ids
import json, sys, requests
sys.path.insert(0, "/app/backend/tests")
import test_checksphere_api as T
adm = T.login(*T.ADMIN).json()["access_token"]
h = T.H(adm)
users = requests.get(f"{T.BASE}/users", headers=h).json()["items"]
a = [u for u in users if u.get("agent_id") == "AGT102"][0]
clients = requests.get(f"{T.BASE}/clients", headers=h).json()["items"]
branches = requests.get(f"{T.BASE}/branches", headers=h).json()["items"]
master = (clients[0], [b for b in branches if b["client_id"] == clients[0]["id"]][0])
c = T.new_case(adm, master, "residence_applicant", a["id"],
               assigned_address="TEST Flat 1203, Very Long Tower Name Residency, Opposite Big Landmark Shopping Mall, Andheri West Link Road, Mumbai 400053")
print(json.dumps({"agt102": a["id"], "case": c["id"], "internal": c.get("internal_case_id")}))
