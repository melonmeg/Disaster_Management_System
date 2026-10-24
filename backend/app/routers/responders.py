"""/api/responders"""
from fastapi import APIRouter, Depends

from ..common import Page, paginated, require_row, updates_from
from ..db import Database
from ..errors import forbidden
from ..schemas import AssignUnitIn, Availability, AvailabilityIn, ResponderIn, ResponderUpdate
from ..security import CurrentUser, current_user, get_db, require_roles

router = APIRouter(prefix="/responders", tags=["responders"])

# Responders read the directory view (no e-mail); admins and dispatchers also see e-mail.
_DIRECTORY = "SELECT v.* FROM v_responder_directory v"
_DIRECTORY_WITH_EMAIL = ("SELECT v.*, r.email FROM v_responder_directory v "
                         "JOIN responders r ON r.responder_id = v.responder_id")


def _select(user: CurrentUser) -> str:
    return _DIRECTORY if user.role == "responder" else _DIRECTORY_WITH_EMAIL


def fetch_responder(db: Database, user: CurrentUser, responder_id: int) -> dict:
    return require_row(db, f"{_select(user)} WHERE v.responder_id = %s", (responder_id,), "Responder")


@router.get("")
def list_responders(organization_id: int | None = None, unit_id: int | None = None,
                    availability: Availability | None = None, responder_type: str | None = None,
                    page: Page = Depends(), user: CurrentUser = Depends(current_user),
                    db: Database = Depends(get_db)):
    where, params = [], []
    for column, value in (("v.organization_id", organization_id), ("v.unit_id", unit_id),
                          ("v.availability", availability), ("v.responder_type", responder_type)):
        if value is not None:
            where.append(f"{column} = %s"); params.append(value)
    return paginated(db, _select(user), where, params, page, "responder_id")


@router.get("/{responder_id}")
def get_responder(responder_id: int, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    return fetch_responder(db, user, responder_id)


@router.post("", status_code=201)
def create_responder(body: ResponderIn, user: CurrentUser = Depends(require_roles("admin")),
                     db: Database = Depends(get_db)):
    # trg_responders_before_insert rejects a unit from another organization
    new_id, _ = db.execute(
        "INSERT INTO responders (first_name, middle_name, last_name, phone, email, responder_type, "
        "availability, organization_id, unit_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (body.first_name, body.middle_name, body.last_name, body.phone, body.email, body.responder_type,
         body.availability, body.organization_id, body.unit_id))
    return fetch_responder(db, user, new_id)


@router.patch("/{responder_id}")
def update_responder(responder_id: int, body: ResponderUpdate, user: CurrentUser = Depends(require_roles("admin")),
                     db: Database = Depends(get_db)):
    fetch_responder(db, user, responder_id)
    changes = updates_from(body, {"first_name", "middle_name", "last_name", "phone", "email",
                                  "responder_type", "organization_id"})
    if changes:
        db.execute(f"UPDATE responders SET {', '.join(f'{k} = %s' for k in changes)} WHERE responder_id = %s",
                   [*changes.values(), responder_id])
    return fetch_responder(db, user, responder_id)


@router.put("/{responder_id}/unit")
def assign_unit(responder_id: int, body: AssignUnitIn,
                user: CurrentUser = Depends(require_roles("admin", "dispatcher")), db: Database = Depends(get_db)):
    """Assign, reassign (or with unit_id=null, unassign) a responder — via sp_assign_responder."""
    db.call("sp_assign_responder", (responder_id, body.unit_id))
    return fetch_responder(db, user, responder_id)


@router.patch("/{responder_id}/availability")
def set_availability(responder_id: int, body: AvailabilityIn, user: CurrentUser = Depends(current_user),
                     db: Database = Depends(get_db)):
    if user.role == "responder" and user.responder_id != responder_id:
        raise forbidden("Responders can only change their own availability")
    fetch_responder(db, user, responder_id)
    db.execute("UPDATE responders SET availability = %s WHERE responder_id = %s", (body.availability, responder_id))
    return fetch_responder(db, user, responder_id)
