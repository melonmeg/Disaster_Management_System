"""/api/units"""
from fastapi import APIRouter, Depends

from ..common import Page, paginated, require_row, updates_from
from ..db import Database
from ..schemas import UnitIn, UnitStatus, UnitUpdate
from ..security import CurrentUser, current_user, get_db, require_roles
from .responders import _select as responder_select

router = APIRouter(prefix="/units", tags=["units"], dependencies=[Depends(current_user)])

SELECT = "SELECT * FROM v_unit_availability"


def _fix(row: dict) -> dict:
    row["is_free"] = bool(row["is_free"])
    return row


def fetch_unit(db: Database, unit_id: int) -> dict:
    return _fix(require_row(db, f"{SELECT} WHERE unit_id = %s", (unit_id,), "Unit"))


@router.get("")
def list_units(status: UnitStatus | None = None, organization_id: int | None = None, unit_type: str | None = None,
               available: bool | None = None, page: Page = Depends(), db: Database = Depends(get_db)):
    """`available=true` returns units that can be dispatched right now (fn_unit_is_free)."""
    where, params = [], []
    for column, value in (("status", status), ("organization_id", organization_id), ("unit_type", unit_type)):
        if value is not None:
            where.append(f"{column} = %s"); params.append(value)
    if available is not None:
        where.append("is_free = %s"); params.append(int(available))
    result = paginated(db, SELECT, where, params, page, "unit_id")
    result["data"] = [_fix(r) for r in result["data"]]
    return result


@router.get("/{unit_id}")
def get_unit(unit_id: int, db: Database = Depends(get_db)):
    """Unit availability plus its current (active) assignments."""
    unit = fetch_unit(db, unit_id)
    unit["active_dispatches"] = db.all(
        "SELECT dispatch_id, dispatch_status, dispatched_at, incident_id, incident_type, severity, location, "
        "resources_outstanding FROM v_active_dispatches WHERE unit_id = %s ORDER BY dispatched_at DESC", (unit_id,))
    return unit


@router.get("/{unit_id}/responders")
def unit_responders(unit_id: int, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    fetch_unit(db, unit_id)
    return {"data": db.all(f"{responder_select(user)} WHERE v.unit_id = %s ORDER BY v.responder_id", (unit_id,))}


@router.get("/{unit_id}/dispatches")
def unit_dispatch_history(unit_id: int, page: Page = Depends(), db: Database = Depends(get_db)):
    fetch_unit(db, unit_id)
    return paginated(db, "SELECT d.*, i.incident_type, i.severity, i.location FROM dispatches d "
                         "JOIN incidents i ON i.incident_id = d.incident_id",
                     ["d.unit_id = %s"], [unit_id], page, "d.dispatched_at DESC")


@router.post("", status_code=201, dependencies=[Depends(require_roles("admin"))])
def create_unit(body: UnitIn, db: Database = Depends(get_db)):
    new_id, _ = db.execute(
        "INSERT INTO units (unit_name, unit_type, status, base_location, organization_id) VALUES (%s, %s, %s, %s, %s)",
        (body.unit_name, body.unit_type, body.status, body.base_location, body.organization_id))
    return fetch_unit(db, new_id)


@router.patch("/{unit_id}", dependencies=[Depends(require_roles("admin"))])
def update_unit(unit_id: int, body: UnitUpdate, db: Database = Depends(get_db)):
    fetch_unit(db, unit_id)
    changes = updates_from(body, {"unit_name", "unit_type", "status", "base_location"})
    if changes:
        db.execute(f"UPDATE units SET {', '.join(f'{k} = %s' for k in changes)} WHERE unit_id = %s",
                   [*changes.values(), unit_id])
    return fetch_unit(db, unit_id)
