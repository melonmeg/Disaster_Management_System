import os

from conftest import login


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_login_success_returns_tokens_without_secrets(client):
    body = login(client, os.environ["SEED_ADMIN_USERNAME"], os.environ["SEED_ADMIN_PASSWORD"])
    assert body["token_type"] == "bearer" and body["access_token"] and body["refresh_token"]
    assert body["user"]["role"] == "admin"
    assert "password_hash" not in str(body)


def test_login_wrong_password_and_unknown_user(client):
    for username, password in ((os.environ["SEED_ADMIN_USERNAME"], "wrong-password"), ("nobody", "x")):
        res = client.post("/api/auth/login", json={"username": username, "password": password})
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_protected_route_requires_valid_token(client):
    assert client.get("/api/incidents").status_code == 401
    res = client.get("/api/incidents", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401 and res.json()["error"]["code"] == "UNAUTHORIZED"


def test_me(client, responder):
    me = client.get("/api/auth/me", headers=responder).json()
    assert me["role"] == "responder" and me["responder_id"] == 2


def test_refresh_and_token_types(client):
    tokens = login(client, os.environ["SEED_DISPATCHER_USERNAME"], os.environ["SEED_DISPATCHER_PASSWORD"])
    res = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert res.status_code == 200 and res.json()["access_token"]
    # an access token is not accepted as a refresh token, and vice versa
    assert client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401
    assert client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {tokens['refresh_token']}"}).status_code == 401


def test_register_logout_and_deactivate(client, admin, dispatcher):
    new_user = {"username": "kabir", "password": "Firefighter#2026", "role": "responder", "responder_id": 3}
    assert client.post("/api/auth/register", headers=dispatcher, json=new_user).status_code == 403

    res = client.post("/api/auth/register", headers=admin, json=new_user)
    assert res.status_code == 201
    assert "password" not in str(res.json())
    user_id = res.json()["user_id"]

    assert client.post("/api/auth/register", headers=admin, json=new_user).json()["error"]["code"] == "DUPLICATE"
    res = client.post("/api/auth/register", headers=admin,
                      json={"username": "nolink", "password": "Password#123", "role": "responder"})
    assert res.status_code == 400
    res = client.post("/api/auth/register", headers=admin,
                      json={"username": "short", "password": "123", "role": "admin"})
    assert res.status_code == 422 and res.json()["error"]["details"][0]["field"] == "password"

    # logout invalidates both the access and the refresh token
    tokens = login(client, "kabir", "Firefighter#2026")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401

    # deactivated users cannot log in
    assert client.patch(f"/api/users/{user_id}", headers=admin, json={"is_active": False}).status_code == 200
    assert client.post("/api/auth/login",
                       json={"username": "kabir", "password": "Firefighter#2026"}).status_code == 401


def test_password_is_stored_as_bcrypt_hash(client, admin):
    from conftest import mysql_as
    conn = mysql_as("DB_ADMIN")
    with conn.cursor() as cur:
        cur.execute("SELECT password_hash FROM app_users WHERE username = %s", (os.environ["SEED_ADMIN_USERNAME"],))
        stored = cur.fetchone()[0]
    conn.close()
    assert stored.startswith("$2") and os.environ["SEED_ADMIN_PASSWORD"] not in stored
