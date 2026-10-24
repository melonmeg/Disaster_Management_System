"""/api/resources — stock levels; allocation/return lives under /api/dispatches."""
from fastapi import APIRouter, Depends

from ..common import Page, paginated, require_row, updates_from
from ..db import Database
from ..schemas import QuantityIn, ResourceIn, ResourceStatus, ResourceUpdate
from ..security import current_user, get_db, require_roles

router = APIRouter(prefix="/resources", tags=["resources"], dependencies=[Depends(current_user)])

SELECT = "SELECT * FROM v_resource_stock"


def fetch_resource(db: Database, resource_id: int) -> dict:
    return require_row(db, f"{SELECT} WHERE resource_id = %s", (resource_id,), "Resource")


@router.get("")
def list_resources(resource_type: str | None = None, organization_id: int | None = None,
                   status: ResourceStatus | None = None, available: bool | None = None,
                   page: Page = Depends(), db: Database = Depends(get_db)):
    """`available=true` = stock on hand and not marked UNAVAILABLE."""
    where, params = [], []
    for column, value in (("resource_type", resource_type), ("organization_id", organization_id),
                          ("status", status)):
        if value is not None:
            where.append(f"{column} = %s"); params.append(value)
    if available:
        where.append("quantity_available > 0 AND status <> 'UNAVAILABLE'")
    elif available is False:
        where.append("(quantity_available = 0 OR status = 'UNAVAILABLE')")
    return paginated(db, SELECT, where, params, page, "resource_id")


@router.get("/{resource_id}")
def get_resource(resource_id: int, db: Database = Depends(get_db)):
    """Stock plus the dispatches currently holding this resource."""
    resource = fetch_resource(db, resource_id)
    resource["allocations"] = db.all(
        "SELECT dr.dispatch_id, d.incident_id, d.status AS dispatch_status, dr.quantity_assigned, "
        "dr.quantity_returned, dr.quantity_assigned - dr.quantity_returned AS quantity_outstanding "
        "FROM dispatch_resources dr JOIN dispatches d ON d.dispatch_id = dr.dispatch_id "
        "WHERE dr.resource_id = %s AND dr.quantity_assigned > dr.quantity_returned ORDER BY dr.dispatch_id",
        (resource_id,))
    return resource


@router.post("", status_code=201, dependencies=[Depends(require_roles("admin"))])
def create_resource(body: ResourceIn, db: Database = Depends(get_db)):
    new_id, _ = db.execute(
        "INSERT INTO resources (resource_name, resource_type, quantity_total, quantity_available, status, location, "
        "organization_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (body.resource_name, body.resource_type, body.quantity_total, body.quantity_total,
         "AVAILABLE" if body.quantity_total > 0 else "DEPLETED", body.location, body.organization_id))
    return fetch_resource(db, new_id)


@router.patch("/{resource_id}", dependencies=[Depends(require_roles("admin"))])
def update_resource(resource_id: int, body: ResourceUpdate, db: Database = Depends(get_db)):
    current = fetch_resource(db, resource_id)
    changes = updates_from(body, {"resource_name", "resource_type", "location", "status"})
    if changes.get("status") == "AVAILABLE" and current["quantity_available"] == 0:
        changes["status"] = "DEPLETED"
    if changes:
        db.execute(f"UPDATE resources SET {', '.join(f'{k} = %s' for k in changes)} WHERE resource_id = %s",
                   [*changes.values(), resource_id])
    return fetch_resource(db, resource_id)


@router.post("/{resource_id}/restock", dependencies=[Depends(require_roles("admin"))])
def restock(resource_id: int, body: QuantityIn, db: Database = Depends(get_db)):
    """Add newly purchased stock: total and available both increase."""
    fetch_resource(db, resource_id)
    db.execute("UPDATE resources SET quantity_total = quantity_total + %s, "
               "quantity_available = quantity_available + %s, "
               "status = IF(status = 'DEPLETED', 'AVAILABLE', status) WHERE resource_id = %s",
               (body.quantity, body.quantity, resource_id))
    return fetch_resource(db, resource_id)
