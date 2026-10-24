"""/api/incidents"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from ..common import Page, paginated, require_row, updates_from
from ..db import Database
from ..errors import forbidden
from ..schemas import IncidentIn, IncidentStatus, IncidentUpdate, Severity
from ..security import CurrentUser, current_user, get_db, require_roles

router = APIRouter(prefix="/incidents", tags=["incidents"])

SELECT = "SELECT * FROM v_incident_overview"
SORTS = {"newest": "created_at DESC", "oldest": "created_at ASC",
         "severity": "FIELD(severity, 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'), created_at DESC"}


def fetch_incident(db: Database, incident_id: int) -> dict:
    return require_row(db, f"{SELECT} WHERE incident_id = %s", (incident_id,), "Incident")


@router.get("")
def list_incidents(status: list[IncidentStatus] | None = Query(None), severity: list[Severity] | None = Query(None),
                   location: str | None = Query(None, max_length=100, description="substring match"),
                   incident_type: str | None = None, unresolved: bool | None = None,
                   created_from: datetime | None = None, created_to: datetime | None = None,
                   sort: str = Query("newest", pattern="^(newest|oldest|severity)$"),
                   page: Page = Depends(), _: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    """Filter by status/severity (repeatable), location, type, date range; `unresolved=true` = OPEN or IN_PROGRESS."""
    where, params = [], []
    if status:
        where.append(f"status IN ({', '.join(['%s'] * len(status))})"); params += status
    if severity:
        where.append(f"severity IN ({', '.join(['%s'] * len(severity))})"); params += severity
    if location:
        where.append("location LIKE %s"); params.append(f"%{location}%")
    if incident_type:
        where.append("incident_type = %s"); params.append(incident_type)
    if unresolved is not None:
        where.append("status IN ('OPEN', 'IN_PROGRESS')" if unresolved else "status IN ('RESOLVED', 'CLOSED')")
    if created_from:
        where.append("created_at >= %s"); params.append(created_from)
    if created_to:
        where.append("created_at <= %s"); params.append(created_to)
    return paginated(db, SELECT, where, params, page, SORTS[sort])


@router.get("/{incident_id}")
def get_incident(incident_id: int, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    """Incident with its dispatches (unit + crew) and patients."""
    incident = fetch_incident(db, incident_id)
    incident["dispatches"] = incident_dispatches(incident_id, user, db)["data"]
    incident["patients"] = db.all("SELECT * FROM incident_patients WHERE incident_id = %s ORDER BY patient_no",
                                  (incident_id,))
    return incident


@router.get("/{incident_id}/dispatches")
def incident_dispatches(incident_id: int, _: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    fetch_incident(db, incident_id)
    rows = db.all(
        "SELECT d.dispatch_id, d.status, d.dispatched_at, u.unit_id, u.unit_name, u.unit_type, o.organization_name, "
        "  (SELECT GROUP_CONCAT(CONCAT_WS(' ', r.first_name, r.last_name) ORDER BY r.responder_id SEPARATOR ', ') "
        "     FROM responders r WHERE r.unit_id = u.unit_id) AS crew, "
        "  fn_outstanding_quantity(d.dispatch_id) AS resources_outstanding "
        "FROM dispatches d JOIN units u ON u.unit_id = d.unit_id "
        "JOIN organizations o ON o.organization_id = u.organization_id "
        "WHERE d.incident_id = %s ORDER BY d.dispatched_at", (incident_id,))
    return {"data": rows}


@router.get("/{incident_id}/calls")
def incident_calls(incident_id: int, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    if user.role == "responder":
        raise forbidden("Responders cannot view call records")
    fetch_incident(db, incident_id)
    return {"data": db.all("SELECT * FROM calls WHERE incident_id = %s ORDER BY received_at", (incident_id,))}


@router.get("/{incident_id}/activity")
def incident_activity(incident_id: int, _: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    fetch_incident(db, incident_id)
    return {"data": db.all("SELECT * FROM activity_logs WHERE incident_id = %s ORDER BY action_time, log_id",
                           (incident_id,))}


@router.post("", status_code=201, dependencies=[Depends(require_roles("admin", "dispatcher"))])
def create_incident(body: IncidentIn, db: Database = Depends(get_db)):
    new_id, _ = db.execute("INSERT INTO incidents (incident_type, severity, location) VALUES (%s, %s, %s)",
                           (body.incident_type, body.severity, body.location))
    return fetch_incident(db, new_id)


@router.patch("/{incident_id}", dependencies=[Depends(require_roles("admin", "dispatcher"))])
def update_incident(incident_id: int, body: IncidentUpdate, db: Database = Depends(get_db)):
    """Edit details or change status. Transitions are validated by trg_incidents_before_update;
    status RESOLVED goes through sp_resolve_incident (also checks that resources are returned)."""
    fetch_incident(db, incident_id)
    changes = updates_from(body, {"incident_type", "severity", "location", "status"})
    if changes.get("status") == "RESOLVED":
        changes.pop("status")
        resolve = True
    else:
        resolve = False
    with db.transaction():
        if changes:
            db.execute(f"UPDATE incidents SET {', '.join(f'{k} = %s' for k in changes)} WHERE incident_id = %s",
                       [*changes.values(), incident_id])
    if resolve:
        db.call("sp_resolve_incident", (incident_id,))
    return fetch_incident(db, incident_id)


@router.post("/{incident_id}/resolve", dependencies=[Depends(require_roles("admin", "dispatcher"))])
def resolve_incident(incident_id: int, db: Database = Depends(get_db)):
    db.call("sp_resolve_incident", (incident_id,))
    return fetch_incident(db, incident_id)
