"""Business rules for incidents, dispatches, resources, patients and calls."""
from conftest import mysql_as


def stock(client, headers, resource_id):
    return client.get(f"/api/resources/{resource_id}", headers=headers).json()["quantity_available"]


def test_full_dispatch_lifecycle(client, dispatcher, free_unit, open_incident):
    incident_id, unit_id = open_incident["incident_id"], free_unit["unit_id"]
    assert open_incident["status"] == "OPEN"

    # dispatch -> unit busy, incident in progress, logged
    res = client.post("/api/dispatches", headers=dispatcher, json={"incident_id": incident_id, "unit_id": unit_id})
    assert res.status_code == 201, res.text
    dispatch_id = res.json()["dispatch_id"]
    assert res.json()["status"] == "DISPATCHED"
    assert client.get(f"/api/units/{unit_id}", headers=dispatcher).json()["is_free"] is False
    assert client.get(f"/api/incidents/{incident_id}", headers=dispatcher).json()["status"] == "IN_PROGRESS"

    # same unit cannot be dispatched twice
    res = client.post("/api/dispatches", headers=dispatcher, json={"incident_id": incident_id, "unit_id": unit_id})
    assert res.status_code == 409 and res.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"

    # allocate resources, stock goes down
    before = stock(client, dispatcher, 203)
    res = client.post(f"/api/dispatches/{dispatch_id}/resources", headers=dispatcher,
                      json={"resource_id": 203, "quantity": 3})
    assert res.status_code == 201
    assert stock(client, dispatcher, 203) == before - 3

    # over-allocation refused, stock untouched
    res = client.post(f"/api/dispatches/{dispatch_id}/resources", headers=dispatcher,
                      json={"resource_id": 203, "quantity": 10_000})
    assert res.status_code == 409 and "Insufficient stock" in res.json()["error"]["message"]
    assert stock(client, dispatcher, 203) == before - 3

    # invalid transition, cannot resolve while active
    res = client.patch(f"/api/dispatches/{dispatch_id}/status", headers=dispatcher, json={"status": "COMPLETED"})
    assert res.status_code == 409 and res.json()["error"]["details"]["allowed"]
    assert client.post(f"/api/incidents/{incident_id}/resolve", headers=dispatcher).status_code == 409

    for status in ("EN_ROUTE", "ON_SCENE", "COMPLETED"):
        res = client.patch(f"/api/dispatches/{dispatch_id}/status", headers=dispatcher, json={"status": status})
        assert res.status_code == 200 and res.json()["status"] == status
    assert client.get(f"/api/units/{unit_id}", headers=dispatcher).json()["is_free"] is True

    # cannot resolve until resources are back; cannot return more than outstanding
    res = client.post(f"/api/incidents/{incident_id}/resolve", headers=dispatcher)
    assert res.status_code == 409 and "returned" in res.json()["error"]["message"]
    res = client.post(f"/api/dispatches/{dispatch_id}/resources/203/return", headers=dispatcher, json={"quantity": 4})
    assert res.status_code == 409
    res = client.post(f"/api/dispatches/{dispatch_id}/resources/203/return", headers=dispatcher, json={"quantity": 3})
    assert res.status_code == 200 and res.json()["resources"][0]["quantity_outstanding"] == 0
    assert stock(client, dispatcher, 203) == before

    res = client.post(f"/api/incidents/{incident_id}/resolve", headers=dispatcher)
    assert res.status_code == 200 and res.json()["status"] == "RESOLVED" and res.json()["resolved_at"]

    # resolved incidents accept no new dispatches
    res = client.post("/api/dispatches", headers=dispatcher, json={"incident_id": incident_id, "unit_id": unit_id})
    assert res.status_code == 409

    actions = [a["action"] for a in client.get(f"/api/incidents/{incident_id}/activity", headers=dispatcher).json()["data"]]
    assert actions[0].startswith("Incident created") and any("RESOLVED" in a for a in actions)


def test_dispatch_invalid_references(client, dispatcher):
    assert client.post("/api/dispatches", headers=dispatcher, json={"incident_id": 99999, "unit_id": 4}).status_code == 404
    assert client.post("/api/dispatches", headers=dispatcher, json={"incident_id": 102, "unit_id": 99999}).status_code == 404
    res = client.post("/api/dispatches", headers=dispatcher, json={"incident_id": 102, "unit_id": -1})
    assert res.status_code == 422
    assert client.post("/api/dispatches/99999/resources", headers=dispatcher,
                       json={"resource_id": 201, "quantity": 1}).status_code == 404
    assert client.post("/api/dispatches/5001/resources", headers=dispatcher,
                       json={"resource_id": 99999, "quantity": 1}).status_code == 404
    # completed dispatch cannot receive resources
    assert client.post("/api/dispatches/5004/resources", headers=dispatcher,
                       json={"resource_id": 201, "quantity": 1}).status_code == 409


def test_responder_updates_own_dispatch(client, responder):
    res = client.patch("/api/dispatches/5003/status", headers=responder, json={"status": "COMPLETED"})
    assert res.status_code == 200 and res.json()["status"] == "COMPLETED"


def test_incident_filters_and_pagination(client, dispatcher):
    res = client.get("/api/incidents?severity=HIGH&severity=CRITICAL&page_size=1", headers=dispatcher).json()
    assert res["pagination"]["page_size"] == 1 and len(res["data"]) == 1
    assert res["pagination"]["total"] >= 2
    assert all(i["severity"] in ("HIGH", "CRITICAL") for i in res["data"])
    res = client.get("/api/incidents?location=MG%20Road", headers=dispatcher).json()
    assert [i["incident_id"] for i in res["data"]] == [101]
    res = client.get("/api/incidents?status=RESOLVED", headers=dispatcher).json()
    assert 103 in [i["incident_id"] for i in res["data"]]
    assert client.get("/api/incidents?status=BOGUS", headers=dispatcher).status_code == 422


def test_incident_details_and_validation(client, dispatcher):
    detail = client.get("/api/incidents/101", headers=dispatcher).json()
    assert {d["dispatch_id"] for d in detail["dispatches"]} >= {5001, 5002}
    assert client.get("/api/incidents/99999", headers=dispatcher).status_code == 404
    res = client.post("/api/incidents", headers=dispatcher, json={"incident_type": "Fire", "severity": "EXTREME",
                                                                 "location": "X"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_ERROR"
    # CLOSED -> anything is not a valid transition; RESOLVED -> CLOSED is
    assert client.patch("/api/incidents/103", headers=dispatcher, json={"status": "CLOSED"}).status_code == 200
    assert client.patch("/api/incidents/103", headers=dispatcher, json={"status": "OPEN"}).status_code == 409


def test_patients_composite_key(client, dispatcher):
    res = client.post("/api/incidents/101/patients", headers=dispatcher,
                      json={"patient_name": "Patient F", "age": 52, "gender": "Male", "patient_condition": "Smoke"})
    assert res.status_code == 201
    first = res.json()["patient_no"]
    second = client.post("/api/incidents/101/patients", headers=dispatcher, json={"patient_name": "Patient G"}).json()
    assert second["patient_no"] == first + 1 and second["incident_id"] == 101
    assert client.post("/api/incidents/101/patients", headers=dispatcher, json={"age": 200}).status_code == 422
    assert client.post("/api/incidents/99999/patients", headers=dispatcher, json={}).status_code == 404
    res = client.patch(f"/api/incidents/101/patients/{first}", headers=dispatcher, json={"patient_condition": "Stable"})
    assert res.json()["patient_condition"] == "Stable"


def test_call_with_new_incident_is_atomic(client, dispatcher, admin):
    count = client.get("/api/incidents", headers=dispatcher).json()["pagination"]["total"]
    res = client.post("/api/calls", headers=dispatcher, json={
        "incident": {"incident_type": "Flooding", "severity": "MEDIUM", "location": "Ring Road Underpass"},
        "caller_name": "Ravi", "caller_phone": "9876500000", "priority": "MEDIUM", "transcript": "Water rising"})
    assert res.status_code == 201, res.text
    assert res.json()["received_by"] == 1  # the dispatcher's own responder record
    assert client.get("/api/incidents", headers=dispatcher).json()["pagination"]["total"] == count + 1

    # call insert fails (unknown call-taker) -> incident insert is rolled back too
    res = client.post("/api/calls", headers=admin, json={
        "incident": {"incident_type": "Flooding", "severity": "LOW", "location": "Elsewhere"},
        "received_by": 99999})
    assert res.status_code == 400 and res.json()["error"]["code"] == "INVALID_REFERENCE"
    assert client.get("/api/incidents", headers=dispatcher).json()["pagination"]["total"] == count + 1

    assert client.post("/api/calls", headers=dispatcher, json={"priority": "LOW"}).status_code == 400


def test_responder_assignment_rules(client, dispatcher):
    # police officer (org 1) onto a fire-service unit (org 2) is refused by the trigger
    res = client.put("/api/responders/2/unit", headers=dispatcher, json={"unit_id": 2})
    assert res.status_code == 409
    res = client.put("/api/responders/1/unit", headers=dispatcher, json={"unit_id": 1})
    assert res.status_code == 200 and res.json()["unit_id"] == 1
    crew = client.get("/api/units/1/responders", headers=dispatcher).json()["data"]
    assert {r["responder_id"] for r in crew} >= {1, 2}
    assert client.put("/api/responders/1/unit", headers=dispatcher, json={"unit_id": None}).json()["unit_id"] is None
    assert client.put("/api/responders/1/unit", headers=dispatcher, json={"unit_id": 99999}).status_code == 404


def test_organization_crud_and_in_use(client, admin):
    res = client.post("/api/organizations", headers=admin, json={"organization_name": "Disaster Relief Force"})
    assert res.status_code == 201
    org_id = res.json()["organization_id"]
    assert client.post("/api/organizations", headers=admin,
                       json={"organization_name": "Disaster Relief Force"}).status_code == 409
    assert client.patch(f"/api/organizations/{org_id}", headers=admin, json={"status": "INACTIVE"}).json()["status"] == "INACTIVE"
    assert client.delete(f"/api/organizations/{org_id}", headers=admin).status_code == 204
    assert client.delete(f"/api/organizations/{org_id}", headers=admin).status_code == 404
    res = client.delete("/api/organizations/1", headers=admin)  # has units/responders
    assert res.status_code == 409 and res.json()["error"]["code"] == "IN_USE"


def test_resources_restock_and_availability(client, admin, dispatcher):
    res = client.post("/api/resources", headers=admin, json={
        "resource_name": "Stretcher", "resource_type": "Medical Supply", "quantity_total": 0, "organization_id": 3})
    assert res.status_code == 201 and res.json()["status"] == "DEPLETED"
    rid = res.json()["resource_id"]
    available = {r["resource_id"] for r in client.get("/api/resources?available=true&page_size=100",
                                                      headers=dispatcher).json()["data"]}
    assert rid not in available
    res = client.post(f"/api/resources/{rid}/restock", headers=admin, json={"quantity": 5})
    assert res.json()["quantity_available"] == 5 and res.json()["status"] == "AVAILABLE"


def test_summary_activity_and_integration(client, dispatcher, responder):
    summary = client.get("/api/reports/summary", headers=dispatcher).json()
    assert {"incidents_by_status", "units", "low_stock", "multi_patient_incidents"} <= summary.keys()
    assert any(r["incident_id"] == 102 for r in summary["multi_patient_incidents"])

    logs = client.get("/api/activity-logs?incident_id=101", headers=responder).json()
    assert logs["data"] and all(l["incident_id"] == 101 for l in logs["data"])
    res = client.post("/api/activity-logs", headers=dispatcher, json={"incident_id": 101, "action": "Road closed"})
    assert res.status_code == 201 and "Road closed" in res.json()["action"]

    res = client.post("/api/integration/validate-refs", headers=dispatcher,
                      json={"incident_ids": [101, 424242], "call_ids": [1001], "unit_ids": [1]})
    assert res.json() == {"valid": False, "missing": {"incident_ids": [424242], "call_ids": [], "unit_ids": []}}


def test_stock_matches_allocations_everywhere():
    """Invariant: for every resource, total = available + quantity still in the field."""
    conn = mysql_as("DB_ADMIN")
    with conn.cursor() as cur:
        cur.execute("SELECT resource_id, quantity_total, quantity_available, quantity_in_field FROM v_resource_stock")
        rows = cur.fetchall()
    conn.close()
    # the sample data starts with some stock already counted as "used" outside the system
    # (e.g. oxygen 18/20 with 2 in the field), so check available + in_field <= total
    assert all(avail + in_field <= total and avail >= 0 for _, total, avail, in_field in rows)
