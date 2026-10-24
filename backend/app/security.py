"""Password hashing, JWT tokens and the per-request auth dependencies."""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .db import Database, connect, open_db
from .errors import ApiError, forbidden

ROLES = ("admin", "dispatcher", "responder")
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    username: str
    role: str
    responder_id: int | None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(user: dict, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    lifetime = (timedelta(minutes=settings.access_token_minutes) if token_type == "access"
                else timedelta(days=settings.refresh_token_days))
    payload = {
        "sub": str(user["user_id"]),
        "role": user["role"],
        "ver": user["token_version"],   # must match app_users.token_version
        "type": token_type,
        "iat": now,
        "exp": now + lifetime,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def token_pair(user: dict) -> dict:
    return {
        "access_token": create_token(user, "access"),
        "refresh_token": create_token(user, "refresh"),
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
    }


def _unauthorized(message: str) -> ApiError:
    return ApiError(401, "UNAUTHORIZED", message)


def user_from_token(token: str, expected_type: str) -> dict:
    """Validate a token and return the live app_users row (checked against the DB
    so logout, deactivation and role changes take effect immediately)."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token has expired")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid token")
    if payload.get("type") != expected_type:
        raise _unauthorized("Wrong token type")
    with open_db("auth") as db:
        user = db.one(
            "SELECT user_id, username, role, responder_id, is_active, token_version "
            "FROM app_users WHERE user_id = %s", (int(payload["sub"]),))
    if not user or not user["is_active"] or user["token_version"] != payload.get("ver"):
        raise _unauthorized("Session is no longer valid; please log in again")
    return user


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Missing bearer token")
    user = user_from_token(credentials.credentials, "access")
    return CurrentUser(user["user_id"], user["username"], user["role"], user["responder_id"])


def require_roles(*roles: str):
    """Dependency: allow only the given application roles."""
    def checker(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in roles:
            raise forbidden(f"Requires role: {', '.join(roles)}")
        return user
    return checker


def get_db(user: CurrentUser = Depends(current_user)):
    """Database connection using the MySQL account mapped to the caller's role."""
    conn = connect(user.role)
    try:
        yield Database(conn)
    finally:
        conn.close()
