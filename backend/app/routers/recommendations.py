"""/api/recommendations — AI-assisted dispatch suggestions.

Suggestions only: nothing here creates a dispatch. The dispatcher confirms in the UI, which then
calls the existing POST /api/dispatches; `PUT /recommendations/{id}/dispatch` afterwards links the
resulting dispatch to the recommendation for later evaluation.
"""
from fastapi import APIRouter, Depends, Query
from pydantic import Field

from ..common import require_row
from ..config import settings
from ..db import Database
from ..errors import ApiError, not_found
from ..recommendation import engine, explain
from ..recommendation.store import DecisionRecord, FeedbackRecord, RecommendationStore, StoreUnavailable, get_store, now
from ..schemas import Body
from ..security import CurrentUser, get_db, require_roles

router = APIRouter(tags=["recommendations"], dependencies=[Depends(require_roles("admin", "dispatcher"))])
staff = require_roles("admin", "dispatcher")


class DecisionIn(Body):
    decision: str = Field(pattern="^(ACCEPTED|REJECTED|OVERRIDDEN)$")
    unit_id: int | None = Field(None, gt=0)
    reason: str | None = Field(None, max_length=500)


class DispatchLinkIn(Body):
    dispatch_id: int = Field(gt=0)


class FeedbackIn(Body):
    rating: int | None = Field(None, ge=1, le=5)
    comment: str | None = Field(None, max_length=1000)


def _model_info() -> dict:
    llm_on = settings.llm_enabled and bool(settings.llm_api_key and settings.llm_base_url and settings.llm_model)
    return {"llm": settings.llm_model if llm_on else None, "llm_enabled": llm_on}


@router.post("/incidents/{incident_id}/recommendations", status_code=201)
def generate(incident_id: int, user: CurrentUser = Depends(staff), db: Database = Depends(get_db),
             store: RecommendationStore = Depends(get_store)):
    """Rank eligible units for an incident (deterministic), add an LLM explanation if available, store the result.

    If MongoDB is down the ranking is still returned with `persisted: false` and no recommendation_id,
    so it can be read but not accepted/rejected.
    """
    ranking = engine.recommend(db, incident_id)
    explanation, reason = explain.explain(ranking)
    try:
        doc = store.create(incident_id, user.user_id, ranking, explanation, reason, _model_info())
        return {**doc, "persisted": True, "persistence_error": None}
    except StoreUnavailable as exc:
        return {"recommendation_id": None, "incident_id": incident_id, "status": "UNSAVED", "ranking": ranking,
                "explanation": explanation, "explanation_unavailable_reason": reason, "decision": None,
                "feedback": [], "algorithm_version": ranking["algorithm_version"], "model": _model_info(),
                "persisted": False, "persistence_error": exc.message}


@router.get("/incidents/{incident_id}/recommendations")
def history(incident_id: int, limit: int = Query(20, ge=1, le=100), db: Database = Depends(get_db),
            store: RecommendationStore = Depends(get_store)):
    require_row(db, "SELECT 1 FROM incidents WHERE incident_id = %s", (incident_id,), "Incident")
    return {"data": store.list_for_incident(incident_id, limit)}


@router.get("/recommendations/summary")
def summary(store: RecommendationStore = Depends(get_store)):
    return {"pending": store.pending_count()}


def _load(store: RecommendationStore, recommendation_id: str) -> dict:
    doc = store.get(recommendation_id)
    if doc is None:
        raise not_found("Recommendation")
    return doc


@router.get("/recommendations/{recommendation_id}")
def get_one(recommendation_id: str, store: RecommendationStore = Depends(get_store)):
    return _load(store, recommendation_id)


@router.post("/recommendations/{recommendation_id}/decision")
def decide(recommendation_id: str, body: DecisionIn, user: CurrentUser = Depends(staff),
           db: Database = Depends(get_db), store: RecommendationStore = Depends(get_store)):
    """Record accept / reject / override. This does NOT dispatch anything."""
    doc = _load(store, recommendation_id)
    candidate_ids = {c["unit_id"] for c in doc["ranking"]["candidates"]}
    if body.decision == "REJECTED":
        if body.unit_id is not None:
            raise ApiError(400, "VALIDATION_ERROR", "A rejection does not name a unit")
    else:
        if body.unit_id is None:
            raise ApiError(400, "VALIDATION_ERROR", "unit_id is required to accept or override")
        if body.decision == "ACCEPTED" and body.unit_id not in candidate_ids:
            raise ApiError(400, "VALIDATION_ERROR", "Only a recommended candidate can be accepted; use OVERRIDDEN for other units")
        if body.decision == "OVERRIDDEN":
            if not (body.reason and len(body.reason.strip()) >= 3):
                raise ApiError(400, "VALIDATION_ERROR", "An override needs a reason")
            require_row(db, "SELECT 1 FROM units WHERE unit_id = %s", (body.unit_id,), "Unit")
    record = DecisionRecord(decision=body.decision, unit_id=body.unit_id, reason=body.reason,
                            decided_by=user.user_id, decided_at=now())
    if not store.record_decision(recommendation_id, record):
        raise ApiError(409, "BUSINESS_RULE_VIOLATION", "This recommendation was already decided or has been superseded")
    return _load(store, recommendation_id)


@router.put("/recommendations/{recommendation_id}/dispatch")
def link_dispatch(recommendation_id: str, body: DispatchLinkIn, db: Database = Depends(get_db),
                  store: RecommendationStore = Depends(get_store)):
    """After the dispatcher confirmed and POST /dispatches succeeded: remember which dispatch resulted."""
    doc = _load(store, recommendation_id)
    decision = doc.get("decision")
    if not decision or decision["decision"] == "REJECTED":
        raise ApiError(409, "BUSINESS_RULE_VIOLATION", "Only an accepted or overridden recommendation can be linked to a dispatch")
    dispatch = require_row(db, "SELECT incident_id, unit_id FROM dispatches WHERE dispatch_id = %s",
                           (body.dispatch_id,), "Dispatch")
    if dispatch["incident_id"] != doc["incident_id"] or dispatch["unit_id"] != decision["unit_id"]:
        raise ApiError(409, "BUSINESS_RULE_VIOLATION", "That dispatch is for a different incident or unit than the decision")
    if not store.link_dispatch(recommendation_id, body.dispatch_id):
        raise ApiError(409, "BUSINESS_RULE_VIOLATION", "A dispatch is already linked to this recommendation")
    return _load(store, recommendation_id)


@router.post("/recommendations/{recommendation_id}/feedback", status_code=201)
def add_feedback(recommendation_id: str, body: FeedbackIn, user: CurrentUser = Depends(staff),
                 store: RecommendationStore = Depends(get_store)):
    if body.rating is None and not body.comment:
        raise ApiError(400, "VALIDATION_ERROR", "Provide a rating or a comment")
    if not store.add_feedback(recommendation_id, FeedbackRecord(rating=body.rating, comment=body.comment,
                                                                by=user.user_id, at=now())):
        raise not_found("Recommendation")
    return _load(store, recommendation_id)


@router.delete("/recommendations/{recommendation_id}", status_code=204, dependencies=[Depends(require_roles("admin"))])
def delete_recommendation(recommendation_id: str, store: RecommendationStore = Depends(get_store)):
    """Admin only: remove a recommendation record (e.g. test data). The MySQL dispatch it may have led to is untouched."""
    if not store.delete(recommendation_id):
        raise not_found("Recommendation")
