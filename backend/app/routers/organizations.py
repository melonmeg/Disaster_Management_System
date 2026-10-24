"""/api/organizations"""
from fastapi import APIRouter, Depends, Response

from ..common import Page, paginated, require_row, updates_from
from ..db import Database
from ..schemas import OrganizationIn, OrganizationUpdate, OrgStatus
from ..security import current_user, get_db, require_roles

router = APIRouter(prefix="/organizations", tags=["organizations"], dependencies=[Depends(current_user)])

SELECT = ("SELECT o.organization_id, o.organization_name, o.location, o.status, "
          "(SELECT COUNT(*) FROM units u WHERE u.organization_id = o.organization_id) AS unit_count, "
          "(SELECT COUNT(*) FROM resources r WHERE r.organization_id = o.organization_id) AS resource_count "
          "FROM organizations o")


@router.get("")
def list_organizations(status: OrgStatus | None = None, page: Page = Depends(), db: Database = Depends(get_db)):
    where, params = [], []
    if status:
        where.append("o.status = %s"); params.append(status)
    return paginated(db, SELECT, where, params, page, "organization_id")


@router.get("/{organization_id}")
def get_organization(organization_id: int, db: Database = Depends(get_db)):
    return require_row(db, f"{SELECT} WHERE o.organization_id = %s", (organization_id,), "Organization")


@router.post("", status_code=201, dependencies=[Depends(require_roles("admin"))])
def create_organization(body: OrganizationIn, db: Database = Depends(get_db)):
    new_id, _ = db.execute("INSERT INTO organizations (organization_name, location, status) VALUES (%s, %s, %s)",
                           (body.organization_name, body.location, body.status))
    return get_organization(new_id, db)


@router.patch("/{organization_id}", dependencies=[Depends(require_roles("admin"))])
def update_organization(organization_id: int, body: OrganizationUpdate, db: Database = Depends(get_db)):
    require_row(db, "SELECT 1 FROM organizations WHERE organization_id = %s", (organization_id,), "Organization")
    changes = updates_from(body, {"organization_name", "location", "status"})
    if changes:
        db.execute(f"UPDATE organizations SET {', '.join(f'{k} = %s' for k in changes)} WHERE organization_id = %s",
                   [*changes.values(), organization_id])
    return get_organization(organization_id, db)


@router.delete("/{organization_id}", status_code=204, dependencies=[Depends(require_roles("admin"))])
def delete_organization(organization_id: int, db: Database = Depends(get_db)):
    # Foreign keys from units/resources/responders make MySQL refuse (-> 409 IN_USE) if still referenced.
    _, deleted = db.execute("DELETE FROM organizations WHERE organization_id = %s", (organization_id,))
    if not deleted:
        require_row(db, "SELECT 1 FROM organizations WHERE organization_id = %s", (organization_id,), "Organization")
    return Response(status_code=204)
