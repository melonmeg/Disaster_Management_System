"""POST /api/users: create a login together with the person it belongs to, atomically."""
import pytest

from conftest import login, mysql_as


def _count(table):
    conn = mysql_as("DB_ADMIN")
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return cur.fetchone()[0]
    finally:
        conn.close()


def _post(client, admin, username, role, person=None, **extra):
    return client.post("/api/users", headers=admin, json={"username": username, "password": "Account#2026", "role": role,
                                                          **({"person": person} if person else {}), **extra})


def test_admin_account_needs_no_person(client, admin):
    res = _post(client, admin, "acct_admin1", "admin")
    assert res.status_code == 201 and res.json()["responder_id"] is None
    assert login(client, "acct_admin1", "Account#2026")["user"]["role"] == "admin"
    assert _post(client, admin, "acct_admin2", "admin", {"first_name": "A", "last_name": "B", "organization_id": 1}).status_code == 400


def test_dispatcher_is_created_with_person_and_can_log_calls(client, admin):
    res = _post(client, admin, "acct_disp1", "dispatcher",
                {"first_name": "Nisha", "last_name": "Rao", "phone": "9845099001", "email": "nisha.rao@example.com", "organization_id": 1})
    assert res.status_code == 201, res.text
    rid = res.json()["responder_id"]
    person = client.get(f"/api/responders/{rid}", headers=admin).json()
    assert person["responder_type"] == "Dispatcher" and person["organization_id"] == 1 and person["unit_id"] is None
    tokens = login(client, "acct_disp1", "Account#2026")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    call = client.post("/api/calls", headers=headers, json={"incident_id": 101, "caller_name": "Test"})
    assert call.status_code == 201 and call.json()["received_by"] == rid


def test_field_responder_with_organisation_and_unit(client, admin):
    res = _post(client, admin, "acct_resp1", "responder",
                {"first_name": "Kiran", "last_name": "Das", "responder_type": "Firefighter", "organization_id": 2, "unit_id": 2})
    assert res.status_code == 201, res.text
    person = client.get(f"/api/responders/{res.json()['responder_id']}", headers=admin).json()
    assert (person["organization_id"], person["unit_id"], person["responder_type"]) == (2, 2, "Firefighter")


@pytest.mark.parametrize("person, role, code", [
    ({"first_name": "No", "last_name": "Org", "responder_type": "Firefighter"}, "responder", 422),     # an organisation is required
    ({"first_name": "No", "last_name": "Type", "organization_id": 1}, "responder", 422),               # responders need a role
    ({"first_name": "Wrong", "last_name": "Unit", "responder_type": "Firefighter", "organization_id": 2, "unit_id": 1}, "responder", 409),
])
def test_invalid_person_creates_nothing(client, admin, person, role, code):
    users, responders = _count("app_users"), _count("responders")
    res = _post(client, admin, "acct_bad1", role, person)
    assert res.status_code == code, res.text
    assert (_count("app_users"), _count("responders")) == (users, responders)


def test_duplicate_username_rolls_back_the_new_person(client, admin):
    assert _post(client, admin, "acct_dup1", "admin").status_code == 201
    responders = _count("responders")
    res = _post(client, admin, "acct_dup1", "dispatcher", {"first_name": "Dup", "last_name": "User", "organization_id": 1})
    assert res.status_code == 409
    assert _count("responders") == responders          # the person was not left behind


def test_link_existing_person_or_new_but_not_both(client, admin):
    both = _post(client, admin, "acct_both", "responder", {"first_name": "A", "last_name": "B", "responder_type": "Paramedic", "organization_id": 3}, responder_id=4)
    neither = _post(client, admin, "acct_none", "responder")
    assert both.status_code == 400 and neither.status_code == 400
    assert _post(client, admin, "acct_link1", "responder", responder_id=5).status_code == 201


def test_only_admin_can_create_accounts(client, dispatcher, responder):
    for who in (dispatcher, responder):
        assert _post(client, who, "acct_nope", "admin").status_code == 403


def test_responder_login_edits_patients_only_on_their_units_incident(client, admin, dispatcher, free_unit, open_incident):
    created = _post(client, admin, "acct_resp_patients", "responder",
                    {"first_name": "Asha", "last_name": "Menon", "responder_type": "Paramedic",
                     "organization_id": free_unit["organization_id"], "unit_id": free_unit["unit_id"]})
    assert created.status_code == 201, created.text
    headers = {"Authorization": f"Bearer {login(client, 'acct_resp_patients', 'Account#2026')['access_token']}"}
    iid = open_incident["incident_id"]
    assert client.post(f"/api/incidents/{iid}/patients", headers=headers, json={"patient_name": "Early"}).status_code == 403   # not dispatched yet
    assert client.post("/api/dispatches", headers=dispatcher, json={"incident_id": iid, "unit_id": free_unit["unit_id"]}).status_code == 201
    patient = client.post(f"/api/incidents/{iid}/patients", headers=headers, json={"patient_name": "Ravi", "age": 30})
    assert patient.status_code == 201, patient.text
    no = patient.json()["patient_no"]
    edited = client.patch(f"/api/incidents/{iid}/patients/{no}", headers=headers, json={"patient_condition": "Conscious, minor burns"})
    assert edited.status_code == 200 and edited.json()["patient_condition"] == "Conscious, minor burns"
    assert client.delete(f"/api/incidents/{iid}/patients/{no}", headers=headers).status_code == 403          # delete stays admin only
    assert client.post("/api/incidents/101/patients", headers=headers, json={"patient_name": "Elsewhere"}).status_code == 403


def test_deactivating_an_account_removes_the_person_from_their_unit(client, admin):
    made = _post(client, admin, "acct_leaver", "responder",
                 {"first_name": "Leah", "last_name": "Verma", "responder_type": "Firefighter", "organization_id": 2, "unit_id": 2})
    assert made.status_code == 201, made.text
    uid, rid = made.json()["user_id"], made.json()["responder_id"]
    assert rid in {r["responder_id"] for r in client.get("/api/units/2/responders", headers=admin).json()["data"]}

    assert client.patch(f"/api/users/{uid}", headers=admin, json={"is_active": False}).status_code == 200
    person = client.get(f"/api/responders/{rid}", headers=admin).json()
    assert person["unit_id"] is None and person["availability"] == "OFF_DUTY" and person["full_name"] == "Leah Verma"
    assert rid not in {r["responder_id"] for r in client.get("/api/units/2/responders", headers=admin).json()["data"]}
    assert client.post("/api/auth/login", json={"username": "acct_leaver", "password": "Account#2026"}).status_code == 401

    assert client.patch(f"/api/users/{uid}", headers=admin, json={"is_active": True}).status_code == 200
    assert client.get(f"/api/responders/{rid}", headers=admin).json()["unit_id"] is None      # not put back automatically
    assert login(client, "acct_leaver", "Account#2026")["user"]["role"] == "responder"
