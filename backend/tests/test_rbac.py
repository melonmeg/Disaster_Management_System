"""Role-based access control: API layer (403 FORBIDDEN) and MySQL layer (privilege errors)."""
import pymysql
import pytest

from conftest import mysql_as


# ---------- application level ----------
@pytest.mark.parametrize("method, path, body", [
    ("post", "/api/incidents", {"incident_type": "X", "severity": "LOW", "location": "Y"}),
    ("get", "/api/calls", None),
    ("get", "/api/users", None),
    ("post", "/api/dispatches", {"incident_id": 102, "unit_id": 4}),
    ("post", "/api/dispatches/5003/resources", {"resource_id": 202, "quantity": 1}),
    ("post", "/api/organizations", {"organization_name": "X"}),
    ("put", "/api/responders/2/unit", {"unit_id": None}),
    ("get", "/api/reports/summary", None),
])
def test_responder_blocked(client, responder, method, path, body):
    res = getattr(client, method)(path, headers=responder, **({"json": body} if body else {}))
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("method, path, body", [
    ("post", "/api/organizations", {"organization_name": "New Org"}),
    ("delete", "/api/organizations/1", None),
    ("post", "/api/units", {"unit_name": "U", "organization_id": 1}),
    ("post", "/api/resources", {"resource_name": "R", "quantity_total": 1, "organization_id": 1}),
    ("delete", "/api/incidents/102/patients/1", None),
    ("post", "/api/auth/register", {"username": "x_user", "password": "Password#1", "role": "admin"}),
])
def test_dispatcher_blocked_from_admin_actions(client, dispatcher, method, path, body):
    res = getattr(client, method)(path, headers=dispatcher, **({"json": body} if body else {}))
    assert res.status_code == 403, res.text


def test_responder_permitted_actions(client, responder):
    assert client.get("/api/incidents", headers=responder).status_code == 200
    assert client.get("/api/units?available=true", headers=responder).status_code == 200
    assert client.get("/api/resources", headers=responder).status_code == 200
    # own availability: yes; somebody else's: no
    res = client.patch("/api/responders/2/availability", headers=responder, json={"availability": "ON_DUTY"})
    assert res.status_code == 200 and res.json()["availability"] == "ON_DUTY"
    assert client.patch("/api/responders/3/availability", headers=responder,
                        json={"availability": "OFF_DUTY"}).status_code == 403


def test_responder_cannot_touch_other_units_dispatch(client, responder):
    # dispatch 5001 belongs to Fire Engine 04; the responder is on Police Unit 12
    res = client.patch("/api/dispatches/5001/status", headers=responder, json={"status": "ON_SCENE"})
    assert res.status_code == 403
    # patients only for incidents their unit is dispatched to (101: no, 102: yes via dispatch 5003)
    assert client.post("/api/incidents/101/patients", headers=responder, json={"patient_name": "P"}).status_code == 403
    res = client.post("/api/incidents/102/patients", headers=responder,
                      json={"patient_name": "Patient E", "age": 25, "gender": "Female"})
    assert res.status_code == 201, res.text


def test_email_hidden_from_responder(client, responder, admin):
    assert all("email" not in r for r in client.get("/api/responders", headers=responder).json()["data"])
    assert all("email" in r for r in client.get("/api/responders", headers=admin).json()["data"])


# ---------- database level (MySQL privileges, independent of the API) ----------
def _denied(account, sql):
    conn = mysql_as(account)
    try:
        with conn.cursor() as cur:
            with pytest.raises(pymysql.MySQLError) as exc:
                cur.execute(sql)
        return exc.value.args[0]
    finally:
        conn.close()


@pytest.mark.parametrize("account, sql, errno", [
    ("DB_RESPONDER", "DELETE FROM incidents WHERE incident_id = 103", 1142),
    ("DB_RESPONDER", "SELECT * FROM calls", 1142),
    ("DB_RESPONDER", "SELECT email FROM responders", 1143),
    ("DB_RESPONDER", "UPDATE dispatches SET unit_id = 4 WHERE dispatch_id = 5003", 1143),
    ("DB_RESPONDER", "CALL sp_allocate_resource(5001, 202, 1)", 1370),
    ("DB_RESPONDER", "SELECT * FROM app_users", 1142),
    ("DB_DISPATCHER", "DELETE FROM calls WHERE call_id = 1001", 1142),
    ("DB_DISPATCHER", "SELECT * FROM app_users", 1142),
    ("DB_DISPATCHER", "INSERT INTO organizations (organization_name) VALUES ('X')", 1142),
    ("DB_ADMIN", "DROP TABLE calls", 1142),
    ("DB_AUTH", "SELECT * FROM incidents", 1142),
])
def test_mysql_privileges_deny(account, sql, errno):
    assert _denied(account, sql) == errno


def test_mysql_privileges_allow():
    conn = mysql_as("DB_RESPONDER")
    with conn.cursor() as cur:
        cur.execute("SELECT responder_id, availability FROM responders")
        assert cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM v_incident_overview")
        assert cur.fetchone()[0] >= 3
    conn.close()


def test_api_maps_db_permission_error_to_403(client, responder):
    """If an API check were missing, MySQL still refuses; the API reports it as 403, not 500."""
    from app.db import open_db
    from app.errors import mysql_error_response
    with open_db("responder") as db:
        with pytest.raises(pymysql.MySQLError) as exc:
            db.execute("DELETE FROM activity_logs")
    assert mysql_error_response(exc.value).status_code == 403
