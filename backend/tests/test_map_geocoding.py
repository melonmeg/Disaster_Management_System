"""Map data, geocoding (with a fake provider) and manual coordinates."""
import pytest

from app.geocoding import GeocodeResult, GeocoderError, parse_mappls
from app.main import app
from app.geocoding import get_geocoder
from conftest import mysql_as


class FakeGeocoder:
    def __init__(self, table):
        self.table, self.calls = table, []

    def geocode(self, location):
        self.calls.append(location)
        outcome = self.table.get(location, GeocodeResult("NOT_FOUND"))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def geocoder():
    fake = FakeGeocoder({})
    app.dependency_overrides[get_geocoder] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_geocoder, None)


def _incident(client, headers, location):
    res = client.post("/api/incidents", headers=headers,
                      json={"incident_type": "Road Accident", "severity": "LOW", "location": location})
    assert res.status_code == 201, res.text
    return res.json()["incident_id"]


def _map_row(client, headers, incident_id):
    rows = client.get("/api/map/incidents", headers=headers).json()["data"]
    return next(r for r in rows if r["incident_id"] == incident_id)


def test_unresolved_incident_is_not_placed_on_the_map(client, dispatcher):
    iid = _incident(client, dispatcher, "Nowhere Lane 1, Unit Test District")
    row = _map_row(client, dispatcher, iid)
    assert row["geocode_status"] == "PENDING"
    assert row["latitude"] is None and row["longitude"] is None


def test_geocode_resolves_caches_and_reports_failures(client, dispatcher, geocoder):
    ok = "Geo Test Street 1, Resolved City"
    missing = "Geo Test Street 2, Missing City"
    ambiguous = "Geo Test Street 3, Ambiguous City"
    geocoder.table = {
        ok: GeocodeResult("RESOLVED", 12.9716, 77.5946, "Geo Test Street 1"),
        ambiguous: GeocodeResult("AMBIGUOUS"),
    }
    ids = {name: _incident(client, dispatcher, name) for name in (ok, missing, ambiguous)}

    res = client.post("/api/map/geocode?limit=25", headers=dispatcher)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["error"] is None and body["remaining"] == 0
    assert _map_row(client, dispatcher, ids[ok])["latitude"] == pytest.approx(12.9716)
    assert _map_row(client, dispatcher, ids[missing])["geocode_status"] == "NOT_FOUND"
    amb = _map_row(client, dispatcher, ids[ambiguous])
    assert amb["geocode_status"] == "AMBIGUOUS" and amb["latitude"] is None   # never a guessed position

    # cached: a second run must not call the provider again for the same text
    geocoder.calls.clear()
    client.post("/api/map/geocode?limit=25", headers=dispatcher)
    assert ok not in geocoder.calls and missing not in geocoder.calls


def test_provider_failure_is_reported_and_not_cached(client, dispatcher, geocoder):
    loc = "Geo Failure Road 9, Outage Town"
    geocoder.table = {loc: GeocoderError("Geocoding provider failed: ConnectError")}
    iid = _incident(client, dispatcher, loc)
    body = client.post("/api/map/geocode?limit=25", headers=dispatcher).json()
    assert "failed" in body["error"]
    assert _map_row(client, dispatcher, iid)["geocode_status"] == "PENDING"   # retried next time, not NOT_FOUND


def test_filters(client, dispatcher):
    iid = _incident(client, dispatcher, "Filter Test Street 5, Somewhere")
    rows = client.get("/api/map/incidents?severity=LOW&status=OPEN&incident_type=Road Accident",
                      headers=dispatcher).json()["data"]
    assert iid in {r["incident_id"] for r in rows}
    assert all(r["severity"] == "LOW" for r in rows)
    assert client.get("/api/map/incidents?severity=BOGUS", headers=dispatcher).status_code == 422


def test_manual_coordinates_override(client, dispatcher):
    loc = "Manual Test Street 7, Hand Town"
    iid = _incident(client, dispatcher, loc)
    res = client.put("/api/map/locations", headers=dispatcher,
                     json={"location": loc, "latitude": 28.61, "longitude": 77.2})
    assert res.status_code == 200
    row = _map_row(client, dispatcher, iid)
    assert row["geocode_status"] == "MANUAL" and row["latitude"] == pytest.approx(28.61)
    bad = client.put("/api/map/locations", headers=dispatcher, json={"location": loc, "latitude": 95, "longitude": 0})
    assert bad.status_code == 422


def test_roles(client, responder, dispatcher):
    assert client.get("/api/map/incidents", headers=responder).status_code == 200
    assert client.post("/api/map/geocode", headers=responder).status_code == 403
    assert client.put("/api/map/locations", headers=responder,
                      json={"location": "x", "latitude": 1, "longitude": 1}).status_code == 403
    assert client.get("/api/map/incidents").status_code == 401


def test_mysql_privileges_on_geocode_cache():
    import pymysql
    conn = mysql_as("DB_RESPONDER")
    with conn.cursor() as cur, pytest.raises(pymysql.err.MySQLError) as exc:
        cur.execute("INSERT INTO geocode_cache (location_key, status) VALUES ('x', 'NOT_FOUND')")
    assert exc.value.args[0] == 1142
    conn.close()


def test_parse_mappls_responses():
    assert parse_mappls({"copResults": []}).status == "NOT_FOUND"
    one = parse_mappls({"copResults": {"latitude": 12.0, "longitude": "77.0", "formattedAddress": "A",
                                       "geocodeLevel": "street", "confidenceScore": 0.9}})
    assert one.status == "RESOLVED" and one.latitude == 12.0 and one.longitude == 77.0 and one.provider == "mappls"
    near = parse_mappls({"copResults": [{"lat": 12.0, "lng": 77.0, "geocodeLevel": "houseNumber"},
                                        {"lat": 12.001, "lng": 77.001}]})
    assert near.status == "RESOLVED"
    far = parse_mappls({"copResults": [{"lat": 12.0, "lng": 77.0}, {"lat": 28.6, "lng": 77.2}]})
    assert far.status == "AMBIGUOUS" and far.latitude is None
    coarse = parse_mappls({"copResults": {"latitude": 12.0, "longitude": 77.0, "geocodeLevel": "city"}})
    assert coarse.status == "AMBIGUOUS" and coarse.latitude is None        # wide-area match is not placed
    with pytest.raises(GeocoderError, match="no coordinates"):             # eLoc only: never invent a position
        parse_mappls({"copResults": {"eLoc": "TIYF9Q", "geocodeLevel": "street"}})
    with pytest.raises(GeocoderError):
        parse_mappls([1, 2])


def test_mappls_http_handling(monkeypatch):
    import httpx
    from app import geocoding
    g = geocoding.MapplsGeocoder(); g.min_interval = 0
    monkeypatch.setattr(geocoding, "settings", type("S", (), {"mappls_api_key": "", "mappls_geocode_url": "http://m",
                                                              "mappls_region": "", "geocoder_ambiguity_km": 5})())
    with pytest.raises(GeocoderError, match="MAPPLS_API_KEY"):
        g.geocode("x")
    monkeypatch.setattr(geocoding.settings.__class__, "mappls_api_key", "k", raising=False)
    seen = {}

    def fake_get(url, params, timeout):
        seen.update(params)
        return httpx.Response(seen.pop("_status", 200), json={"copResults": {"latitude": 1, "longitude": 2}},
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(geocoding.httpx, "get", fake_get)
    assert g.geocode("Some Street").status == "RESOLVED"
    assert seen["address"] == "Some Street" and set(seen) == {"address", "itemCount", "access_token"}   # nothing else is sent
    monkeypatch.setattr(geocoding.httpx, "get", lambda u, params, timeout: httpx.Response(401, request=httpx.Request("GET", u)))
    with pytest.raises(GeocoderError, match="rejected the API key"):
        g.geocode("x")
    monkeypatch.setattr(geocoding.httpx, "get", lambda u, params, timeout: httpx.Response(404, request=httpx.Request("GET", u)))
    assert g.geocode("x").status == "NOT_FOUND"
    monkeypatch.setattr(geocoding.httpx, "get", lambda u, params, timeout: httpx.Response(500, request=httpx.Request("GET", u)))
    with pytest.raises(GeocoderError, match="provider failed"):
        g.geocode("x")
