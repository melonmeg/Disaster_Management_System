"""MongoDB persistence of recommendations (collection `recommendation_history`).

MySQL stays authoritative for incidents, units, dispatches and resources; documents here
only point at MySQL ids and keep the evidence a recommendation was based on. A MySQL write
and a MongoDB write are two separate operations, never one transaction: the API reports a
failed Mongo write instead of hiding it, and nothing is dispatched by this module.
"""
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

from ..config import settings
from ..errors import ApiError

COLLECTION = "recommendation_history"
Decision = Literal["ACCEPTED", "REJECTED", "OVERRIDDEN"]


class StoreUnavailable(ApiError):
    def __init__(self, message="Recommendation history (MongoDB) is unavailable"):
        super().__init__(503, "RECOMMENDATION_STORE_UNAVAILABLE", message)


class DecisionRecord(BaseModel):
    decision: Decision
    unit_id: int | None = None          # unit the dispatcher chose (ACCEPTED / OVERRIDDEN)
    reason: str | None = Field(None, max_length=500)
    decided_by: int                     # app_users.user_id
    decided_at: datetime
    dispatch_id: int | None = None      # MySQL dispatch created after the dispatcher confirmed


class FeedbackRecord(BaseModel):
    rating: int | None = Field(None, ge=1, le=5)
    comment: str | None = Field(None, max_length=1000)
    by: int
    at: datetime


class RecommendationDoc(BaseModel):
    recommendation_id: str
    incident_id: int
    generated_at: datetime
    generated_by: int
    status: Literal["GENERATED", "REVIEWED", "SUPERSEDED"] = "GENERATED"
    algorithm_version: str
    model: dict
    ranking: dict                       # candidates (scores, reason codes, evidence), exclusions, weights, missing
    explanation: dict | None = None
    explanation_unavailable_reason: str | None = None
    decision: DecisionRecord | None = None
    feedback: list[FeedbackRecord] = []


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


class RecommendationStore:
    def __init__(self, database):
        self.col = database[COLLECTION]

    def ensure_indexes(self) -> None:
        self._run(lambda: (
            self.col.create_index("recommendation_id", unique=True),
            self.col.create_index([("incident_id", ASCENDING), ("generated_at", DESCENDING)]),
            self.col.create_index([("status", ASCENDING), ("generated_at", DESCENDING)]),
            self.col.create_index("decision.dispatch_id", sparse=True),
        ))

    @staticmethod
    def _run(fn):
        try:
            return fn()
        except PyMongoError as exc:
            raise StoreUnavailable() from exc

    def create(self, incident_id: int, user_id: int, ranking: dict, explanation: dict | None,
               unavailable_reason: str | None, model: dict) -> dict:
        doc = RecommendationDoc(
            recommendation_id=uuid.uuid4().hex, incident_id=incident_id, generated_at=now(), generated_by=user_id,
            algorithm_version=ranking["algorithm_version"], model=model, ranking=ranking,
            explanation=explanation, explanation_unavailable_reason=unavailable_reason).model_dump()
        # insert first; only then supersede older documents, so a failure never leaves an incident with none
        self._run(lambda: self.col.insert_one(dict(doc)))
        self._run(lambda: self.col.update_many(
            {"incident_id": incident_id, "status": {"$in": ["GENERATED", "REVIEWED"]},
             "recommendation_id": {"$ne": doc["recommendation_id"]}},
            {"$set": {"status": "SUPERSEDED"}}))
        return doc

    def get(self, recommendation_id: str) -> dict | None:
        return self._run(lambda: self.col.find_one({"recommendation_id": recommendation_id}, {"_id": 0}))

    def list_for_incident(self, incident_id: int, limit: int = 20) -> list[dict]:
        return self._run(lambda: list(self.col.find({"incident_id": incident_id}, {"_id": 0})
                                      .sort([("generated_at", DESCENDING), ("_id", DESCENDING)]).limit(limit)))

    def pending_count(self) -> int:
        return self._run(lambda: self.col.count_documents({"status": "GENERATED", "decision": None}))

    def record_decision(self, recommendation_id: str, decision: DecisionRecord) -> bool:
        """Atomically set the decision once. False if it was already decided or is superseded."""
        result = self._run(lambda: self.col.update_one(
            {"recommendation_id": recommendation_id, "decision": None, "status": "GENERATED"},
            {"$set": {"decision": decision.model_dump(), "status": "REVIEWED"}}))
        return result.matched_count == 1

    def link_dispatch(self, recommendation_id: str, dispatch_id: int) -> bool:
        result = self._run(lambda: self.col.update_one(
            {"recommendation_id": recommendation_id, "decision.dispatch_id": None,
             "decision": {"$ne": None}, "decision.decision": {"$in": ["ACCEPTED", "OVERRIDDEN"]}},
            {"$set": {"decision.dispatch_id": dispatch_id}}))
        return result.matched_count == 1

    def delete(self, recommendation_id: str) -> bool:
        result = self._run(lambda: self.col.delete_one({"recommendation_id": recommendation_id}))
        return result.deleted_count == 1

    def add_feedback(self, recommendation_id: str, feedback: FeedbackRecord) -> bool:
        result = self._run(lambda: self.col.update_one(
            {"recommendation_id": recommendation_id}, {"$push": {"feedback": feedback.model_dump()}}))
        return result.matched_count == 1


_database = None
_store: RecommendationStore | None = None
_indexes_ready = False


def get_mongo_db():
    """The shared MongoDB database handle (MongoClient connects lazily and never raises here)."""
    global _database
    if _database is None:
        _database = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=2000)[settings.mongodb_db]
    return _database


def get_store() -> RecommendationStore:
    """FastAPI dependency; tests override it with a mongomock-backed store.

    Never raises: a MongoDB outage shows up as StoreUnavailable on the first real operation (letting
    callers degrade gracefully). Indexes are (re)tried until they succeed.
    """
    global _store, _indexes_ready
    if _store is None:
        _store = RecommendationStore(get_mongo_db())
    if not _indexes_ready:
        try:
            _store.ensure_indexes()
            _indexes_ready = True
        except StoreUnavailable:
            pass
    return _store
