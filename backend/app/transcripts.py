"""MongoDB storage of call transcriptions (collection `call_transcripts`, one document per call).

The audio itself lives in MySQL (calls.audio_recording). Whatever tool transcribes it (the project does not
pick one) sends the result here: full text, optional timestamped segments, language and engine name. The
document points at MySQL only through `call_id` / `incident_id`, plus the SHA-256 of the audio it was made
from, so a transcript of an older recording is recognisable after the audio is replaced.
"""
from datetime import datetime

from pydantic import BaseModel, Field
from pymongo import ASCENDING
from pymongo.errors import PyMongoError

from .recommendation.store import StoreUnavailable, get_mongo_db, now

COLLECTION = "call_transcripts"


class Segment(BaseModel):
    start: float = Field(ge=0)          # seconds from the start of the recording
    end: float = Field(ge=0)
    text: str = Field(max_length=5000)
    speaker: str | None = Field(None, max_length=50)


class TranscriptDoc(BaseModel):
    call_id: int
    incident_id: int
    text: str = Field(min_length=1, max_length=200_000)
    language: str | None = Field(None, max_length=20)
    engine: str | None = Field(None, max_length=100)       # e.g. the speech-to-text model used
    segments: list[Segment] = Field(default_factory=list, max_length=5000)
    audio_sha256: str | None = None                       # audio this was made from (null if the call had none)
    created_at: datetime
    created_by: int
    updated_at: datetime


class TranscriptStore:
    def __init__(self, database):
        self.col = database[COLLECTION]

    @staticmethod
    def _run(fn):
        try:
            return fn()
        except PyMongoError as exc:
            raise StoreUnavailable("Transcript store (MongoDB) is unavailable") from exc

    def ensure_indexes(self) -> None:
        self._run(lambda: (self.col.create_index("call_id", unique=True),
                           self.col.create_index([("incident_id", ASCENDING)])))

    def upsert(self, call_id: int, incident_id: int, user_id: int, text: str, language, engine, segments,
               audio_sha256) -> dict:
        existing = self.get(call_id)
        doc = TranscriptDoc(call_id=call_id, incident_id=incident_id, text=text, language=language, engine=engine,
                            segments=segments, audio_sha256=audio_sha256,
                            created_at=existing["created_at"] if existing else now(),
                            created_by=existing["created_by"] if existing else user_id, updated_at=now()).model_dump()
        self._run(lambda: self.col.replace_one({"call_id": call_id}, dict(doc), upsert=True))
        return doc

    def get(self, call_id: int) -> dict | None:
        return self._run(lambda: self.col.find_one({"call_id": call_id}, {"_id": 0}))

    def delete(self, call_id: int) -> bool:
        return self._run(lambda: self.col.delete_one({"call_id": call_id})).deleted_count == 1


_store: TranscriptStore | None = None
_indexes_ready = False


def get_transcript_store() -> TranscriptStore:
    """FastAPI dependency; tests override it. Never raises (an outage surfaces on first use)."""
    global _store, _indexes_ready
    if _store is None:
        _store = TranscriptStore(get_mongo_db())
    if not _indexes_ready:
        try:
            _store.ensure_indexes()
            _indexes_ready = True
        except StoreUnavailable:
            pass
    return _store
