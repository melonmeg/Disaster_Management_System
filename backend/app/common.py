"""Small helpers shared by the routers: pagination, filters, ownership checks."""
from fastapi import Query

from .db import Database
from .errors import forbidden, not_found
from .security import CurrentUser


class Page:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
        self.page, self.page_size = page, page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def paginated(db: Database, select_sql: str, where: list[str], params: list, page: Page,
              order_by: str) -> dict:
    """Run `select_sql` with optional WHERE parts, ORDER BY and LIMIT; return data + pagination."""
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    total = db.scalar(f"SELECT COUNT(*) AS n FROM ({select_sql}{where_sql}) AS t", params)
    rows = db.all(f"{select_sql}{where_sql} ORDER BY {order_by} LIMIT %s OFFSET %s",
                  [*params, page.page_size, page.offset])
    return {
        "data": rows,
        "pagination": {
            "page": page.page,
            "page_size": page.page_size,
            "total": total,
            "total_pages": (total + page.page_size - 1) // page.page_size,
        },
    }


def require_row(db: Database, sql: str, params, what: str) -> dict:
    row = db.one(sql, params)
    if row is None:
        raise not_found(what)
    return row


def responder_unit(db: Database, user: CurrentUser) -> int | None:
    if user.responder_id is None:
        return None
    return db.scalar("SELECT unit_id FROM responders WHERE responder_id = %s", (user.responder_id,))


def ensure_responder_on_dispatch(db: Database, user: CurrentUser, dispatch_unit_id: int) -> None:
    """Responders may only act on dispatches of their own unit."""
    if user.role == "responder" and responder_unit(db, user) != dispatch_unit_id:
        raise forbidden("Responders can only act on dispatches of their own unit")


def ensure_responder_on_incident(db: Database, user: CurrentUser, incident_id: int) -> None:
    """Responders may only act on incidents their unit has been dispatched to."""
    if user.role != "responder":
        return
    unit_id = responder_unit(db, user)
    if unit_id is None or not db.one(
            "SELECT 1 FROM dispatches WHERE incident_id = %s AND unit_id = %s LIMIT 1", (incident_id, unit_id)):
        raise forbidden("Responders can only act on incidents their unit is dispatched to")


def updates_from(model, allowed: set[str]) -> dict:
    """Fields explicitly sent in a PATCH body."""
    return {k: v for k, v in model.model_dump(exclude_unset=True).items() if k in allowed}
