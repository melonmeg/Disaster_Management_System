"""Operational log in MongoDB (collection `operational_logs`): one document per API request worth keeping.

Logged: every request that changes data (anything but GET/HEAD/OPTIONS) and every failed request (HTTP >= 400).
Successful reads are skipped, so the 30-second dashboard polling does not flood the collection.
Stored: time, method, path, route template, status, duration, caller id/role (from the token), client IP, request id.
Never stored: request or response bodies, query strings, passwords, tokens, or the contents of recordings.

Best effort by design: the log must never break or slow down the API. If MongoDB is down the entry is dropped
(with a warning in the process log) and writes are not retried for RETRY_AFTER seconds. Entries expire after
OPLOG_RETENTION_DAYS (TTL index). MySQL `activity_logs` (incident timeline, written by triggers) is separate.
"""
import logging
import time
import uuid
from datetime import datetime

import jwt
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import PyMongoError

from .config import settings
from .recommendation.store import get_mongo_db, now

log = logging.getLogger("erm.oplog")
COLLECTION = "operational_logs"
RETRY_AFTER = 30.0
SKIP_PATHS = {"/api/health"}
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def should_log(method: str, path: str, status: int) -> bool:
    if not path.startswith("/api/") or path in SKIP_PATHS:
        return False
    return method.upper() not in READ_METHODS or status >= 400


def caller_from_authorization(header: str | None) -> tuple[int | None, str | None]:
    """Who the bearer token says the caller is. The signature is checked; expiry and the DB session are not
    (this is for the log only, the request itself was already authorised or rejected by the API)."""
    if not header or not header.lower().startswith("bearer "):
        return None, None
    try:
        payload = jwt.decode(header[7:].strip(), settings.jwt_secret, algorithms=["HS256"], options={"verify_exp": False})
        return int(payload["sub"]), payload.get("role")
    except (jwt.PyJWTError, KeyError, ValueError):
        return None, None


class OpLogStore:
    def __init__(self, database, retention_days: int | None = None):
        self.col = database[COLLECTION]
        self.retention_days = retention_days if retention_days is not None else settings.oplog_retention_days
        self._down_until = 0.0
        self._indexed = False

    def ensure_indexes(self) -> None:
        self.col.create_index([("ts", DESCENDING)], expireAfterSeconds=max(1, self.retention_days) * 86400)
        self.col.create_index([("user_id", ASCENDING), ("ts", DESCENDING)])
        self.col.create_index([("status", ASCENDING), ("ts", DESCENDING)])
        self.col.create_index("request_id")
        self._indexed = True

    def record(self, entry: dict) -> bool:
        """Insert one entry; returns False (never raises) if it could not be stored."""
        if time.monotonic() < self._down_until:
            return False
        try:
            if not self._indexed:
                self.ensure_indexes()
            self.col.insert_one(entry)
            return True
        except PyMongoError as exc:
            self._down_until = time.monotonic() + RETRY_AFTER
            log.warning("Operational log (MongoDB) unavailable, entries dropped for %ss: %s", int(RETRY_AFTER), type(exc).__name__)
            return False

    def search(self, *, user_id=None, method=None, status_min=None, status_max=None, path_prefix=None,
               since: datetime | None = None, until: datetime | None = None, page=1, page_size=50) -> dict:
        import re
        q: dict = {}
        if user_id is not None:
            q["user_id"] = user_id
        if method:
            q["method"] = method.upper()
        if status_min is not None or status_max is not None:
            q["status"] = {**({"$gte": status_min} if status_min is not None else {}),
                           **({"$lte": status_max} if status_max is not None else {})}
        if path_prefix:
            q["path"] = {"$regex": "^" + re.escape(path_prefix)}
        if since or until:
            q["ts"] = {**({"$gte": since} if since else {}), **({"$lte": until} if until else {})}
        total = self.col.count_documents(q)
        rows = list(self.col.find(q, {"_id": 0}).sort([("ts", -1), ("_id", -1)]).skip((page - 1) * page_size).limit(page_size))
        return {"data": rows, "pagination": {"page": page, "page_size": page_size, "total": total,
                                             "total_pages": (total + page_size - 1) // page_size}}


_store: OpLogStore | None = None


def get_oplog() -> OpLogStore | None:
    """The shared log store, or None when OPLOG_ENABLED=false. Tests replace this function."""
    global _store
    if not settings.oplog_enabled:
        return None
    if _store is None:
        _store = OpLogStore(get_mongo_db())
    return _store


def make_entry(*, method: str, path: str, route: str | None, status: int, duration_ms: float,
               authorization: str | None, client_ip: str | None) -> dict:
    user_id, role = caller_from_authorization(authorization)
    return {"ts": now(), "request_id": uuid.uuid4().hex, "level": "ERROR" if status >= 500 else "WARNING" if status >= 400 else "INFO",
            "method": method.upper(), "path": path, "route": route, "status": status, "duration_ms": round(duration_ms, 1),
            "user_id": user_id, "role": role, "client_ip": client_ip}
