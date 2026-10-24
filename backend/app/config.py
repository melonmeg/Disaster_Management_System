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

    def db_account(self, account: str) -> tuple[str, str]:
        """MySQL credentials for one of: auth, admin, dispatcher, responder."""
        prefix = f"DB_{account.upper()}"
        return _required(f"{prefix}_USER"), _required(f"{prefix}_PASSWORD")


settings = Settings()
