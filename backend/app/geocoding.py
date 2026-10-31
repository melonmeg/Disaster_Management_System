"""Geocoding of free-text locations with Mappls (MapmyIndia), cached in MySQL (table geocode_cache).

Only the location string is sent to Mappls: no caller name, phone, transcript or patient data.
Provider errors are never cached, so an outage does not turn into permanent NOT_FOUND rows.
The Mappls static key is sent as the `access_token` query parameter, from the backend only.
"""
import math
import time
from dataclasses import dataclass

import httpx

from .config import settings
from .db import Database


class GeocoderError(Exception):
    """Provider unreachable / misconfigured / returned an unusable response."""


@dataclass(frozen=True)
class GeocodeResult:
    status: str                    # RESOLVED | AMBIGUOUS | NOT_FOUND
    latitude: float | None = None
    longitude: float | None = None
    display_name: str | None = None
    provider: str = "mappls"


def normalize(location: str) -> str:
    return location.strip()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line (great-circle) distance; NOT a road distance or travel time."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# geocodeLevel values that mean "only a town/district/state was matched": too coarse to place an incident.
COARSE_LEVELS = {"city", "town", "district", "subdistrict", "state", "pincode", "country"}


def _coord(item: dict, *names: str) -> float | None:
    for n in names:
        if item.get(n) not in (None, ""):
            return float(item[n])
    return None


def parse_mappls(body: dict) -> GeocodeResult:
    """Normalise a Mappls geocode response.

    `copResults` is an object for one match or a list for several. Coordinates are read from
    latitude/longitude (or lat/lng) fields only; if the response has none the result is an error,
    never a guess. Run scripts/mappls_probe.py to see what your account actually returns.
    """
    if not isinstance(body, dict):
        raise GeocoderError("Mappls returned an unexpected response")
    items = body.get("copResults", body.get("results"))
    if items in (None, [], {}):
        return GeocodeResult("NOT_FOUND", provider="mappls")
    items = items if isinstance(items, list) else [items]
    try:
        points = []
        for it in items:
            lat, lon = _coord(it, "latitude", "lat"), _coord(it, "longitude", "lng", "lon")
            if lat is None or lon is None:
                raise GeocoderError("Mappls response contains no coordinates (see scripts/mappls_probe.py)")
            points.append((lat, lon, it.get("formattedAddress"), str(it.get("geocodeLevel", "")).lower()))
    except (TypeError, ValueError, AttributeError) as exc:
        raise GeocoderError("Mappls returned an unexpected response") from exc
    lat, lon, name, level = points[0]
    if level in COARSE_LEVELS:
        return GeocodeResult("AMBIGUOUS", provider="mappls")          # matched only a wide area
    if any(haversine_km(lat, lon, p[0], p[1]) > settings.geocoder_ambiguity_km for p in points[1:]):
        return GeocodeResult("AMBIGUOUS", provider="mappls")
    return GeocodeResult("RESOLVED", lat, lon, name, "mappls")


class MapplsGeocoder:
    min_interval = 0.25   # seconds between requests; Mappls quotas are per account, see your plan

    def __init__(self):
        self._last = 0.0

    def geocode(self, location: str) -> GeocodeResult:
        if not settings.mappls_api_key:
            raise GeocoderError("MAPPLS_API_KEY is not set")
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        params = {"address": location, "itemCount": 3, "access_token": settings.mappls_api_key}
        if settings.mappls_region:
            params["region"] = settings.mappls_region
        try:
            res = httpx.get(settings.mappls_geocode_url, params=params, timeout=10)
            if res.status_code in (400, 404, 204):
                return GeocodeResult("NOT_FOUND", provider="mappls")      # Mappls answers unmatched addresses this way
            if res.status_code in (401, 403):
                raise GeocoderError("Mappls rejected the API key (check MAPPLS_API_KEY and its restrictions)")
            res.raise_for_status()
            body = res.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GeocoderError(f"Geocoding provider failed: {exc.__class__.__name__}") from exc
        finally:
            self._last = time.monotonic()
        return parse_mappls(body)


_default_geocoder = MapplsGeocoder()


def get_geocoder():
    """FastAPI dependency; tests override it with a fake."""
    return _default_geocoder


def store_result(db: Database, location: str, result: GeocodeResult) -> None:
    db.execute(
        "INSERT INTO geocode_cache (location_key, status, latitude, longitude, display_name, provider) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE status = VALUES(status), latitude = VALUES(latitude), "
        "longitude = VALUES(longitude), display_name = VALUES(display_name), provider = VALUES(provider), "
        "resolved_at = NOW(), resolved_by = NULL",
        (normalize(location), result.status, result.latitude, result.longitude,
         (result.display_name or None) and result.display_name[:500], result.provider))


def pending_locations(db: Database, limit: int) -> list[str]:
    """Distinct incident / unit-base locations with no cache row yet."""
    rows = db.all(
        "SELECT loc FROM ("
        "  SELECT TRIM(location) AS loc FROM incidents"
        "  UNION SELECT TRIM(base_location) FROM units WHERE base_location IS NOT NULL"
        ") t WHERE loc <> '' AND loc NOT IN (SELECT location_key FROM geocode_cache) LIMIT %s", (limit,))
    return [r["loc"] for r in rows]


def resolve_pending(db: Database, geocoder, limit: int = 10) -> dict:
    """Geocode up to `limit` uncached locations. Stops at the first provider failure."""
    summary = {"resolved": 0, "ambiguous": 0, "not_found": 0, "error": None}
    for location in pending_locations(db, limit):
        try:
            result = geocoder.geocode(location)
        except GeocoderError as exc:
            summary["error"] = str(exc)
            break
        store_result(db, location, result)
        summary[result.status.lower()] += 1
    summary["remaining"] = len(pending_locations(db, 1000))
    return summary
