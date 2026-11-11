"""Demo data seeding (runs only when the users collection is empty)."""
from datetime import timedelta

import core
import security
from report_config import REPORT_TYPES


async def seed_if_empty() -> bool:
    if await core.db.users.count_documents({}) > 0:
        return False

    users = {}
    for name, role, email, agent_id, pwd in [
        ("CheckSphere Admin", "super_admin", "admin@checksphere.app", None, "Admin@12345"),
        ("Meera Joshi", "supervisor", "sup1@checksphere.app", "SPV01", "Super@12345"),
        ("Ravi Kumar", "agent", "agent1@checksphere.app", "AGT101", "Agent@12345"),
        ("Anita Desai", "agent", "agent2@checksphere.app", "AGT102", "Agent@12345"),
    ]:
        doc = {
            "role": role, "name": name, "email": email, "agent_id": agent_id,
            "phone": None, "password_hash": security.hash_password(pwd),
            "must_change_password": role != "super_admin", "disabled": False, "scope": {},
            "created_at": core.now(),
        }
        res = await core.db.users.insert_one(doc)
        users[name] = str(res.inserted_id)

    clients = {}
    for cname, code in [("Metro Capital Finance", "MCF"), ("Apex Rural Bank", "ARB")]:
        res = await core.db.clients.insert_one({"name": cname, "code": code, "active": True, "created_at": core.now()})
        clients[cname] = str(res.inserted_id)

    branches = {}
    for bname, client, city, state in [
        ("Andheri Branch", "Metro Capital Finance", "Mumbai", "Maharashtra"),
        ("Connaught Place Branch", "Metro Capital Finance", "New Delhi", "Delhi"),
        ("Koramangala Branch", "Apex Rural Bank", "Bengaluru", "Karnataka"),
    ]:
        res = await core.db.branches.insert_one({
            "client_id": clients[client], "name": bname, "city": city, "state": state,
            "active": True, "created_at": core.now()})
        branches[bname] = str(res.inserted_id)

    now = core.now()

    def tl(action, uname, details=None, hours_ago=0):
        return {"action": action, "by": users.get(uname, ""), "by_name": uname, "at": now - timedelta(hours=hours_ago),
                "details": details or {}}

    seed_cases = [
        # (client, branch, applicant, coapplicant, loan, rtype, address, city, state, priority, due_hours, status, agent, flags)
        ("Metro Capital Finance", "Andheri Branch", "Rahul Sharma", None, "Home Loan", "residence_applicant",
         "B-402, Green Meadows, Andheri West, Mumbai", "Mumbai", "Maharashtra", "High", 24, "new", None, []),
        ("Metro Capital Finance", "Andheri Branch", "Priya Nair", None, "Personal Loan", "residence_applicant",
         "701, Sea Breeze, Versova Road, Mumbai", "Mumbai", "Maharashtra", "Medium", 48, "new", None, []),
        ("Apex Rural Bank", "Koramangala Branch", "Farhan Ali", "Sana Ali", "Business Loan", "business_applicant",
         "Shop 12, 5th Block Koramangala, Bengaluru", "Bengaluru", "Karnataka", "High", 36, "assigned", "Ravi Kumar", []),
        ("Metro Capital Finance", "Connaught Place Branch", "Vikram Singh", None, "Home Loan", "residence_coapplicant",
         "22, Ring Road Flats, Connaught Place, New Delhi", "New Delhi", "Delhi", "Medium", 72, "assigned", "Anita Desai", []),
        ("Apex Rural Bank", "Koramangala Branch", "Lata Menon", None, "Vehicle Loan", "kyc",
         "Koramangala Branch, Bengaluru", "Bengaluru", "Karnataka", "Medium", 48, "assigned", "Ravi Kumar", []),
        ("Metro Capital Finance", "Andheri Branch", "Suresh Patil", None, "Home Loan", "tel_residence",
         "Registered mobile verification, Mumbai", "Mumbai", "Maharashtra", "Low", 96, "assigned", "Anita Desai", []),
        ("Metro Capital Finance", "Andheri Branch", "Deepak Rane", None, "Personal Loan", "residence_applicant",
         "A-9, Shivaji Nagar, Andheri East, Mumbai", "Mumbai", "Maharashtra", "High", -48, "in_progress", "Ravi Kumar", []),
        ("Apex Rural Bank", "Koramangala Branch", "Kiran Rao", None, "Business Loan", "income",
         "Income documents, Bengaluru", "Bengaluru", "Karnataka", "Medium", 24, "in_progress", "Anita Desai", []),
        ("Metro Capital Finance", "Connaught Place Branch", "Neha Gupta", None, "Home Loan", "residence_applicant",
         "14, Model Town Phase 2, New Delhi", "New Delhi", "Delhi", "High", -24, "submitted", "Ravi Kumar",
         ["far_from_assigned_address", "low_gps_accuracy"]),
        ("Apex Rural Bank", "Koramangala Branch", "Amit Verma", None, "Business Loan", "business_applicant",
         "80 Feet Road, Indiranagar, Bengaluru", "Bengaluru", "Karnataka", "Medium", -12, "submitted", "Anita Desai", []),
        ("Metro Capital Finance", "Andheri Branch", "Sanjay Mhatre", None, "Home Loan", "residence_applicant",
         "Plot 7, Panvel, Navi Mumbai", "Mumbai", "Maharashtra", "Medium", 24, "under_review", "Ravi Kumar", []),
        ("Apex Rural Bank", "Koramangala Branch", "Geeta Shetty", None, "Vehicle Loan", "kyc",
         "Koramangala Branch, Bengaluru", "Bengaluru", "Karnataka", "Low", 48, "returned", "Anita Desai", []),
        ("Metro Capital Finance", "Connaught Place Branch", "Rohit Khanna", None, "Personal Loan", "tel_office",
         "Office landline verification, New Delhi", "New Delhi", "Delhi", "Medium", 72, "approved", "Ravi Kumar", []),
        ("Metro Capital Finance", "Andheri Branch", "Meenal Kulkarni", None, "Home Loan", "residence_applicant",
         "5, Hill Road, Bandra West, Mumbai", "Mumbai", "Maharashtra", "High", 48, "approved", "Anita Desai", []),
    ]

    for idx, (client, branch, applicant, coapp, loan, rtype, address, city, state, priority, due_hours, status, agent, flags) in enumerate(seed_cases):
        seq = idx + 1
        created_h = 24 * (len(seed_cases) - idx) // 2 + 6
        doc = {
            "internal_case_id": f"CSV-{seq:06d}", "client_case_id": f"CL-2026-{1000 + seq}",
            "client_id": clients[client], "client_name": client,
            "branch_id": branches[branch], "branch_name": branch,
            "applicant_name": applicant, "co_applicant_name": coapp, "loan_type": loan, "report_type": rtype,
            "assigned_address": address, "city": city, "state": state, "priority": priority,
            "due_at": now + timedelta(hours=due_hours), "status": status,
            "assigned_agent_id": users.get(agent) if agent else None, "assigned_agent_name": agent,
            "created_by": users["CheckSphere Admin"], "flags": flags, "timeline": [
                tl("case_created", "CheckSphere Admin", {"source": "seed"}, hours_ago=created_h)],
            "created_at": now - timedelta(hours=created_h), "updated_at": now - timedelta(hours=created_h // 2),
        }
        if agent:
            doc["timeline"].append(tl("assigned", "CheckSphere Admin", {"agent": agent}, hours_ago=created_h - 2))
        if status in ("submitted", "under_review", "approved", "returned"):
            gps = {"lat": 19.1136, "lon": 72.8697, "accuracy": 24 if "far_from_assigned_address" in flags else 6}
            if "far_from_assigned_address" in flags:
                gps = {"lat": 19.22, "lon": 73.01, "accuracy": 210}
            sub_h = max(created_h - 4, 1)
            rep = {
                "case_id": None, "version": 1, "status": "submitted" if status in ("submitted", "under_review", "approved", "returned") else "draft",
                "report_type": rtype, "data": report_data_for(rtype, client, branch, applicant, agent),
                "gps": gps if REPORT_TYPES[rtype]["category"] == "physical" else {},
                "declaration": True, "flags": flags if status not in ("returned",) else [],
                "offline_synced": False, "submitted_by": users.get(agent), "submitted_by_name": agent,
                "submitted_at": now - timedelta(hours=sub_h), "created_at": now - timedelta(hours=sub_h),
                "updated_at": now - timedelta(hours=sub_h),
            }
            res = await core.db.cases.insert_one(doc)
            case_id = str(res.inserted_id)
            rep["case_id"] = case_id
            rep_res = await core.db.reports.insert_one(rep)
            doc_updates = {"last_submitted_at": rep["submitted_at"], "last_gps": rep["gps"]}
            if status == "under_review":
                doc_updates["status"] = "under_review"
                await core.db.reports.update_one({"_id": rep_res.inserted_id}, {"$set": {"status": "under_review"}})
            if status == "approved":
                doc_updates.update({"approved_at": now - timedelta(hours=max(sub_h - 3, 1)), "approved_by": "Meera Joshi",
                                    "reviewed_by": "Meera Joshi", "reviewed_by_name": "Meera Joshi", "reviewed_at": now - timedelta(hours=max(sub_h - 3, 1))})
                await core.db.reports.update_one({"_id": rep_res.inserted_id}, {"$set": {
                    "status": "approved", "reviewed_by": users["Meera Joshi"], "reviewed_by_name": "Meera Joshi",
                    "reviewed_at": now - timedelta(hours=max(sub_h - 3, 1))}})
            if status == "returned":
                doc_updates["status"] = "returned"
                await core.db.reports.update_one({"_id": rep_res.inserted_id}, {"$set": {
                    "status": "returned", "reviewed_by": users["Meera Joshi"], "reviewed_by_name": "Meera Joshi",
                    "reviewed_at": now - timedelta(hours=max(sub_h - 2, 1)),
                    "review_comment": "Person met name is missing and the selfie photo does not show the entrance. Please re-verify and add the observed house number."}})
            await core.db.cases.update_one({"_id": res.inserted_id}, {"$set": doc_updates, "$push": {
                "timeline": tl("report_submitted", agent, {"version": 1}, hours_ago=sub_h)}})
            if status == "approved":
                await core.db.cases.update_one({"_id": res.inserted_id}, {"$push": {
                    "timeline": tl("report_approve", "Meera Joshi", {}, hours_ago=max(sub_h - 3, 1))}})
            if status == "returned":
                await core.db.cases.update_one({"_id": res.inserted_id}, {"$push": {
                    "timeline": tl("report_return", "Meera Joshi", {"comment": "Correction required"}, hours_ago=max(sub_h - 2, 1))}})
        else:
            await core.db.cases.insert_one(doc)

    # Call logs for the telephone case
    tel_case = await core.db.cases.find_one({"report_type": "tel_residence"})
    if tel_case:
        for result, hrs, notes in [("No Response", 30, "First attempt, no response"), ("Busy", 26, "Line busy"),
                                   ("Confirmed", 24, "Applicant confirmed residence details; person met stated correct address")]:
            await core.db.call_logs.insert_one({
                "case_id": str(tel_case["_id"]), "agent_id": users["Anita Desai"], "agent_name": "Anita Desai",
                "phone_number": "+91 98200 11223", "result": result, "person_met": "Rahul" if result == "Confirmed" else None,
                "relationship": "Applicant" if result == "Confirmed" else None,
                "info_confirmed": "Address and residence status" if result == "Confirmed" else None,
                "notes": notes, "attempt_at": now - timedelta(hours=hrs)})
        await core.db.cases.update_one({"_id": tel_case["_id"]}, {"$push": {"timeline": tl("call_attempt", "Anita Desai", {"result": "Confirmed"}, hours_ago=24)}})

    await core.db.counters.update_one({"_id": "case_seq"}, {"$set": {"seq": len(seed_cases)}}, upsert=True)
    await core.db.counters.update_one({"_id": "agent_id"}, {"$set": {"seq": 102}}, upsert=True)
    await core.db.audit_logs.insert_one({
        "user_id": "", "user_name": "system", "user_role": "system", "action": "seed_completed",
        "entity": "system", "entity_id": "", "details": {"cases": len(seed_cases)}, "ip": None, "created_at": core.now()})
    return True


def report_data_for(rtype, client, branch, applicant, agent):
    cfg = REPORT_TYPES[rtype]
    data = {}
    for section in cfg["sections"]:
        for f in section["fields"]:
            k = f["key"]
            if k == "client_name":
                data[k] = client
            elif k == "branch_name":
                data[k] = branch
            elif k in ("internal_case_id",):
                data[k] = "see case"
            elif k == "client_case_id":
                data[k] = "see case"
            elif k == "applicant_name":
                data[k] = applicant
            elif k == "agent_name":
                data[k] = f"{agent}"
            elif k == "visit_datetime":
                data[k] = "today"
            elif k == "assigned_address":
                data[k] = "As assigned"
            elif k == "observed_address":
                data[k] = "Address observed as assigned"
            elif k == "person_met":
                data[k] = "Family member"
            elif k == "relationship":
                data[k] = "Spouse"
            elif k == "address_outcome":
                data[k] = "Confirmed"
            elif k == "residence_status":
                data[k] = "Owned"
            elif k == "locality":
                data[k] = "Urban"
            elif k == "exterior_observation":
                data[k] = "Verifier observed a well-maintained residential premises matching the assigned address."
            elif k == "nature_of_business":
                data[k] = "Retail trading office"
            elif k == "board_present":
                data[k] = "Yes"
            elif k == "business_operational":
                data[k] = "Yes"
            elif k == "relationship_to_business":
                data[k] = "Employee"
            elif k == "document_type":
                data[k] = "Aadhaar / PAN copy"
            elif k == "verification_method":
                data[k] = "Physical Document Review"
            elif k == "authorised_source":
                data[k] = "Client-shared document set"
            elif k == "verification_datetime":
                data[k] = "today"
            elif k == "verifier_name":
                data[k] = f"{agent}"
            elif k == "outcome":
                data[k] = "Confirmed"
            elif k == "information_confirmed":
                data[k] = "Person met stated the residence address matches the assigned address."
    return data
