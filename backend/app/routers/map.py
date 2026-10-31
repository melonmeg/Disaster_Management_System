"""/api/map — incident map data and geocoding of locations (cached in MySQL)."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from ..db import Database
from ..geocoding import get_geocoder, normalize, pending_locations, resolve_pending
from ..schemas import Body, IncidentStatus, Severity
from ..security import CurrentUser, current_user, get_db, require_roles
from pydantic import Field

router = APIRouter(prefix="/map", tags=["map"])


class ManualLocationIn(Body):
    location: str = Field(min_length=1, max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


@router.get("/incidents")
def map_incidents(status: list[IncidentStatus] | None = Query(None), severity: list[Severity] | None = Query(None),
                  incident_type: str | None = None, created_from: datetime | None = None,
                  _: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    """Incidents with coordinates where the location has been geocoded.

    Incidents whose location could not be resolved are still returned (latitude/longitude null,
    `geocode_status` explains why) so the UI can list them without placing them on the map.
    """
    where, params = [], []
    if status:
        where.append(f"status IN ({', '.join(['%s'] * len(status))})"); params += status
    if severity:
        where.append(f"severity IN ({', '.join(['%s'] * len(severity))})"); params += severity
    if incident_type:
        where.append("incident_type = %s"); params.append(incident_type)
    if created_from:
        where.append("created_at >= %s"); params.append(created_from)
    rows = db.all("SELECT * FROM v_incident_map" + (f" WHERE {' AND '.join(where)}" if where else "")
                  + " ORDER BY created_at DESC LIMIT 500", params)
    for r in rows:
        r["latitude"] = None if r["latitude"] is None else float(r["latitude"])
        r["longitude"] = None if r["longitude"] is None else float(r["longitude"])
        r["geocode_status"] = r["geocode_status"] or "PENDING"
    mapped = sum(r["latitude"] is not None for r in rows)
    return {"data": rows,
            "summary": {"total": len(rows), "mapped": mapped, "unmapped": len(rows) - mapped,
                        "pending_geocode": len(pending_locations(db, 1000))}}


@router.post("/geocode", dependencies=[Depends(require_roles("admin", "dispatcher"))])
def geocode_pending(limit: int = Query(10, ge=1, le=25), db: Database = Depends(get_db),
                    geocoder=Depends(get_geocoder)):
    """Geocode up to `limit` uncached incident / unit locations (1 provider request each, rate-limited)."""
    return resolve_pending(db, geocoder, limit)


@router.put("/locations")
def set_manual_location(body: ManualLocationIn, user: CurrentUser = Depends(require_roles("admin", "dispatcher")),
                        db: Database = Depends(get_db)):
    """Record coordinates a person verified for a location text (status MANUAL); overrides any geocoder result."""
    key = normalize(body.location)
    db.execute(
        "INSERT INTO geocode_cache (location_key, status, latitude, longitude, display_name, provider, resolved_by) "
        "VALUES (%s, 'MANUAL', %s, %s, NULL, 'manual', %s) "
        "ON DUPLICATE KEY UPDATE status = 'MANUAL', latitude = VALUES(latitude), longitude = VALUES(longitude), "
        "display_name = NULL, provider = 'manual', resolved_by = VALUES(resolved_by), resolved_at = NOW()",
        (key, body.latitude, body.longitude, user.user_id))
    return {"location": key, "geocode_status": "MANUAL", "latitude": body.latitude, "longitude": body.longitude}
