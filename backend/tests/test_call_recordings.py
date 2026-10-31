"""Call audio stored as a MySQL LONGBLOB, and its transcription stored in MongoDB (mongomock here)."""
import hashlib
import json

import mongomock
import pytest
from pymongo.errors import ServerSelectionTimeoutError

from app.main import app
from app.recommendation.store import StoreUnavailable
from app.transcripts import TranscriptStore, get_transcript_store

WAV = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + bytes(range(256)) * 8      # not playable, but a valid header
MP3 = b"ID3" + bytes(200)
BIN = bytes(range(256)) * 40                                                          # every byte value, incl. NUL


def _call(client, dispatcher, incident_id=101):
    res = client.post("/api/calls", headers=dispatcher, json={"incident_id": incident_id, "caller_name": "Test Caller"})
    assert res.status_code == 201, res.text
    return res.json()["call_id"]


def _put(client, headers, call_id, data, mime="audio/wav", **params):
    return client.put(f"/api/calls/{call_id}/recording", headers={**headers, "Content-Type": mime}, content=data,
                      params=params)


def test_upload_download_roundtrip_is_byte_exact(client, dispatcher):
    cid = _call(client, dispatcher)
    data = WAV + BIN
    res = _put(client, dispatcher, cid, data, filename="my call (1).wav")
    assert res.status_code == 200, res.text
    meta = res.json()
    assert meta["has_recording"] is True and meta["audio_size_bytes"] == len(data)
    assert meta["audio_sha256"] == hashlib.sha256(data).hexdigest()
    assert meta["audio_mime_type"] == "audio/wav" and meta["audio_filename"] == "my_call__1_.wav"   # sanitised

    got = client.get(f"/api/calls/{cid}/recording", headers=dispatcher)
    assert got.status_code == 200 and got.content == data
    assert got.headers["content-type"] == "audio/wav" and got.headers["x-content-type-options"] == "nosniff"


def test_blob_never_leaks_into_json_responses(client, dispatcher):
    cid = _call(client, dispatcher)
    assert _put(client, dispatcher, cid, WAV).status_code == 200
    for path in (f"/api/calls/{cid}", "/api/calls?incident_id=101", "/api/incidents/101/calls"):
        res = client.get(path, headers=dispatcher)
        assert res.status_code == 200, path
        assert "audio_recording" not in res.text, path
    row = next(c for c in client.get("/api/incidents/101/calls", headers=dispatcher).json()["data"] if c["call_id"] == cid)
    assert row["has_recording"] is True


def test_call_without_recording(client, dispatcher):
    cid = _call(client, dispatcher)
    assert client.get(f"/api/calls/{cid}", headers=dispatcher).json()["has_recording"] is False
    assert client.get(f"/api/calls/{cid}/recording", headers=dispatcher).status_code == 404


def test_validation(client, dispatcher, monkeypatch):
    cid = _call(client, dispatcher)
    assert _put(client, dispatcher, cid, b"hello", mime="text/plain").status_code == 415
    assert _put(client, dispatcher, cid, b"", mime="audio/wav").status_code == 400
    assert _put(client, dispatcher, cid, b"this is not a wav file at all", mime="audio/wav").status_code == 400
    assert _put(client, dispatcher, cid, WAV, mime="audio/mpeg").status_code == 400          # content/type mismatch
    assert _put(client, dispatcher, cid, MP3, mime="audio/mpeg").status_code == 200
    assert _put(client, dispatcher, 999999, WAV).status_code == 404
    from app.routers import calls as calls_module
    monkeypatch.setattr(calls_module, "settings", type("S", (), {"max_recording_mb": 0})())
    big = _put(client, dispatcher, cid, WAV)
    assert big.status_code == 413 and big.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_replace_recording(client, dispatcher):
    cid = _call(client, dispatcher)
    _put(client, dispatcher, cid, WAV)
    second = _put(client, dispatcher, cid, MP3, mime="audio/mpeg").json()
    assert second["audio_mime_type"] == "audio/mpeg" and second["audio_size_bytes"] == len(MP3)
    assert client.get(f"/api/calls/{cid}/recording", headers=dispatcher).content == MP3


def test_roles(client, dispatcher, responder, admin):
    cid = _call(client, dispatcher)
    _put(client, dispatcher, cid, WAV)
    assert _put(client, responder, cid, WAV).status_code == 403
    assert client.get(f"/api/calls/{cid}/recording", headers=responder).status_code == 403
    assert client.get(f"/api/calls/{cid}/recording").status_code == 401
    assert client.delete(f"/api/calls/{cid}/recording", headers=dispatcher).status_code == 403
    assert client.delete(f"/api/calls/{cid}/recording", headers=admin).status_code == 204
    assert client.delete(f"/api/calls/{cid}/recording", headers=admin).status_code == 404
    assert client.get(f"/api/calls/{cid}", headers=dispatcher).json()["has_recording"] is False


def test_database_constraint_rejects_audio_without_metadata():
    import pymysql
    from conftest import mysql_as
    conn = mysql_as("DB_ADMIN")
    with conn.cursor() as cur, pytest.raises(pymysql.err.MySQLError) as exc:
        cur.execute("UPDATE calls SET audio_recording = %s WHERE call_id = 1001", (b"x",))
    assert exc.value.args[0] == 3819                        # CHECK constraint chk_calls_audio_meta
    conn.close()


# ---------------------------------------------------------------- transcription in MongoDB
@pytest.fixture
def tstore():
    s = TranscriptStore(mongomock.MongoClient()["erms_test"])
    s.ensure_indexes()
    app.dependency_overrides[get_transcript_store] = lambda: s
    yield s
    app.dependency_overrides.pop(get_transcript_store, None)


SEGMENTS = [{"start": 0.0, "end": 2.5, "text": "There is smoke on the second floor."},
            {"start": 2.5, "end": 4.0, "text": "Please hurry.", "speaker": "caller"}]


def test_transcription_create_read_update_delete(client, dispatcher, admin, tstore):
    cid = _call(client, dispatcher)
    _put(client, dispatcher, cid, WAV)
    sha = hashlib.sha256(WAV).hexdigest()
    body = {"text": "There is smoke on the second floor. Please hurry.", "language": "en", "engine": "some-stt-model",
            "segments": SEGMENTS}
    created = client.put(f"/api/calls/{cid}/transcription", headers=dispatcher, json=body)
    assert created.status_code == 200, created.text
    doc = created.json()
    assert doc["call_id"] == cid and doc["incident_id"] == 101 and doc["audio_sha256"] == sha
    assert len(doc["segments"]) == 2

    got = client.get(f"/api/calls/{cid}/transcription", headers=dispatcher).json()
    assert got["text"].startswith("There is smoke") and got["matches_current_recording"] is True

    updated = client.put(f"/api/calls/{cid}/transcription", headers=dispatcher, json={**body, "text": "Corrected text."})
    assert updated.json()["text"] == "Corrected text." and updated.json()["created_at"] == doc["created_at"]
    assert tstore.col.count_documents({"call_id": cid}) == 1                   # upsert, not a duplicate

    _put(client, dispatcher, cid, MP3, mime="audio/mpeg")                      # audio replaced afterwards
    assert client.get(f"/api/calls/{cid}/transcription", headers=dispatcher).json()["matches_current_recording"] is False

    assert client.delete(f"/api/calls/{cid}/transcription", headers=dispatcher).status_code == 403
    assert client.delete(f"/api/calls/{cid}/transcription", headers=admin).status_code == 204
    assert client.get(f"/api/calls/{cid}/transcription", headers=dispatcher).status_code == 404


def test_transcription_validation_and_roles(client, dispatcher, responder, tstore):
    cid = _call(client, dispatcher)
    url = f"/api/calls/{cid}/transcription"
    assert client.put(url, headers=dispatcher, json={"text": ""}).status_code == 422
    assert client.put(url, headers=dispatcher, json={"text": "x", "segments": [{"start": -1, "end": 1, "text": "t"}]}).status_code == 422
    assert client.put(url, headers=dispatcher, json={"text": "x", "unknown": 1}).status_code == 422
    assert client.put("/api/calls/999999/transcription", headers=dispatcher, json={"text": "x"}).status_code == 404
    assert client.put(url, headers=responder, json={"text": "x"}).status_code == 403
    assert client.get(url, headers=dispatcher).status_code == 404            # call exists, no transcription yet


def test_transcription_without_audio_is_allowed(client, dispatcher, tstore):
    cid = _call(client, dispatcher)
    doc = client.put(f"/api/calls/{cid}/transcription", headers=dispatcher, json={"text": "typed notes"}).json()
    assert doc["audio_sha256"] is None


class _Broken:
    def __getattr__(self, name):
        def fail(*a, **k):
            raise ServerSelectionTimeoutError("down")
        return fail


def test_mongo_down_is_reported_and_mysql_unaffected(client, dispatcher):
    s = TranscriptStore({"call_transcripts": _Broken()})
    app.dependency_overrides[get_transcript_store] = lambda: s
    try:
        cid = _call(client, dispatcher)
        assert _put(client, dispatcher, cid, WAV).status_code == 200            # audio goes to MySQL regardless
        res = client.put(f"/api/calls/{cid}/transcription", headers=dispatcher, json={"text": "x"})
        assert res.status_code == 503 and res.json()["error"]["code"] == "RECOMMENDATION_STORE_UNAVAILABLE"
        assert "Transcript store" in res.json()["error"]["message"]
    finally:
        app.dependency_overrides.pop(get_transcript_store, None)
