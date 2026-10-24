"""Integration tests against a real MySQL test database.

The session starts by rebuilding TEST_DB_NAME (never DB_NAME) from the project SQL files,
so every run starts from the original sample data.
"""
import os
import sys
from pathlib import Path

import pymysql
import pytest
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND / ".env")
TEST_DB = os.environ.get("TEST_DB_NAME", "emergency_response_management_test")
os.environ["DB_NAME"] = TEST_DB  # must happen before the app is imported
sys.path.insert(0, str(BACKEND / "scripts"))

from create_test_db import rebuild_test_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def test_database():
    rebuild_test_db()
    yield TEST_DB


@pytest.fixture(scope="session")
def client(test_database):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def login(client, username, password):
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


def _headers(client, prefix):
    tokens = login(client, os.environ[f"{prefix}_USERNAME"], os.environ[f"{prefix}_PASSWORD"])
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return _headers(client, "SEED_ADMIN")


@pytest.fixture(scope="session")
def dispatcher(client):
    return _headers(client, "SEED_DISPATCHER")


@pytest.fixture(scope="session")
def responder(client):
    """Diya Nair (responder_id 2), member of Police Unit 12 (unit 1)."""
    return _headers(client, "SEED_RESPONDER")


def mysql_as(prefix: str):
    """Direct MySQL connection with one of the least-privilege accounts (DB_ADMIN, DB_RESPONDER, ...)."""
    return pymysql.connect(host=os.environ["DB_HOST"], port=int(os.environ.get("DB_PORT", 3306)),
                           user=os.environ[f"{prefix}_USER"], password=os.environ[f"{prefix}_PASSWORD"],
                           database=TEST_DB, autocommit=True)


@pytest.fixture
def free_unit(client, admin):
    """A brand-new AVAILABLE unit, so dispatch tests don't depend on sample-data state."""
    res = client.post("/api/units", headers=admin, json={
        "unit_name": "Test Rescue", "unit_type": "Rescue Vehicle", "base_location": "Test Base",
        "organization_id": 2})
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def open_incident(client, dispatcher):
    res = client.post("/api/incidents", headers=dispatcher, json={
        "incident_type": "Warehouse Fire", "severity": "HIGH", "location": "Plot 9, Industrial Area"})
    assert res.status_code == 201, res.text
    return res.json()
