"""/api/dispatches — dispatching units, the dispatch state machine and resource allocation."""
from fastapi import APIRouter, Depends

from ..common import Page, ensure_responder_on_dispatch, paginated, require_row
from ..db import Database
from ..errors import ApiError
from ..schemas import AllocationIn, DispatchIn, DispatchStatus, DispatchStatusIn, QuantityIn
from ..security import CurrentUser, current_user, get_db, require_roles

router = APIRouter(prefix="/dispatches", tags=["dispatches"])

SELECT = ("SELECT d.dispatch_id, d.incident_id, d.unit_id, d.status, d.dispatched_at, "
          "i.incident_type, i.severity, i.location, i.status AS incident_status, u.unit_name, u.unit_type "
          "FROM dispatches d JOIN incidents i ON i.incident_id = d.incident_id JOIN units u ON u.unit_id = d.unit_id")

# Same state machine as trg_dispatches_before_update; checked here too for a clear 409 message.
TRANSITIONS = {
    "DISPATCHED": {"EN_ROUTE", "ON_SCENE", "CANCELLED"},
    "EN_ROUTE": {"ON_SCENE", "CANCELLED"},
    "ON_SCENE": {"COMPLETED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


def fetch_dispatch(db: Database, dispatch_id: int) -> dict:
    dispatch = require_row(db, f"{SELECT} WHERE d.dispatch_id = %s", (dispatch_id,), "Dispatch")
    dispatch["resources"] = dispatch_resources_rows(db, dispatch_id)
    return dispatch


def dispatch_resources_rows(db: Database, dispatch_id: int) -> list[dict]:
    return db.all(
        "SELECT dr.dispatch_resource_id, dr.resource_id, r.resource_name, r.resource_type, dr.quantity_assigned, "
        "dr.quantity_returned, dr.quantity_assigned - dr.quantity_returned AS quantity_outstanding "
        "FROM dispatch_resources dr JOIN resources r ON r.resource_id = dr.resource_id "
        "WHERE dr.dispatch_id = %s ORDER BY r.resource_name", (dispatch_id,))


@router.get("")
def list_dispatches(status: DispatchStatus | None = None, incident_id: int | None = None, unit_id: int | None = None,
                    active: bool | None = None, page: Page = Depends(), _: CurrentUser = Depends(current_user),
                    db: Database = Depends(get_db)):
    """Dispatch history, newest first. `active=true` = not COMPLETED/CANCELLED."""
    where, params = [], []
    for column, value in (("d.status", status), ("d.incident_id", incident_id), ("d.unit_id", unit_id)):
        if value is not None:
            where.append(f"{column} = %s"); params.append(value)
    if active is not None:
        where.append(f"d.status {'NOT ' if active else ''}IN ('COMPLETED', 'CANCELLED')")
    return paginated(db, SELECT, where, params, page, "d.dispatched_at DESC, d.dispatch_id DESC")


@router.get("/{dispatch_id}")
def get_dispatch(dispatch_id: int, _: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    return fetch_dispatch(db, dispatch_id)


@router.post("", status_code=201, dependencies=[Depends(require_roles("admin", "dispatcher"))])
def create_dispatch(body: DispatchIn, db: Database = Depends(get_db)):
    """sp_create_dispatch validates incident/unit, locks them, inserts and (via trigger) marks the unit busy."""
    *_, dispatch_id = db.call("sp_create_dispatch", (body.incident_id, body.unit_id, 0))
    return fetch_dispatch(db, dispatch_id)


@router.patch("/{dispatch_id}/status")
def update_status(dispatch_id: int, body: DispatchStatusIn, user: CurrentUser = Depends(current_user),
                  db: Database = Depends(get_db)):
    dispatch = require_row(db, "SELECT unit_id, status FROM dispatches WHERE dispatch_id = %s",
                           (dispatch_id,), "Dispatch")
    ensure_responder_on_dispatch(db, user, dispatch["unit_id"])
    if body.status != dispatch["status"] and body.status not in TRANSITIONS[dispatch["status"]]:
        allowed = sorted(TRANSITIONS[dispatch["status"]])
        raise ApiError(409, "INVALID_TRANSITION",
                       f"Cannot change dispatch from {dispatch['status']} to {body.status}",
                       {"allowed": allowed})
    db.execute("UPDATE dispatches SET status = %s WHERE dispatch_id = %s", (body.status, dispatch_id))
    return fetch_dispatch(db, dispatch_id)


@router.get("/{dispatch_id}/resources")
def list_dispatch_resources(dispatch_id: int, _: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    require_row(db, "SELECT 1 FROM dispatches WHERE dispatch_id = %s", (dispatch_id,), "Dispatch")
    return {"data": dispatch_resources_rows(db, dispatch_id)}


@router.post("/{dispatch_id}/resources", status_code=201,
             dependencies=[Depends(require_roles("admin", "dispatcher"))])
def allocate_resource(dispatch_id: int, body: AllocationIn, db: Database = Depends(get_db)):
    """sp_allocate_resource locks the stock row; over-allocation is rejected with 409."""
    db.call("sp_allocate_resource", (dispatch_id, body.resource_id, body.quantity))
    return fetch_dispatch(db, dispatch_id)


@router.post("/{dispatch_id}/resources/{resource_id}/return")
def return_resource(dispatch_id: int, resource_id: int, body: QuantityIn, user: CurrentUser = Depends(current_user),
                    db: Database = Depends(get_db)):
    dispatch = require_row(db, "SELECT unit_id FROM dispatches WHERE dispatch_id = %s", (dispatch_id,), "Dispatch")
    ensure_responder_on_dispatch(db, user, dispatch["unit_id"])
    db.call("sp_return_resource", (dispatch_id, resource_id, body.quantity))
    return fetch_dispatch(db, dispatch_id)
