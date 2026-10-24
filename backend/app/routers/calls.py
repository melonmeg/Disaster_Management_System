"""/api/calls — emergency call records (MySQL `calls` table). Not available to responders.

The structured call row (caller, priority, incident link) lives in MySQL. Rich, unstructured
data about a call (audio metadata, transcript segments, NLP tags) belongs to the MongoDB side;
those documents reference `call_id` / `incident_id` from here (see docs/API.md, "Integration").
"""
from datetime import datetime

from fastapi import APIRouter, Depends

from ..common import Page, paginated, require_row, updates_from
from ..db import Database
from ..errors import ApiError
from ..schemas import CallIn, CallStatus, CallUpdate, Severity
from ..security import CurrentUser, get_db, require_roles

router = APIRouter(prefix="/calls", tags=["calls"])
staff = require_roles("admin", "dispatcher")

SELECT = ("SELECT c.*, CONCAT_WS(' ', r.first_name, r.last_name) AS received_by_name "
          "FROM calls c JOIN responders r ON r.responder_id = c.received_by")


def fetch_call(db: Database, call_id: int) -> dict:
    return require_row(db, f"{SELECT} WHERE c.call_id = %s", (call_id,), "Call")


@router.get("")
def list_calls(incident_id: int | None = None, status: CallStatus | None = None, priority: Severity | None = None,
               received_from: datetime | None = None, received_to: datetime | None = None,
               page: Page = Depends(), _: CurrentUser = Depends(staff), db: Database = Depends(get_db)):
    where, params = [], []
    for column, value in (("c.incident_id", incident_id), ("c.status", status), ("c.priority", priority)):
        if value is not None:
            where.append(f"{column} = %s"); params.append(value)
    if received_from:
        where.append("c.received_at >= %s"); params.append(received_from)
    if received_to:
        where.append("c.received_at <= %s"); params.append(received_to)
    return paginated(db, SELECT, where, params, page, "c.received_at DESC, c.call_id DESC")


@router.get("/{call_id}")
def get_call(call_id: int, _: CurrentUser = Depends(staff), db: Database = Depends(get_db)):
    return fetch_call(db, call_id)


@router.post("", status_code=201)
def create_call(body: CallIn, user: CurrentUser = Depends(staff), db: Database = Depends(get_db)):
    """Log a call against an existing incident (`incident_id`) or open a new incident
    (`incident`) and the call in ONE transaction: if the call insert fails, the incident is rolled back."""
    if (body.incident_id is None) == (body.incident is None):
        raise ApiError(400, "VALIDATION_ERROR", "Send exactly one of incident_id or incident")
    received_by = body.received_by or user.responder_id
    if received_by is None:
        raise ApiError(400, "VALIDATION_ERROR", "received_by is required (your login has no responder record)")

    with db.transaction():
        incident_id = body.incident_id
        if body.incident is not None:
            incident_id, _ = db.execute(
                "INSERT INTO incidents (incident_type, severity, location) VALUES (%s, %s, %s)",
                (body.incident.incident_type, body.incident.severity, body.incident.location))
        elif db.one("SELECT status FROM incidents WHERE incident_id = %s", (incident_id,)) is None:
            raise ApiError(400, "INVALID_REFERENCE", f"Incident {incident_id} does not exist")
        call_id, _ = db.execute(
            "INSERT INTO calls (received_by, status, transcript, caller_name, priority, caller_phone, location, "
            "incident_id) VALUES (%s, 'RECEIVED', %s, %s, %s, %s, %s, %s)",
            (received_by, body.transcript, body.caller_name, body.priority, body.caller_phone,
             body.location or (body.incident.location if body.incident else None), incident_id))
    return fetch_call(db, call_id)


@router.patch("/{call_id}")
def update_call(call_id: int, body: CallUpdate, _: CurrentUser = Depends(staff), db: Database = Depends(get_db)):
    fetch_call(db, call_id)
    changes = updates_from(body, {"status", "priority", "transcript"})
    if changes:
        db.execute(f"UPDATE calls SET {', '.join(f'{k} = %s' for k in changes)} WHERE call_id = %s",
                   [*changes.values(), call_id])
    return fetch_call(db, call_id)
