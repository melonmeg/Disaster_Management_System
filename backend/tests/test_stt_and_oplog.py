"""Groq transcription of call recordings (fake provider) and the MongoDB operational log (mongomock)."""
import httpx
import mongomock
import pytest
from pymongo.errors import ServerSelectionTimeoutError

from app import oplog
from app.main import app
from app.oplog import OpLogStore
from app.transcription import GroqTranscriber, TranscriptionError, get_transcriber
from app.transcripts import TranscriptStore, get_transcript_store

WAV = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + bytes(range(256)) * 4


class FakeSTT:
    engine = "groq/fake-whisper"

    def __init__(self):
        self.result, self.error, self.calls = None, None, []

    def transcribe(self, audio, filename, mime, language=None):
        self.calls.append((len(audio), filename, mime, language))
        if self.error:
            raise self.error
        return self.result or {"text": "Smoke on the second floor.", "language": "en",
                               "segments": [{"start": 0.0, "end": 2.5, "text": "Smoke on the second floor."}]}


@pytest.fixture
def stt():
    fake = FakeSTT()
    store = TranscriptStore(mongomock.MongoClient()["erms_stt"])
    app.dependency_overrides[get_transcriber] = lambda: fake
    app.dependency_overrides[get_transcript_store] = lambda: store
    yield fake
    app.dependency_overrides.pop(get_transcriber, None)
    app.dependency_overrides.pop(get_transcript_store, None)


def _call_with_audio(client, dispatcher):
    cid = client.post("/api/calls", headers=dispatcher, json={"incident_id": 101, "caller_name": "STT"}).json()["call_id"]
    res = client.put(f"/api/calls/{cid}/recording", headers={**dispatcher, "Content-Type": "audio/wav"}, content=WAV)
    assert res.status_code == 200, res.text
    return cid


def test_transcribe_saves_groq_result_in_mongo(client, dispatcher, stt):
    cid = _call_with_audio(client, dispatcher)
    res = client.post(f"/api/calls/{cid}/transcribe?language=en", headers=dispatcher)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["text"] == "Smoke on the second floor." and body["engine"] == "groq/fake-whisper"
    assert body["segments"][0]["end"] == 2.5 and body["matches_current_recording"] is True
    assert stt.calls == [(len(WAV), f"call-{cid}.wav", "audio/wav", "en")]
    got = client.get(f"/api/calls/{cid}/transcription", headers=dispatcher)
    assert got.status_code == 200 and got.json()["text"] == body["text"]


def test_transcribe_without_recording_is_409(client, dispatcher, stt):
    cid = client.post("/api/calls", headers=dispatcher, json={"incident_id": 101}).json()["call_id"]
    res = client.post(f"/api/calls/{cid}/transcribe", headers=dispatcher)
    assert res.status_code == 409 and res.json()["error"]["code"] == "NO_RECORDING"
    assert stt.calls == []


def test_transcribe_provider_failure_is_reported_and_nothing_saved(client, dispatcher, stt):
    cid = _call_with_audio(client, dispatcher)
    stt.error = TranscriptionError("The speech-to-text service could not be reached")
    res = client.post(f"/api/calls/{cid}/transcribe", headers=dispatcher)
    assert res.status_code == 502 and res.json()["error"]["code"] == "TRANSCRIPTION_FAILED"
    assert client.get(f"/api/calls/{cid}/transcription", headers=dispatcher).status_code == 404


def test_transcribe_empty_speech_and_roles(client, dispatcher, responder, stt):
    cid = _call_with_audio(client, dispatcher)
    stt.result = {"text": "", "language": "en", "segments": []}
    assert client.post(f"/api/calls/{cid}/transcribe", headers=dispatcher).json()["error"]["code"] == "NO_SPEECH"
    assert client.post(f"/api/calls/{cid}/transcribe", headers=responder).status_code == 403
    assert client.post(f"/api/calls/{cid}/transcribe").status_code == 401


def test_transcribe_not_configured_gives_503(client, dispatcher):
    cid = _call_with_audio(client, dispatcher)
    res = client.post(f"/api/calls/{cid}/transcribe", headers=dispatcher)      # STT_ENABLED=false in tests
    assert res.status_code == 503 and res.json()["error"]["code"] == "TRANSCRIPTION_NOT_CONFIGURED"


# ---- the Groq HTTP client itself, against a mocked transport (no network)
def _groq(handler, monkeypatch):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Client(transport=transport).post(url, **kw))
    return GroqTranscriber("https://stt.example/v1", "secret-key", "whisper-x")


def test_groq_client_parses_verbose_json(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], request.content
        return httpx.Response(200, json={"text": " hello ", "language": "english", "segments": [
            {"start": 0, "end": 1.2, "text": " hello "}, {"start": 1.2, "end": 2, "text": "  "},
            {"start": "x", "end": 3, "text": "bad"}]})
    out = _groq(handler, monkeypatch).transcribe(WAV, "a.wav", "audio/wav", "en")
    assert out == {"text": "hello", "language": "english", "segments": [{"start": 0.0, "end": 1.2, "text": "hello"}]}
    assert seen["url"] == "https://stt.example/v1/audio/transcriptions" and seen["auth"] == "Bearer secret-key"
    assert b'name="model"' in seen["body"] and b"whisper-x" in seen["body"] and b"verbose_json" in seen["body"]


@pytest.mark.parametrize("status,code", [(401, "TRANSCRIPTION_AUTH_FAILED"), (404, "TRANSCRIPTION_MODEL_UNAVAILABLE"),
                                         (413, "TRANSCRIPTION_TOO_LARGE"), (429, "TRANSCRIPTION_RATE_LIMITED"),
                                         (500, "TRANSCRIPTION_FAILED")])
def test_groq_client_error_mapping_hides_provider_details(monkeypatch, status, code):
    t = _groq(lambda r: httpx.Response(status, json={"error": {"message": "secret-key leaked?"}}), monkeypatch)
    with pytest.raises(TranscriptionError) as e:
        t.transcribe(WAV, "a.wav", "audio/wav")
    assert e.value.code == code and "secret-key" not in e.value.message


def test_groq_client_network_error(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("no route", request=request)
    with pytest.raises(TranscriptionError) as e:
        _groq(boom, monkeypatch).transcribe(WAV, "a.wav", "audio/wav")
    assert e.value.status == 502


# ---------------------------------------------------------------- operational log
@pytest.fixture
def logstore(monkeypatch):
    s = OpLogStore(mongomock.MongoClient()["erms_oplog"], retention_days=30)
    monkeypatch.setattr(oplog, "get_oplog", lambda: s)
    return s


def test_oplog_records_changes_and_failures_but_not_reads(client, dispatcher, logstore):
    client.get("/api/incidents", headers=dispatcher)                                   # successful read: skipped
    client.get("/api/health")                                                          # skipped
    created = client.post("/api/incidents", headers=dispatcher, json={
        "incident_type": "Log Test", "severity": "LOW", "location": "Nowhere Road"})
    assert created.status_code == 201
    client.get("/api/incidents/999999", headers=dispatcher)                            # failed read: logged
    client.post("/api/auth/login", json={"username": "nobody", "password": "wrong-password-1"})
    rows = list(logstore.col.find({}, {"_id": 0}).sort("ts", 1))
    assert sorted((r["method"], r["status"]) for r in rows) == [("GET", 404), ("POST", 201), ("POST", 401)]
    post = next(r for r in rows if r["status"] == 201)
    assert post["path"] == "/api/incidents" and post["role"] == "dispatcher" and isinstance(post["user_id"], int)
    miss = next(r for r in rows if r["status"] == 404)
    assert post["level"] == "INFO" and miss["level"] == "WARNING" and miss["route"] == "/api/incidents/{incident_id}"
    assert next(r for r in rows if r["status"] == 401)["user_id"] is None
    flat = str(rows)
    assert "wrong-password-1" not in flat and "Log Test" not in flat and "Bearer" not in flat   # no bodies, no secrets


def test_oplog_ttl_index_and_api_filters(client, dispatcher, admin, logstore):
    client.post("/api/incidents", headers=dispatcher, json={"incident_type": "A", "severity": "LOW", "location": "L1"})
    client.get("/api/incidents/999999", headers=dispatcher)
    assert any(v.get("expireAfterSeconds") == 30 * 86400 for v in logstore.col.index_information().values())
    res = client.get("/api/logs?status_min=400", headers=admin)
    assert res.status_code == 200 and {r["status"] for r in res.json()["data"]} == {404}
    res = client.get("/api/logs?method=POST&path_prefix=/api/incidents", headers=admin).json()
    assert res["pagination"]["total"] >= 1 and all(r["method"] == "POST" for r in res["data"])
    assert client.get("/api/logs?method=TRACE", headers=admin).status_code == 422


def test_logs_endpoint_is_admin_only(client, dispatcher, responder, logstore):
    assert client.get("/api/logs", headers=dispatcher).status_code == 403
    assert client.get("/api/logs", headers=responder).status_code == 403
    assert client.get("/api/logs").status_code == 401


def test_logs_endpoint_when_disabled(client, admin):
    res = client.get("/api/logs", headers=admin)                                       # OPLOG_ENABLED=false in tests
    assert res.status_code == 503 and res.json()["error"]["code"] == "OPLOG_DISABLED"


def test_oplog_outage_never_breaks_requests_and_backs_off(client, dispatcher, monkeypatch):
    class Down:
        inserts = 0

        def create_index(self, *a, **k):
            raise ServerSelectionTimeoutError("down")

        def insert_one(self, *a, **k):
            Down.inserts += 1
            raise ServerSelectionTimeoutError("down")
    s = OpLogStore({"operational_logs": Down()})
    monkeypatch.setattr(oplog, "get_oplog", lambda: s)
    for _ in range(3):
        assert client.get("/api/incidents/999999", headers=dispatcher).status_code == 404   # still answered normally
    assert Down.inserts == 0 and s.record({"x": 1}) is False        # index creation failed, then writes are suspended
