# Cleanup for this test iteration: reset AGT102 password, deactivate TEST_ users created by tests, delete their cases by id
import sys, requests
sys.path.insert(0, "/app/backend/tests")
import test_checksphere_api as T

adm = T.login(*T.ADMIN).json()["access_token"]
h = T.H(adm)
users = requests.get(f"{T.BASE}/users", headers=h).json()["items"]
agt102 = [u for u in users if u.get("agent_id") == "AGT102"][0]
print("reset AGT102", requests.post(f"{T.BASE}/users/{agt102['id']}/reset-password", json={"password": "Agent@12345"}, headers=h).status_code)
mine = [u for u in users if (u.get("name") or "").startswith("TEST_") and (u.get("email") or "").endswith("@example.com")]
case_ids = set()
for u in mine:
    for c in requests.get(f"{T.BASE}/cases?agent_id={u['id']}&limit=200", headers=h).json()["items"]:
        if c.get("assigned_agent_id") == u["id"] and str(c.get("client_case_id", "")).startswith("TEST_"):
            case_ids.add(c["id"])
    requests.post(f"{T.BASE}/users/{u['id']}/set-active", json={"active": False}, headers=h)
deleted = [requests.delete(f"{T.BASE}/cases/{cid}", headers=h).status_code for cid in case_ids]
print("deactivated users", len(mine), "deleted cases", len(deleted), set(deleted))
