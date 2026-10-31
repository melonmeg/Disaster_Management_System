"""Settings loaded from environment variables (backend/.env in development)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable {name} (see backend/.env.example)")
    return value


@dataclass(frozen=True)
class Settings:
    db_host: str = field(default_factory=lambda: os.environ.get("DB_HOST", "127.0.0.1"))
    db_port: int = field(default_factory=lambda: int(os.environ.get("DB_PORT", "3306")))
    db_name: str = field(default_factory=lambda: os.environ.get("DB_NAME", "emergency_response_management"))
    jwt_secret: str = field(default_factory=lambda: _required("JWT_SECRET"))
    access_token_minutes: int = field(default_factory=lambda: int(os.environ.get("ACCESS_TOKEN_MINUTES", "30")))
    refresh_token_days: int = field(default_factory=lambda: int(os.environ.get("REFRESH_TOKEN_DAYS", "7")))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    )

    # --- geocoding: Mappls (MapmyIndia) forward geocoding API ---
    mappls_api_key: str = field(default_factory=lambda: os.environ.get("MAPPLS_API_KEY", ""))
    mappls_geocode_url: str = field(default_factory=lambda: os.environ.get("MAPPLS_GEOCODE_URL", "https://search.mappls.com/search/address/geocode"))
    mappls_region: str = field(default_factory=lambda: os.environ.get("MAPPLS_REGION", ""))   # country code; optional for India
    geocoder_ambiguity_km: float = field(default_factory=lambda: float(os.environ.get("GEOCODER_AMBIGUITY_KM", "5")))
    max_recording_mb: int = field(default_factory=lambda: int(os.environ.get("MAX_RECORDING_MB", "25")))
    # --- MongoDB (recommendation_history, call_transcripts) ---
    mongodb_uri: str = field(default_factory=lambda: os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017"))
    mongodb_db: str = field(default_factory=lambda: os.environ.get("MONGODB_DB", "erms"))
    # --- speech-to-text for call recordings: Groq Whisper (OpenAI-compatible audio API) ---
    stt_base_url: str = field(default_factory=lambda: os.environ.get("STT_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"))
    stt_api_key: str = field(default_factory=lambda: os.environ.get("STT_API_KEY", ""))   # falls back to LLM_API_KEY
    stt_model: str = field(default_factory=lambda: os.environ.get("STT_MODEL", "whisper-large-v3-turbo"))
    stt_enabled: bool = field(default_factory=lambda: os.environ.get("STT_ENABLED", "true").lower() == "true")
    # --- operational log (MongoDB `operational_logs`) ---
    oplog_enabled: bool = field(default_factory=lambda: os.environ.get("OPLOG_ENABLED", "true").lower() == "true")
    oplog_retention_days: int = field(default_factory=lambda: int(os.environ.get("OPLOG_RETENTION_DAYS", "90")))
    # --- LLM explanations (optional): any OpenAI-compatible chat-completions API, e.g. Llama API ---
    llm_base_url: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL", "").rstrip("/"))
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", ""))
    llm_enabled: bool = field(default_factory=lambda: os.environ.get("LLM_ENABLED", "true").lower() == "true")
    # --- recommendation scoring weights, e.g. "capability=0.5,availability=0.2,distance=0.2,resources=0.1" ---
    reco_weights: str = field(default_factory=lambda: os.environ.get("RECO_WEIGHTS", ""))

    def db_account(self, account: str) -> tuple[str, str]:
        """MySQL credentials for one of: auth, admin, dispatcher, responder."""
        prefix = f"DB_{account.upper()}"
        return _required(f"{prefix}_USER"), _required(f"{prefix}_PASSWORD")


settings = Settings()
