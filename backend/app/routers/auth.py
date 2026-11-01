"""/api/auth and /api/users — login, token refresh, logout, current user, user management."""
from fastapi import APIRouter, Depends, Response
from pydantic import ValidationError

from ..common import updates_from
from ..db import Database, open_db
from ..errors import ApiError, not_found
from ..schemas import AccountIn, LoginIn, RefreshIn, RegisterIn, ResponderIn, UserUpdate
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


@router.post("/users", status_code=201, dependencies=[Depends(require_roles("admin"))])
def create_account(body: AccountIn, db: Database = Depends(get_db)):
    """Create a login together with the person it belongs to, in one transaction (nothing is left half-created).

    admin: no person. dispatcher: person is saved as responder_type 'Dispatcher'. responder: person with a role/type;
    `responder_id` links an existing person instead of creating one."""
    if body.role == "admin":
        if body.person or body.responder_id:
            raise ApiError(400, "VALIDATION_ERROR", "Admin accounts are not linked to a responder record")
    elif (body.person is None) == (body.responder_id is None):
        raise ApiError(400, "VALIDATION_ERROR", "Send either `person` (new) or `responder_id` (existing) for this role")
    with db.transaction():
        responder_id = body.responder_id
        if body.person:
            data = body.person.model_dump()
            if body.role == "dispatcher":
                data["responder_type"] = "Dispatcher"
            elif not data["responder_type"]:
                raise ApiError(422, "VALIDATION_ERROR", "responder_type is required for a responder")
            if data["organization_id"] is None:
                raise ApiError(422, "VALIDATION_ERROR", "organization_id is required")
            try:
                p = ResponderIn(**data, availability="AVAILABLE")
            except ValidationError as exc:
                raise ApiError(422, "VALIDATION_ERROR", exc.errors()[0]["msg"].removeprefix("Value error, ")) from exc
            # trg_responders_before_insert rejects a unit from another organization
            responder_id, _ = db.execute(
                "INSERT INTO responders (first_name, middle_name, last_name, phone, email, responder_type, availability, "
                "organization_id, unit_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (p.first_name, p.middle_name, p.last_name, p.phone, p.email, p.responder_type, p.availability,
                 p.organization_id, p.unit_id))
        user_id, _ = db.execute(
            "INSERT INTO app_users (username, password_hash, role, responder_id) VALUES (%s, %s, %s, %s)",
            (body.username, hash_password(body.password), body.role, responder_id))
    return db.one(f"SELECT {PUBLIC_USER_COLUMNS} FROM app_users WHERE user_id = %s", (user_id,))


@router.get("/users", dependencies=[Depends(require_roles("admin"))])
def list_users(db: Database = Depends(get_db)):
    return {"data": db.all(f"SELECT {PUBLIC_USER_COLUMNS} FROM app_users ORDER BY user_id")}


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, admin: CurrentUser = Depends(require_roles("admin")),
                db: Database = Depends(get_db)):
    changes = updates_from(body, {"role", "responder_id", "is_active"})
    if user_id == admin.user_id and (changes.get("is_active") is False or changes.get("role", "admin") != "admin"):
        raise ApiError(400, "VALIDATION_ERROR", "You cannot deactivate or demote your own account")
    if body.password:
        changes["password_hash"] = hash_password(body.password)
    if not db.one("SELECT 1 FROM app_users WHERE user_id = %s", (user_id,)):
        raise not_found("User")
    if changes:
        sets = ", ".join(f"{k} = %s" for k in changes)
        with db.transaction():
            # any change to role/status/password ends the user's existing sessions
            db.execute(f"UPDATE app_users SET {sets}, token_version = token_version + 1 WHERE user_id = %s",
                       [*changes.values(), user_id])
            if changes.get("is_active") is False:
                # a deactivated person is taken off their unit's crew and marked off duty; calls, patients and
                # dispatch history keep pointing at them. Reactivating does not put them back on the unit.
                db.execute("UPDATE responders SET unit_id = NULL, availability = 'OFF_DUTY' WHERE responder_id = "
                           "(SELECT responder_id FROM app_users WHERE user_id = %s)", (user_id,))
    return db.one(f"SELECT {PUBLIC_USER_COLUMNS} FROM app_users WHERE user_id = %s", (user_id,))
