"""Recommendation engine, LLM-output validation, MongoDB persistence and the decision workflow.

MongoDB is replaced by mongomock here (no MongoDB server was available when these were written);
see README for how to run against a real server.
"""
import json

import mongomock
import pytest
from pymongo.errors import ServerSelectionTimeoutError

from app.errors import ApiError
from app.main import app
from app.recommendation import engine, explain
from app.recommendation.store import RecommendationStore, StoreUnavailable, get_store


# ---------------------------------------------------------------- engine (pure, no DB)
def _unit(uid, utype, *, free=True, status="AVAILABLE", crew=2, org=1, lat=None, lon=None):
    return {"unit_id": uid, "unit_name": f"Unit {uid}", "unit_type": utype, "status": status, "base_location": "B",
            "organization_id": org, "organization_name": "Org", "is_free": free, "crew_size": crew,
            "current_incident_id": None if free else 99, "base_latitude": lat, "base_longitude": lon}


def _facts(units, *, itype="Building Fire", status="OPEN", lat=None, lon=None, resources=(), dispatched=()):
    return {"incident": {"incident_id": 1, "incident_type": itype, "severity": "HIGH", "location": "L",
                         "status": status, "geocode_status": "RESOLVED" if lat is not None else None,
                         "latitude": lat, "longitude": lon},
            "units": units, "resources": list(resources), "dispatched_units": set(dispatched)}


def _stock(rtype, qty, org=1):
    return {"resource_id": 1, "resource_name": rtype, "resource_type": rtype, "status": "AVAILABLE",
            "organization_id": org, "quantity_total": 10, "quantity_available": qty}


def test_exclusions_have_reason_codes():
    r = engine.evaluate(_facts([
        _unit(1, "Fire Truck", free=False, status="DISPATCHED"),
        _unit(2, "Fire Truck", status="OUT_OF_SERVICE"),
        _unit(3, "Ambulance"), _unit(4, "Police Car"), _unit(5, "Boat"),
        _unit(6, "Fire Truck"),
    ], dispatched={4}))
    reasons = {e["unit_id"]: e["reason_code"] for e in r["excluded"]}
    assert reasons == {1: "UNIT_BUSY", 2: "OUT_OF_SERVICE", 4: "ALREADY_DISPATCHED_TO_INCIDENT", 5: "CAPABILITY_MISMATCH"}
    assert [c["unit_id"] for c in r["candidates"]] == [6, 3]          # primary type outranks supporting
    assert r["candidates"][0]["capability_code"] == "PRIMARY_TYPE_MATCH"


def test_resolved_incident_is_not_recommendable():
    with pytest.raises(ApiError) as exc:
        engine.evaluate(_facts([_unit(1, "Fire Truck")], status="RESOLVED"))
    assert exc.value.status == 409


def test_unknown_incident_type_is_never_a_capability_match():
    r = engine.evaluate(_facts([_unit(1, "Fire Truck")], itype="Alien Landing"))
    c = r["candidates"][0]
    assert c["capability_code"] == "CAPABILITY_UNKNOWN" and c["components"]["capability"] is None
    assert r["confidence"] == "INSUFFICIENT" and r["required_unit_types"] is None
    assert any("No capability rule" in m for m in r["missing"])


def test_distance_only_when_both_ends_are_geocoded():
    r = engine.evaluate(_facts(
        [_unit(1, "Fire Truck", lat=12.95, lon=77.60), _unit(2, "Fire Truck", lat=13.20, lon=77.70),
         _unit(3, "Fire Truck")], lat=12.97, lon=77.59))
    by_id = {c["unit_id"]: c for c in r["candidates"]}
    assert 0 < by_id[1]["distance_km"] < by_id[2]["distance_km"]
    assert by_id[3]["distance_km"] is None
    assert any("not geocoded" in m for m in by_id[3]["missing"])
    assert r["candidates"][0]["unit_id"] == 1
    assert by_id[1]["confidence"] == "HIGH" and by_id[3]["confidence"] == "MEDIUM"


def test_no_incident_coordinates_means_no_distance_claims():
    r = engine.evaluate(_facts([_unit(1, "Fire Truck", lat=12.9, lon=77.6)]))
    assert r["candidates"][0]["distance_km"] is None
    assert any("Incident location is not geocoded" in m for m in r["missing"])


def test_resources_and_shortages():
    r = engine.evaluate(_facts([_unit(1, "Fire Truck", org=1), _unit(2, "Fire Truck", org=2)],
                               resources=[_stock("Firefighting Equipment", 5, org=1)]))
    by_id = {c["unit_id"]: c for c in r["candidates"]}
    assert by_id[1]["relevant_stock_available"] == 5 and by_id[2]["relevant_stock_available"] == 0
    assert by_id[1]["relevant_resources"] == [{"resource_id": 1, "resource_name": "Firefighting Equipment",
                                               "resource_type": "Firefighting Equipment", "quantity_available": 5}]
    assert by_id[2]["relevant_resources"] == []
    assert r["candidates"][0]["unit_id"] == 1
    assert {s["resource_type"] for s in r["resource_shortages"]} == {"Power Equipment"}


def test_unit_without_crew_is_flagged_and_scored_lower():
    r = engine.evaluate(_facts([_unit(1, "Fire Truck", crew=0), _unit(2, "Fire Truck", crew=3)]))
    assert [c["unit_id"] for c in r["candidates"]] == [2, 1]
    assert any("no crew" in m for m in r["candidates"][1]["missing"])


def test_no_candidates_is_insufficient():
    r = engine.evaluate(_facts([_unit(1, "Fire Truck", free=False)]))
    assert r["candidates"] == [] and r["confidence"] == "INSUFFICIENT"


def test_weights_are_configurable(monkeypatch):
    from app.recommendation import rules
    monkeypatch.setattr(rules.settings.__class__, "reco_weights", "capability=1,availability=0,distance=0,resources=0",
                        raising=False)
    # frozen dataclass: patch the module-level settings object's attribute lookup instead
    monkeypatch.setattr(rules, "settings", type("S", (), {"reco_weights": "capability=1,availability=0,distance=0,resources=0"})())
    assert rules.weights()["capability"] == 1.0
    monkeypatch.setattr(rules, "settings", type("S", (), {"reco_weights": "capability=-1"})())
    with pytest.raises(ValueError):
        rules.weights()


# ---------------------------------------------------------------- LLM output validation
def _ranking():
    return engine.evaluate(_facts([_unit(7, "Fire Truck", lat=12.95, lon=77.60), _unit(8, "Ambulance")],
                                  lat=12.97, lon=77.59))


def _reply(**override):
    body = {"summary": "Unit 7 is a Fire Truck, the primary match.",
            "candidate_reasons": [{"unit_id": 7, "reasons": ["Primary type match for a fire."]}],
            "limitations": ["Unit 8 has no known distance."], "alternatives": [8], "sufficient_evidence": True}
    body.update(override)
    return json.dumps(body)


def test_valid_explanation_is_accepted():
    facts = explain.facts_for_model(_ranking())
    out = explain.validate(_reply(), facts)
    assert out["alternatives"] == [8] and out["sufficient_evidence"] is True


@pytest.mark.parametrize("reply, fragment", [
    ("not json", "not valid structured JSON"),
    (_reply(candidate_reasons=[{"unit_id": 99, "reasons": ["x"]}]), "not candidates"),
    (_reply(alternatives=[42]), "not candidates"),
    (_reply(summary="Unit 7 is 3.7 km away."), "numbers that are not in the supplied facts"),
    (_reply(summary=""), "does not match the expected JSON shape"),
])
def test_invalid_explanations_are_rejected(reply, fragment):
    with pytest.raises(explain.ExplanationRejected, match=fragment):
        explain.validate(reply, explain.facts_for_model(_ranking()))


def test_low_confidence_overrides_model_claim_of_sufficient_evidence():
    ranking = engine.evaluate(_facts([_unit(7, "Fire Truck")], itype="Alien Landing"))
    out = explain.validate(_reply(candidate_reasons=[], alternatives=[], limitations=[]),
                           explain.facts_for_model(ranking))
    assert out["sufficient_evidence"] is False


def test_explain_falls_back_when_unconfigured_or_failing(monkeypatch):
    ranking = _ranking()
    monkeypatch.setattr(explain, "settings", type("S", (), {"llm_enabled": True, "llm_api_key": "", "llm_base_url": "", "llm_model": ""})())
    assert explain.explain(ranking)[0] is None
    monkeypatch.setattr(explain, "settings", type("S", (), {"llm_enabled": True, "llm_api_key": "k", "llm_base_url": "http://x", "llm_model": "m"})())
    monkeypatch.setattr(explain, "call_llm", lambda s, u: _reply(alternatives=[1234]))
    text, reason = explain.explain(ranking)
    assert text is None and "rejected" in reason

    def boom(s, u):
        import httpx
        raise httpx.ConnectError("down")
    monkeypatch.setattr(explain, "call_llm", boom)
    assert explain.explain(ranking) == (None, "LLM unavailable: ConnectError")
    monkeypatch.setattr(explain, "call_llm", lambda s, u: _reply())
    assert explain.explain(ranking)[0]["alternatives"] == [8]


def test_only_necessary_facts_are_sent_to_the_model():
    sent = json.dumps(explain.facts_for_model(_ranking()))
    for forbidden in ("caller", "phone", "transcript", "patient"):
        assert forbidden not in sent


# ---------------------------------------------------------------- store
@pytest.fixture
def store():
    s = RecommendationStore(mongomock.MongoClient()["erms_test"])
    s.ensure_indexes()
    app.dependency_overrides[get_store] = lambda: s
    yield s
    app.dependency_overrides.pop(get_store, None)


def test_store_indexes(store):
    names = set(store.col.index_information())
    assert {"recommendation_id_1", "incident_id_1_generated_at_-1"} <= names


def test_new_recommendation_supersedes_old_one(store):
    first = store.create(5, 1, _ranking(), None, "x", {"llm": None})
    second = store.create(5, 1, _ranking(), None, "x", {"llm": None})
    assert store.get(first["recommendation_id"])["status"] == "SUPERSEDED"
    assert store.get(second["recommendation_id"])["status"] == "GENERATED"
    assert [d["recommendation_id"] for d in store.list_for_incident(5)][0] == second["recommendation_id"]


class _BrokenCollection:
    def __getattr__(self, name):
        def fail(*a, **k):
            raise ServerSelectionTimeoutError("mongo down")
        return fail


@pytest.fixture
def broken_store():
    s = RecommendationStore({"recommendation_history": _BrokenCollection()})
    app.dependency_overrides[get_store] = lambda: s
    yield s
    app.dependency_overrides.pop(get_store, None)


# ---------------------------------------------------------------- API workflow
@pytest.fixture
def fire_truck(client, admin):
    res = client.post("/api/units", headers=admin, json={
        "unit_name": "Test Fire Truck", "unit_type": "Fire Truck", "base_location": "Test Fire Base",
        "organization_id": 2})
    assert res.status_code == 201, res.text
    return res.json()


def test_generate_and_accept_then_dispatch_explicitly(client, dispatcher, store, open_incident, fire_truck):
    iid = open_incident["incident_id"]
    res = client.post(f"/api/incidents/{iid}/recommendations", headers=dispatcher)
    assert res.status_code == 201, res.text
    rec = res.json()
    assert rec["persisted"] is True and rec["explanation"] is None and rec["explanation_unavailable_reason"]
    ids = [c["unit_id"] for c in rec["ranking"]["candidates"]]
    assert fire_truck["unit_id"] in ids and rec["ranking"]["candidates"][0]["rank"] == 1

    # generating a recommendation must not dispatch anything
    assert client.get(f"/api/incidents/{iid}/dispatches", headers=dispatcher).json()["data"] == []

    unit_id = fire_truck["unit_id"]
    accepted = client.post(f"/api/recommendations/{rec['recommendation_id']}/decision", headers=dispatcher,
                           json={"decision": "ACCEPTED", "unit_id": unit_id})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "REVIEWED"
    assert client.get(f"/api/incidents/{iid}/dispatches", headers=dispatcher).json()["data"] == []  # still nothing

    again = client.post(f"/api/recommendations/{rec['recommendation_id']}/decision", headers=dispatcher,
                        json={"decision": "REJECTED"})
    assert again.status_code == 409

    dispatch = client.post("/api/dispatches", headers=dispatcher, json={"incident_id": iid, "unit_id": unit_id})
    assert dispatch.status_code == 201
    linked = client.put(f"/api/recommendations/{rec['recommendation_id']}/dispatch", headers=dispatcher,
                        json={"dispatch_id": dispatch.json()["dispatch_id"]})
    assert linked.status_code == 200 and linked.json()["decision"]["dispatch_id"] == dispatch.json()["dispatch_id"]

    # the unit is now busy, so a fresh recommendation excludes it
    fresh = client.post(f"/api/incidents/{iid}/recommendations", headers=dispatcher).json()
    assert unit_id not in [c["unit_id"] for c in fresh["ranking"]["candidates"]]
    assert client.get(f"/api/recommendations/{rec['recommendation_id']}", headers=dispatcher).json()["status"] == "SUPERSEDED"


def test_decision_validation(client, dispatcher, store, open_incident, fire_truck):
    iid = open_incident["incident_id"]
    rid = client.post(f"/api/incidents/{iid}/recommendations", headers=dispatcher).json()["recommendation_id"]
    url = f"/api/recommendations/{rid}/decision"
    assert client.post(url, headers=dispatcher, json={"decision": "ACCEPTED"}).status_code == 400
    assert client.post(url, headers=dispatcher, json={"decision": "ACCEPTED", "unit_id": 99999}).status_code == 400
    assert client.post(url, headers=dispatcher, json={"decision": "REJECTED", "unit_id": 1}).status_code == 400
    assert client.post(url, headers=dispatcher, json={"decision": "OVERRIDDEN", "unit_id": 1}).status_code == 400   # no reason
    assert client.post(url, headers=dispatcher, json={"decision": "OVERRIDDEN", "unit_id": 99999, "reason": "local knowledge"}).status_code == 404
    assert client.post(url, headers=dispatcher, json={"decision": "MAYBE"}).status_code == 422
    ok = client.post(url, headers=dispatcher, json={"decision": "OVERRIDDEN", "unit_id": 1, "reason": "closest in practice"})
    assert ok.status_code == 200 and ok.json()["decision"]["decision"] == "OVERRIDDEN"


def test_reject_records_feedback_and_cannot_link_dispatch(client, dispatcher, store, open_incident, fire_truck):
    iid = open_incident["incident_id"]
    rid = client.post(f"/api/incidents/{iid}/recommendations", headers=dispatcher).json()["recommendation_id"]
    assert client.post(f"/api/recommendations/{rid}/decision", headers=dispatcher,
                       json={"decision": "REJECTED", "reason": "wrong area"}).status_code == 200
    fb = client.post(f"/api/recommendations/{rid}/feedback", headers=dispatcher, json={"rating": 2, "comment": "slow"})
    assert fb.status_code == 201 and fb.json()["feedback"][0]["rating"] == 2
    assert client.post(f"/api/recommendations/{rid}/feedback", headers=dispatcher, json={}).status_code == 400
    assert client.put(f"/api/recommendations/{rid}/dispatch", headers=dispatcher,
                      json={"dispatch_id": 1}).status_code == 409
    assert client.get("/api/recommendations/summary", headers=dispatcher).json()["pending"] >= 0


def test_link_must_match_decision(client, dispatcher, store, open_incident, fire_truck, free_unit):
    iid = open_incident["incident_id"]
    rid = client.post(f"/api/incidents/{iid}/recommendations", headers=dispatcher).json()["recommendation_id"]
    client.post(f"/api/recommendations/{rid}/decision", headers=dispatcher,
                json={"decision": "ACCEPTED", "unit_id": fire_truck["unit_id"]})
    other = client.post("/api/dispatches", headers=dispatcher,
                        json={"incident_id": iid, "unit_id": free_unit["unit_id"]}).json()
    res = client.put(f"/api/recommendations/{rid}/dispatch", headers=dispatcher, json={"dispatch_id": other["dispatch_id"]})
    assert res.status_code == 409


def test_resolved_or_missing_incident(client, dispatcher, store):
    assert client.post("/api/incidents/999999/recommendations", headers=dispatcher).status_code == 404
    res = client.post("/api/incidents/103/recommendations", headers=dispatcher)   # sample data: RESOLVED
    assert res.status_code == 409


def test_responder_cannot_use_recommendations(client, responder, store):
    assert client.post("/api/incidents/101/recommendations", headers=responder).status_code == 403
    assert client.get("/api/incidents/101/recommendations", headers=responder).status_code == 403
    assert client.get("/api/recommendations/summary", headers=responder).status_code == 403
    assert client.post("/api/recommendations/abc/decision", headers=responder, json={"decision": "REJECTED"}).status_code == 403


def test_unknown_recommendation_is_404(client, dispatcher, store):
    assert client.get("/api/recommendations/doesnotexist", headers=dispatcher).status_code == 404


def test_mongo_down_returns_unsaved_ranking_and_clear_errors(client, dispatcher, broken_store, open_incident, fire_truck):
    iid = open_incident["incident_id"]
    res = client.post(f"/api/incidents/{iid}/recommendations", headers=dispatcher)
    assert res.status_code == 201
    body = res.json()
    assert body["persisted"] is False and body["recommendation_id"] is None and body["persistence_error"]
    assert body["ranking"]["candidates"]                       # the dispatcher still sees the ranking
    assert client.get(f"/api/incidents/{iid}/recommendations", headers=dispatcher).status_code == 503
    assert client.get("/api/recommendations/summary", headers=dispatcher).json()["error"]["code"] == "RECOMMENDATION_STORE_UNAVAILABLE"
    # MySQL operations are unaffected
    assert client.get("/api/units", headers=dispatcher).status_code == 200


def test_llm_explanation_is_stored_when_valid(client, dispatcher, store, open_incident, fire_truck, monkeypatch):
    monkeypatch.setattr(explain, "settings", type("S", (), {"llm_enabled": True, "llm_api_key": "k", "llm_base_url": "http://x", "llm_model": "m"})())
    captured = {}

    def fake(system, user):
        captured["user"] = user
        cands = json.loads(user)["candidates"]
        return json.dumps({"summary": f"{cands[0]['unit_name']} is the top ranked candidate.",
                           "candidate_reasons": [{"unit_id": cands[0]["unit_id"], "reasons": ["Primary type match."]}],
                           "limitations": [], "alternatives": [], "sufficient_evidence": True})
    monkeypatch.setattr(explain, "call_llm", fake)
    iid = open_incident["incident_id"]
    rec = client.post(f"/api/incidents/{iid}/recommendations", headers=dispatcher).json()
    assert rec["explanation"]["summary"].endswith("top ranked candidate.")
    assert rec["explanation_unavailable_reason"] is None
    assert "caller" not in captured["user"]


def test_admin_can_delete_a_recommendation_record(client, admin, dispatcher, store, open_incident, fire_truck):
    iid = open_incident["incident_id"]
    rid = client.post(f"/api/incidents/{iid}/recommendations", headers=dispatcher).json()["recommendation_id"]
    assert client.delete(f"/api/recommendations/{rid}", headers=dispatcher).status_code == 403
    assert client.delete(f"/api/recommendations/{rid}", headers=admin).status_code == 204
    assert client.get(f"/api/recommendations/{rid}", headers=dispatcher).status_code == 404
    assert client.delete(f"/api/recommendations/{rid}", headers=admin).status_code == 404


def test_overlong_lists_are_trimmed_and_wrapped_json_is_accepted():
    facts = explain.facts_for_model(_ranking())
    long_reasons = [{"unit_id": 7, "reasons": ["Reason " + c for c in "abcdefghi"]}]
    out = explain.validate(_reply(candidate_reasons=long_reasons, limitations=["x"] * 15), facts)
    assert len(out["candidate_reasons"][0]["reasons"]) == 6 and len(out["limitations"]) == 10
    wrapped = "<think>checking the units</think>Here is the JSON:\n" + _reply() + "\nHope this helps."
    assert explain.validate(wrapped, facts)["alternatives"] == [8]


def test_rejection_message_names_the_failing_field():
    with pytest.raises(explain.ExplanationRejected, match=r"\(alternatives:"):
        explain.validate(_reply(alternatives="none"), explain.facts_for_model(_ranking()))
