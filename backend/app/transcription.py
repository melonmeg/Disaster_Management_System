"""Speech-to-text for call recordings, using Groq's Whisper endpoint (OpenAI-compatible audio API).

POST {STT_BASE_URL}/audio/transcriptions  (multipart: file, model, response_format=verbose_json)
The audio is sent to a third-party service; the API key is only ever sent as a bearer header and is never logged.
Any failure becomes a TranscriptionError with a safe message (no URL, key or provider response body).
"""
import logging

import httpx

from .config import settings
from .errors import ApiError

log = logging.getLogger("erm.stt")


class TranscriptionError(ApiError):
    def __init__(self, message: str, status: int = 502, code: str = "TRANSCRIPTION_FAILED"):
        super().__init__(status, code, message)


class GroqTranscriber:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 120.0):
        self.base_url, self.api_key, self.model, self.timeout = base_url.rstrip("/"), api_key, model, timeout

    @property
    def engine(self) -> str:
        return f"groq/{self.model}"

    def transcribe(self, audio: bytes, filename: str, mime: str, language: str | None = None) -> dict:
        """Returns {text, language, segments:[{start,end,text}]}."""
        data = {"model": self.model, "response_format": "verbose_json", "temperature": "0"}
        if language:
            data["language"] = language
        try:
            res = httpx.post(f"{self.base_url}/audio/transcriptions",
                             headers={"Authorization": f"Bearer {self.api_key}"},
                             data=data, files={"file": (filename, audio, mime)}, timeout=self.timeout)
        except httpx.HTTPError as exc:
            log.warning("STT request failed: %s", type(exc).__name__)
            raise TranscriptionError("The speech-to-text service could not be reached") from exc
        if res.status_code in (401, 403):
            raise TranscriptionError("The speech-to-text service rejected the API key", 502, "TRANSCRIPTION_AUTH_FAILED")
        if res.status_code == 404:
            raise TranscriptionError(f"Speech-to-text model '{self.model}' is not available for this key "
                                     "(check STT_MODEL)", 502, "TRANSCRIPTION_MODEL_UNAVAILABLE")
        if res.status_code == 413:
            raise TranscriptionError("The recording is too large for the speech-to-text service", 413, "TRANSCRIPTION_TOO_LARGE")
        if res.status_code == 429:
            raise TranscriptionError("The speech-to-text service is rate limiting requests; try again shortly", 503,
                                     "TRANSCRIPTION_RATE_LIMITED")
        if res.status_code >= 400:
            log.warning("STT service returned HTTP %s", res.status_code)
            raise TranscriptionError(f"The speech-to-text service returned an error (HTTP {res.status_code})")
        try:
            body = res.json()
            text = (body.get("text") or "").strip()
        except (ValueError, AttributeError) as exc:
            raise TranscriptionError("The speech-to-text service returned an unreadable response") from exc
        segments = []
        for s in body.get("segments") or []:
            seg_text = str(s.get("text", "")).strip()
            if seg_text and isinstance(s.get("start"), (int, float)) and isinstance(s.get("end"), (int, float)):
                segments.append({"start": max(0.0, float(s["start"])), "end": max(0.0, float(s["end"])), "text": seg_text[:5000]})
        return {"text": text, "language": body.get("language"), "segments": segments[:5000]}


def get_transcriber() -> GroqTranscriber:
    """FastAPI dependency; tests override it."""
    if not settings.stt_enabled:
        raise TranscriptionError("Automatic transcription is turned off (STT_ENABLED=false)", 503, "TRANSCRIPTION_NOT_CONFIGURED")
    key = settings.stt_api_key or settings.llm_api_key
    if not key:
        raise TranscriptionError("Automatic transcription is not configured: set STT_API_KEY (a Groq key) in backend/.env",
                                 503, "TRANSCRIPTION_NOT_CONFIGURED")
    return GroqTranscriber(settings.stt_base_url, key, settings.stt_model)
