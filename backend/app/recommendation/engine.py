"""Deterministic recommendation: collect facts -> eligibility -> ranking.

No LLM is involved here. Every number in the output is either read from MySQL or
computed from values read from MySQL, and every exclusion carries a reason code.
Missing information is reported (`missing`) and lowers confidence; it is never
treated as evidence that a unit fits.
"""
from ..db import Database
from ..errors import ApiError, not_found
from ..geocoding import haversine_km
from . import rules

RECOMMENDABLE_INCIDENT_STATUSES = ("OPEN", "IN_PROGRESS")


def collect_facts(db: Database, incident_id: int) -> dict:
    incident = db.one("SELECT * FROM v_incident_map WHERE incident_id = %s", (incident_id,))
    if incident is None:
        raise not_found("Incident")
    units = db.all(
        "SELECT a.unit_id, a.unit_name, a.unit_type, a.status, a.base_location, a.organization_id, "
        "a.organization_name, a.is_free, a.crew_size, a.current_incident_id, "
        "l.latitude AS base_latitude, l.longitude AS base_longitude "
        "FROM v_unit_availability a JOIN v_unit_locations l ON l.unit_id = a.unit_id ORDER BY a.unit_id")
    resources = db.all(
        "SELECT resource_id, resource_name, resource_type, status, organization_id, organization_name, quantity_total, "
        "quantity_available FROM v_resource_stock ORDER BY resource_id")
    dispatched_units = {r["unit_id"] for r in db.all(
        "SELECT unit_id FROM dispatches WHERE incident_id = %s AND status NOT IN ('COMPLETED', 'CANCELLED')",
        (incident_id,))}
    return {"incident": incident, "units": units, "resources": resources, "dispatched_units": dispatched_units}


def _float(value) -> float | None:
    return None if value is None else float(value)


def evaluate(facts: dict) -> dict:
    """Pure function of `facts`: {candidates, excluded, resource_shortages, missing, confidence, ...}."""
    inc = facts["incident"]
    if inc["status"] not in RECOMMENDABLE_INCIDENT_STATUSES:
        raise ApiError(409, "BUSINESS_RULE_VIOLATION",
                       f"Incident is {inc['status']}; recommendations are only generated for OPEN or IN_PROGRESS incidents")

    rule = rules.rule_for(inc["incident_type"])
    weights = rules.weights()
    inc_lat, inc_lon = _float(inc["latitude"]), _float(inc["longitude"])
    incident_missing = []
    if rule is None:
        incident_missing.append(
            f"No capability rule for incident type '{inc['incident_type']}'; unit suitability is unknown")
    if inc_lat is None:
        incident_missing.append(
            f"Incident location is not geocoded (status: {inc['geocode_status'] or 'not attempted'}); distance unavailable")

    candidates, excluded = [], []
    for u in facts["units"]:
        base = {"unit_id": u["unit_id"], "unit_name": u["unit_name"], "unit_type": u["unit_type"]}
        if u["unit_id"] in facts["dispatched_units"]:
            excluded.append({**base, "reason_code": "ALREADY_DISPATCHED_TO_INCIDENT"}); continue
        if u["status"] == "OUT_OF_SERVICE":
            excluded.append({**base, "reason_code": "OUT_OF_SERVICE"}); continue
        if not u["is_free"]:
            excluded.append({**base, "reason_code": "UNIT_BUSY", "current_incident_id": u["current_incident_id"]}); continue

        if rule is None:
            capability, cap_code = None, "CAPABILITY_UNKNOWN"
        elif u["unit_type"] in rule["primary"]:
            capability, cap_code = 1.0, "PRIMARY_TYPE_MATCH"
        elif u["unit_type"] in rule["supporting"]:
            capability, cap_code = 0.5, "SUPPORTING_TYPE_MATCH"
        else:
            excluded.append({**base, "reason_code": "CAPABILITY_MISMATCH"}); continue

        missing = list(incident_missing)
        distance_km = None
        if inc_lat is not None:
            if u["base_latitude"] is not None:
                distance_km = round(
                    haversine_km(inc_lat, inc_lon, float(u["base_latitude"]), float(u["base_longitude"])), 1)
            else:
                missing.append(f"Base location of {u['unit_name']} is not geocoded; distance unavailable")
        crew = int(u["crew_size"])
        if crew == 0:
            missing.append(f"{u['unit_name']} has no crew assigned in the database")

        needs_resources = bool(rule and rule["resource_types"])
        relevant = [
            {"resource_id": r["resource_id"], "resource_name": r["resource_name"], "resource_type": r["resource_type"],
             "quantity_available": r["quantity_available"]}
            for r in facts["resources"]
            if needs_resources and r["organization_id"] == u["organization_id"] and r["status"] == "AVAILABLE"
            and r["resource_type"] in rule["resource_types"] and r["quantity_available"] > 0]
        stock_available = sum(r["quantity_available"] for r in relevant)

        candidates.append({
            **base, "organization_id": u["organization_id"], "organization_name": u["organization_name"],
            "base_location": u["base_location"], "crew_size": crew,
            "capability_code": cap_code, "distance_km": distance_km,
            "distance_note": "straight-line distance between geocoded points, not travel time"
                             if distance_km is not None else None,
            "relevant_stock_available": stock_available if needs_resources else None,
            "relevant_resources": relevant,   # stock to consider allocating after dispatch; quantities are NOT suggested
            "components": {"capability": capability,
                           "availability": 1.0 if crew > 0 else 0.3,
                           "distance": None,   # normalised across candidates below
                           "resources": (1.0 if stock_available > 0 else 0.0) if needs_resources else None},
            "missing": missing,
        })

    # distance score = nearest / this candidate's distance (nearest candidate = 1.0)
    known = [c["distance_km"] for c in candidates if c["distance_km"] is not None]
    if known:
        nearest = min(known)
        for c in candidates:
            d = c["distance_km"]
            if d is not None:
                c["components"]["distance"] = 1.0 if d == nearest else round(nearest / d, 3)

    for c in candidates:
        used = {k: v for k, v in c["components"].items() if v is not None}
        total_w = sum(weights[k] for k in used)
        c["score"] = round(sum(weights[k] * v for k, v in used.items()) / total_w, 3) if total_w else 0.0
        c["factors_used"] = sorted(used)
        c["confidence"] = _confidence(c)

    candidates.sort(key=lambda c: (-c["score"], c["distance_km"] if c["distance_km"] is not None else 1e9,
                                   c["unit_id"]))
    for rank, c in enumerate(candidates, 1):
        c["rank"] = rank

    shortages = []
    if rule:
        for rtype in rule["resource_types"]:
            total = sum(r["quantity_available"] for r in facts["resources"]
                        if r["resource_type"] == rtype and r["status"] == "AVAILABLE")
            if total == 0:
                shortages.append({"resource_type": rtype, "reason_code": "NO_STOCK_AVAILABLE"})

    return {
        "incident_id": inc["incident_id"], "incident_type": inc["incident_type"], "severity": inc["severity"],
        "incident_status": inc["status"], "incident_location": inc["location"],
        "incident_coordinates": None if inc_lat is None else {"latitude": inc_lat, "longitude": inc_lon},
        "required_unit_types": None if rule is None
        else {"primary": list(rule["primary"]), "supporting": list(rule["supporting"])},
        "candidates": candidates, "excluded": excluded, "resource_shortages": shortages,
        "weights": weights, "algorithm_version": rules.ALGORITHM_VERSION,
        "missing": incident_missing,
        "confidence": candidates[0]["confidence"] if candidates else "INSUFFICIENT",
    }


def _confidence(c: dict) -> str:
    """HIGH needs a primary capability match and a known distance; unknown capability = INSUFFICIENT."""
    capability = c["components"]["capability"]
    if capability is None:
        return "INSUFFICIENT"
    if capability < 1.0:
        return "LOW" if c["distance_km"] is None else "MEDIUM"
    return "HIGH" if c["distance_km"] is not None else "MEDIUM"


def recommend(db: Database, incident_id: int) -> dict:
    return evaluate(collect_facts(db, incident_id))
