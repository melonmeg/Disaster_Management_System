"""/api/logs — the MongoDB operational log (admin only)."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pymongo.errors import PyMongoError

from .. import oplog
from ..common import Page
from ..errors import ApiError
from ..security import require_roles

router = APIRouter(tags=["operational log"], dependencies=[Depends(require_roles("admin"))])


@router.get("/logs")
def list_logs(user_id: int | None = Query(None, gt=0), method: str | None = Query(None, pattern="^(GET|POST|PUT|PATCH|DELETE)$"),
              status_min: int | None = Query(None, ge=100, le=599), status_max: int | None = Query(None, ge=100, le=599),
              path_prefix: str | None = Query(None, max_length=200), since: datetime | None = None,
              until: datetime | None = None, page: Page = Depends()):
    """Newest first. Successful reads are not logged; see app/oplog.py for what is and is not stored."""
    store = oplog.get_oplog()
    if store is None:
        raise ApiError(503, "OPLOG_DISABLED", "The operational log is turned off (OPLOG_ENABLED=false)")
    try:
        return store.search(user_id=user_id, method=method, status_min=status_min, status_max=status_max,
                            path_prefix=path_prefix, since=since, until=until, page=page.page, page_size=page.page_size)
    except PyMongoError as exc:
        raise ApiError(503, "OPLOG_UNAVAILABLE", "The operational log (MongoDB) is unavailable") from exc
