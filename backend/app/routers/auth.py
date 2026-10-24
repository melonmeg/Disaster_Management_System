"""/api/auth and /api/users — login, token refresh, logout, current user, user management."""
from fastapi import APIRouter, Depends, Response

from ..common import updates_from
from ..db import Database, open_db
from ..errors import ApiError, not_found
from ..schemas import LoginIn, RefreshIn, RegisterIn, UserUpdate
from ..security import (CurrentUser, current_user, get_db, hash_password, require_roles, token_pair,
                        user_from_token, verify_password)

router = APIRouter(tags=["auth"])

PUBLIC_USER_COLUMNS = "user_id, username, role, responder_id, is_active, created_at, last_login_at"
# dummy hash so a login attempt for an unknown user costs the same time as a real one
_DUMMY_HASH = hash_password("timing-equaliser")


def _public(user: dict) -> dict:
    return {k: user[k] for k in ("user_id", "username", "role", "responder_id")}


@router.post("/auth/login")
def login(body: LoginIn):
    with open_db("auth") as db:
        user = db.one("SELECT user_id, username, password_hash, role, responder_id, is_active, token_version "
                      "FROM app_users WHERE username = %s", (body.username,))
        if not verify_password(body.password, user["password_hash"] if user else _DUMMY_HASH) \
                or not user or not user["is_active"]:
            raise ApiError(401, "INVALID_CREDENTIALS", "Invalid username or password")
        db.execute("UPDATE app_users SET last_login_at = NOW() WHERE user_id = %s", (user["user_id"],))
    return {**token_pair(user), "user": _public(user)}


@router.post("/auth/refresh")
def refresh(body: RefreshIn):
    user = user_from_token(body.refresh_token, "refresh")
    return {**token_pair(user), "user": _public(user)}


@router.post("/auth/logout", status_code=204)
def logout(user: CurrentUser = Depends(current_user)):
    # Bumping token_version invalidates every access and refresh token issued to this user.
    with open_db("auth") as db:
        db.execute("UPDATE app_users SET token_version = token_version + 1 WHERE user_id = %s", (user.user_id,))
    return Response(status_code=204)


@router.get("/auth/me")
def me(user: CurrentUser = Depends(current_user)):
    return {"user_id": user.user_id, "username": user.username, "role": user.role,
            "responder_id": user.responder_id}


# ---------- user management (admin only; registration is not public in an emergency system) ----------
@router.post("/auth/register", status_code=201, dependencies=[Depends(require_roles("admin"))])
def register(body: RegisterIn, db: Database = Depends(get_db)):
    if body.role == "responder" and body.responder_id is None:
        raise ApiError(400, "VALIDATION_ERROR", "responder_id is required for the responder role")
    user_id, _ = db.execute(
        "INSERT INTO app_users (username, password_hash, role, responder_id) VALUES (%s, %s, %s, %s)",
        (body.username, hash_password(body.password), body.role, body.responder_id))
    return db.one(f"SELECT {PUBLIC_USER_COLUMNS} FROM app_users WHERE user_id = %s", (user_id,))


@router.get("/users", dependencies=[Depends(require_roles("admin"))])
def list_users(db: Database = Depends(get_db)):
    return {"data": db.all(f"SELECT {PUBLIC_USER_COLUMNS} FROM app_users ORDER BY user_id")}


@router.patch("/users/{user_id}", dependencies=[Depends(require_roles("admin"))])
def update_user(user_id: int, body: UserUpdate, db: Database = Depends(get_db)):
    changes = updates_from(body, {"role", "responder_id", "is_active"})
    if body.password:
        changes["password_hash"] = hash_password(body.password)
    if not db.one("SELECT 1 FROM app_users WHERE user_id = %s", (user_id,)):
        raise not_found("User")
    if changes:
        sets = ", ".join(f"{k} = %s" for k in changes)
        # any change to role/status/password ends the user's existing sessions
        db.execute(f"UPDATE app_users SET {sets}, token_version = token_version + 1 WHERE user_id = %s",
                   [*changes.values(), user_id])
    return db.one(f"SELECT {PUBLIC_USER_COLUMNS} FROM app_users WHERE user_id = %s", (user_id,))
