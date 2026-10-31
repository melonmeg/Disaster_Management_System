"""/api/calls — emergency call records (MySQL `calls` table). Not available to responders.



The structured call row (caller, priority, incident link) lives in MySQL. Rich, unstructured

data about a call (audio metadata, transcript segments, NLP tags) belongs to the MongoDB side;

those documents reference `call_id` / `incident_id` from here (see docs/API.md, "Integration").

"""

import hashlib

import re

from datetime import datetime



from fastapi import APIRouter, Depends, Query, Request, Response

from fastapi.concurrency import run_in_threadpool

from pydantic import Field



from ..common import Page, paginated, require_row, updates_from

from ..config import settings

from ..db import Database

from ..errors import ApiError, not_found

from ..recommendation.store import now

from ..schemas import Body, CallIn, CallStatus, CallUpdate, Severity

from ..security import CurrentUser, get_db, require_roles

from ..transcription import GroqTranscriber, get_transcriber

from ..transcripts import Segment, TranscriptStore, get_transcript_store



router = APIRouter(prefix="/calls", tags=["calls"])

staff = require_roles("admin", "dispatcher")



# Never `c.*`: that would pull the audio BLOB into every list/JSON response.

CALL_COLUMNS = ("c.call_id, c.received_by, c.status, c.transcript, c.received_at, c.caller_name, c.priority, "

                "c.caller_phone, c.location, c.incident_id, c.audio_filename, c.audio_mime_type, "

                "c.audio_size_bytes, c.audio_sha256, c.audio_uploaded_at, (c.audio_recording IS NOT NULL) AS has_recording")

SELECT = (f"SELECT {CALL_COLUMNS}, CONCAT_WS(' ', r.first_name, r.last_name) AS received_by_name "

          "FROM calls c JOIN responders r ON r.responder_id = c.received_by")





def fetch_call(db: Database, call_id: int) -> dict:

    call = require_row(db, f"{SELECT} WHERE c.call_id = %s", (call_id,), "Call")

    call["has_recording"] = bool(call["has_recording"])

    return call





@router.get("")

def list_calls(incident_id: int | None = None, status: CallStatus | None = None, priority: Severity | None = None,

               received_from: datetime | None = None, received_to: datetime | None = None,

               page: Page = Depends(), _: CurrentUser = Depends(staff), db: Database = Depends(get_db)):

    where, params = [], []

    for column, value in (("c.incident_id", incident_id), ("c.status", status), ("c.priority", priority)):

        if value is not None:

            where.append(f"{column} = %s"); params.append(value)

    if received_from:

        where.append("c.received_at >= %s"); params.append(received_from)

    if received_to:

        where.append("c.received_at <= %s"); params.append(received_to)

    result = paginated(db, SELECT, where, params, page, "c.received_at DESC, c.call_id DESC")

    for row in result["data"]:

        row["has_recording"] = bool(row["has_recording"])

    return result





@router.get("/{call_id}")

def get_call(call_id: int, _: CurrentUser = Depends(staff), db: Database = Depends(get_db)):

    return fetch_call(db, call_id)





@router.post("", status_code=201)

def create_call(body: CallIn, user: CurrentUser = Depends(staff), db: Database = Depends(get_db)):

    """Log a call against an existing incident (`incident_id`) or open a new incident

    (`incident`) and the call in ONE transaction: if the call insert fails, the incident is rolled back."""

    if (body.incident_id is None) == (body.incident is None):

        raise ApiError(400, "VALIDATION_ERROR", "Send exactly one of incident_id or incident")

    received_by = body.received_by or user.responder_id

    if received_by is None:

        raise ApiError(400, "VALIDATION_ERROR", "received_by is required (your login has no responder record)")



    with db.transaction():

        incident_id = body.incident_id

        if body.incident is not None:

            incident_id, _ = db.execute(

                "INSERT INTO incidents (incident_type, severity, location) VALUES (%s, %s, %s)",

                (body.incident.incident_type, body.incident.severity, body.incident.location))

        elif db.one("SELECT status FROM incidents WHERE incident_id = %s", (incident_id,)) is None:

            raise ApiError(400, "INVALID_REFERENCE", f"Incident {incident_id} does not exist")

        call_id, _ = db.execute(

            "INSERT INTO calls (received_by, status, transcript, caller_name, priority, caller_phone, location, "

            "incident_id) VALUES (%s, 'RECEIVED', %s, %s, %s, %s, %s, %s)",

            (received_by, body.transcript, body.caller_name, body.priority, body.caller_phone,

             body.location or (body.incident.location if body.incident else None), incident_id))

    return fetch_call(db, call_id)





@router.patch("/{call_id}")

def update_call(call_id: int, body: CallUpdate, _: CurrentUser = Depends(staff), db: Database = Depends(get_db)):

    fetch_call(db, call_id)

    changes = updates_from(body, {"status", "priority", "transcript"})

    if changes:

        db.execute(f"UPDATE calls SET {', '.join(f'{k} = %s' for k in changes)} WHERE call_id = %s",

                   [*changes.values(), call_id])

    return fetch_call(db, call_id)





# ---------- audio recording (MySQL LONGBLOB) ----------

def _is_mp3(d: bytes) -> bool:

    return d[:3] == b"ID3" or (len(d) > 1 and d[0] == 0xFF and d[1] & 0xE0 == 0xE0)





# declared type -> check of the file's first bytes, so an arbitrary file cannot be stored as "audio"

AUDIO_SIGNATURES = {

    "audio/mpeg": _is_mp3,

    "audio/wav": lambda d: d[:4] == b"RIFF" and d[8:12] == b"WAVE",

    "audio/x-wav": lambda d: d[:4] == b"RIFF" and d[8:12] == b"WAVE",

    "audio/ogg": lambda d: d[:4] == b"OggS",

    "audio/flac": lambda d: d[:4] == b"fLaC",

    "audio/mp4": lambda d: d[4:8] == b"ftyp",

    "audio/x-m4a": lambda d: d[4:8] == b"ftyp",

    "audio/webm": lambda d: d[:4] == bytes([0x1A, 0x45, 0xDF, 0xA3]),
}

EXTENSIONS = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wave": "wav", "audio/wav": "wav", "audio/x-wav": "wav", "audio/ogg": "ogg", "audio/flac": "flac",

              "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/webm": "webm"}





async def _read_limited(request: Request, limit: int) -> bytes:

    declared = request.headers.get("content-length")

    if declared and declared.isdigit() and int(declared) > limit:

        raise ApiError(413, "PAYLOAD_TOO_LARGE", f"Recording exceeds the {limit // (1024 * 1024)} MB limit")

    chunks, total = [], 0

    async for chunk in request.stream():

        total += len(chunk)

        if total > limit:

            raise ApiError(413, "PAYLOAD_TOO_LARGE", f"Recording exceeds the {limit // (1024 * 1024)} MB limit")

        chunks.append(chunk)

    return b"".join(chunks)





@router.put("/{call_id}/recording")

async def upload_recording(call_id: int, request: Request, filename: str | None = Query(None, max_length=255),

                           _: CurrentUser = Depends(staff), db: Database = Depends(get_db)):

    """Store the call's audio. Send the raw file as the request body with its audio Content-Type

    (audio/mpeg, audio/wav, audio/ogg, audio/flac, audio/mp4, audio/x-m4a, audio/webm). Replaces an existing one."""

    mime = request.headers.get("content-type", "").split(";")[0].strip().lower()

    if mime not in AUDIO_SIGNATURES:

        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", f"Unsupported content type; use one of: {', '.join(sorted(AUDIO_SIGNATURES))}")

    await run_in_threadpool(fetch_call, db, call_id)               # 404 before reading a large body

    data = await _read_limited(request, settings.max_recording_mb * 1024 * 1024)

    if not data:

        raise ApiError(400, "VALIDATION_ERROR", "Empty recording")

    if not AUDIO_SIGNATURES[mime](data):

        raise ApiError(400, "VALIDATION_ERROR", f"The file content does not look like {mime}")

    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename or "")[:255] or f"call-{call_id}.{EXTENSIONS[mime]}"



    def store():

        db.execute("UPDATE calls SET audio_recording = %s, audio_mime_type = %s, audio_filename = %s, "

                   "audio_size_bytes = %s, audio_sha256 = %s, audio_uploaded_at = NOW() WHERE call_id = %s",

                   (data, mime, safe_name, len(data), hashlib.sha256(data).hexdigest(), call_id))

        return fetch_call(db, call_id)

    return await run_in_threadpool(store)





@router.get("/{call_id}/recording")

def download_recording(call_id: int, _: CurrentUser = Depends(staff), db: Database = Depends(get_db)):

    row = require_row(db, "SELECT audio_recording, audio_mime_type, audio_filename FROM calls WHERE call_id = %s",

                      (call_id,), "Call")

    if row["audio_recording"] is None:

        raise not_found("Recording")

    return Response(content=row["audio_recording"], media_type=row["audio_mime_type"],

                    headers={"Content-Disposition": f'inline; filename="{row["audio_filename"]}"',

                             "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})





@router.delete("/{call_id}/recording", status_code=204, dependencies=[Depends(require_roles("admin"))])

def delete_recording(call_id: int, db: Database = Depends(get_db)):

    """Admin only: remove the audio (the call row and any stored transcription stay)."""

    if not fetch_call(db, call_id)["has_recording"]:

        raise not_found("Recording")

    db.execute("UPDATE calls SET audio_recording = NULL, audio_mime_type = NULL, audio_filename = NULL, "

               "audio_size_bytes = NULL, audio_sha256 = NULL, audio_uploaded_at = NULL WHERE call_id = %s", (call_id,))





# ---------- transcription of the recording (MongoDB call_transcripts) ----------

class TranscriptionIn(Body):

    text: str = Field(min_length=1, max_length=200_000)

    language: str | None = Field(None, max_length=20)

    engine: str | None = Field(None, max_length=100, description="speech-to-text model/tool that produced it")

    segments: list[Segment] = Field(default_factory=list, max_length=5000)





@router.put("/{call_id}/transcription")

def put_transcription(call_id: int, body: TranscriptionIn, user: CurrentUser = Depends(staff),

                      db: Database = Depends(get_db), store: TranscriptStore = Depends(get_transcript_store)):

    """Save (or replace) the transcription of this call's audio in MongoDB. MySQL is not changed."""

    call = fetch_call(db, call_id)

    return store.upsert(call_id, call["incident_id"], user.user_id, body.text, body.language, body.engine,

                        [s.model_dump() for s in body.segments], call["audio_sha256"])





@router.post("/{call_id}/transcribe")
def transcribe_recording(call_id: int, language: str | None = Query(None, max_length=10, pattern="^[A-Za-z-]+$"),
                         user: CurrentUser = Depends(staff), db: Database = Depends(get_db),
                         store: TranscriptStore = Depends(get_transcript_store),
                         stt: GroqTranscriber = Depends(get_transcriber)):
    """Transcribe the stored recording with Groq (Whisper) and save the result in MongoDB (replaces an older one).
    The audio is sent to the speech-to-text provider. MySQL is not changed."""
    row = require_row(db, "SELECT call_id, incident_id, audio_recording, audio_mime_type, audio_filename, audio_sha256 "
                          "FROM calls WHERE call_id = %s", (call_id,), "Call")
    if row["audio_recording"] is None:
        raise ApiError(409, "NO_RECORDING", "This call has no recording to transcribe")
    result = stt.transcribe(row["audio_recording"], row["audio_filename"] or f"call-{call_id}", row["audio_mime_type"], language)
    if not result["text"]:
        raise ApiError(422, "NO_SPEECH", "No speech was detected in this recording")
    doc = store.upsert(call_id, row["incident_id"], user.user_id, result["text"], result["language"], stt.engine,
                       result["segments"], row["audio_sha256"])
    doc["matches_current_recording"] = True
    return doc


@router.get("/{call_id}/transcription")

def get_transcription(call_id: int, _: CurrentUser = Depends(staff), db: Database = Depends(get_db),

                      store: TranscriptStore = Depends(get_transcript_store)):

    call = fetch_call(db, call_id)

    doc = store.get(call_id)

    if doc is None:

        raise not_found("Transcription")

    doc["matches_current_recording"] = doc["audio_sha256"] == call["audio_sha256"]

    return doc





@router.delete("/{call_id}/transcription", status_code=204, dependencies=[Depends(require_roles("admin"))])

def delete_transcription(call_id: int, store: TranscriptStore = Depends(get_transcript_store)):

    if not store.delete(call_id):

        raise not_found("Transcription")

