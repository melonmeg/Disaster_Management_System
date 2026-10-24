"""/api/activity-logs, /api/reports and /api/integration."""
from datetime import datetime

from fastapi import APIRouter, Depends

from ..common import Page, ensure_responder_on_incident, paginated, require_row
from ..db import Database
from ..errors import forbidden
from ..schemas import ActivityIn, ValidateRefsIn
from ..security import CurrentUser, current_user, get_db, require_roles

router = APIRouter(tags=["activity & reports"])


# ---------- activity logs (written automatically by triggers; manual notes via POST) ----------
@router.get("/activity-logs")
def list_activity(incident_id: int | None = None, since: datetime | None = None, until: datetime | None = None,
                  page: Page = Depends(), _: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    where, params = [], []
    if incident_id is not None:
        where.append("a.incident_id = %s"); params.append(incident_id)
    if since:
        where.append("a.action_time >= %s"); params.append(since)
    if until:
        where.append("a.action_time <= %s"); params.append(until)
    return paginated(db, "SELECT a.log_id, a.incident_id, a.action, a.action_time, i.incident_type "
                         "FROM activity_logs a JOIN incidents i ON i.incident_id = a.incident_id",
                     where, params, page, "a.action_time DESC, a.log_id DESC")


@router.post("/activity-logs", status_code=201)
def add_activity(body: ActivityIn, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    require_row(db, "SELECT 1 FROM incidents WHERE incident_id = %s", (body.incident_id,), "Incident")
    ensure_responder_on_incident(db, user, body.incident_id)
    log_id, _ = db.execute("INSERT INTO activity_logs (incident_id, action) VALUES (%s, %s)",
                           (body.incident_id, f"[{user.username}] {body.action}"[:100]))
    return db.one("SELECT * FROM activity_logs WHERE log_id = %s", (log_id,))


# ---------- operational summary ----------
@router.get("/reports/summary", dependencies=[Depends(require_roles("admin", "dispatcher"))])
def summary(db: Database = Depends(get_db)):
    return {
        "incidents_by_status": db.all(
            "SELECT status, COUNT(*) AS count FROM incidents GROUP BY status ORDER BY count DESC"),
        "incidents_by_severity": db.all(
            "SELECT severity, COUNT(*) AS count, "
            "SUM(status IN ('OPEN', 'IN_PROGRESS')) AS unresolved FROM incidents GROUP BY severity "
            "ORDER BY FIELD(severity, 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW')"),
        "response_times": db.one(
            "SELECT ROUND(AVG(response_minutes), 1) AS avg_response_minutes, "
            "MAX(response_minutes) AS max_response_minutes FROM v_incident_overview "
            "WHERE response_minutes IS NOT NULL"),
        "units": db.one(
            "SELECT COUNT(*) AS total, SUM(is_free) AS free, SUM(NOT is_free) AS busy FROM v_unit_availability"),
        "dispatches_by_status": db.all("SELECT status, COUNT(*) AS count FROM dispatches GROUP BY status"),
        # resources where less than 25 % of stock is on hand
        "low_stock": db.all(
            "SELECT resource_id, resource_name, quantity_available, quantity_total FROM resources "
            "WHERE quantity_available < 0.25 * quantity_total ORDER BY quantity_available"),
        "multi_patient_incidents": db.all(
            "SELECT incident_id, COUNT(*) AS patient_count FROM incident_patients "
            "GROUP BY incident_id HAVING COUNT(*) > 1 ORDER BY patient_count DESC"),
    }


# ---------- integration with the MongoDB side ----------
_REF_TABLES = {
    "incident_ids": ("incidents", "incident_id"),
    "call_ids": ("calls", "call_id"),
    "dispatch_ids": ("dispatches", "dispatch_id"),
    "unit_ids": ("units", "unit_id"),
    "responder_ids": ("responders", "responder_id"),
}


@router.post("/integration/validate-refs")
def validate_refs(body: ValidateRefsIn, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    """MySQL cannot enforce foreign keys into MongoDB, so before saving a document that points
    at MySQL rows the Next.js/Mongo side asks here which ids exist."""
    if body.call_ids and user.role == "responder":
        raise forbidden("Responders cannot access call records")
    missing = {}
    for field, (table, column) in _REF_TABLES.items():
        ids = sorted(set(getattr(body, field)))
        if not ids:
            continue
        found = {r[column] for r in db.all(
            f"SELECT {column} FROM {table} WHERE {column} IN ({', '.join(['%s'] * len(ids))})", ids)}
        missing[field] = [i for i in ids if i not in found]
    return {"valid": not any(missing.values()), "missing": missing}
