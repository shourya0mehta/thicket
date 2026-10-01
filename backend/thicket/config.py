"""Runtime configuration, read once from the environment.

Every setting maps to an upper-case environment variable of the same name
(for example ``max_upload_bytes`` is ``MAX_UPLOAD_BYTES``). All of them are
documented in ``backend/.env.example``.

Ports live here and nowhere else: the API listens on :data:`API_PORT` and the
Vite dev server on :data:`FRONTEND_DEV_PORT`.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from thicket import __version__

API_PORT = 8000
FRONTEND_DEV_PORT = 5173

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = BACKEND_DIR / "var"
DEFAULT_ORIGINS = [
    f"http://localhost:{FRONTEND_DEV_PORT}",
    f"http://127.0.0.1:{FRONTEND_DEV_PORT}",
]
MB = 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        validate_default=True,
    )

    # Deployment
    environment: Literal["development", "test", "production"] = "development"
    app_version: str = __version__
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    # Storage
    thicket_data_dir: Path = DEFAULT_DATA_DIR
    database_url: str | None = None
    serve_frontend_dir: Path | None = None

    # HTTP
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_ORIGINS)
    )
    rate_limit_per_minute: int = Field(
        30, ge=0, description="POST requests per client IP; 0 disables."
    )
    request_timeout_seconds: float = Field(300.0, gt=0)
    client_ip_header: str | None = Field(
        None,
        description=(
            "Header the edge proxy sets to the client IP (e.g. Fly-Client-IP). When set, "
            "the rate limiter keys on it instead of the connection address."
        ),
    )

    # Upload and audio limits
    max_upload_bytes: int = Field(50 * MB, ge=1024)
    max_audio_duration_seconds: float = Field(600.0, gt=0)
    min_audio_duration_seconds: float = Field(1.0, ge=0)

    # Detection pipeline
    default_decision_threshold: float = Field(0.60, ge=0, le=1)
    raw_threshold: float = Field(0.10, ge=0.01, le=1)
    merge_gap_seconds: float = Field(1.0, ge=0, le=30)
    hop_seconds: float = Field(3.0, ge=0.5, le=3.0)

    # Models
    birdnet_enabled: bool = True
    birdnet_model_dir: Path | None = None
    location_filter: bool = True
    location_filter_threshold: float = Field(0.03, ge=0, le=1)
    frog_insect_enabled: bool = False
    frog_insect_model_path: Path | None = None

    # Retention and workers
    retain_audio: bool = False
    temp_retention_hours: float = Field(1.0, gt=0)
    preview_ttl_minutes: float = Field(60.0, gt=0)
    analysis_timeout_seconds: float = Field(300.0, gt=0)
    worker_concurrency: int = Field(1, ge=1, le=16)
    janitor_interval_seconds: float = Field(600.0, gt=0)

    # Accounts and sign-in (platform)
    auth_mode: Literal["disabled", "dev", "google"] = "disabled"
    session_secret: str | None = Field(
        None,
        description=(
            "Signs session cookies. When unset a random secret is generated once and kept "
            "in <data dir>/session_secret (production logs a warning)."
        ),
    )
    google_client_id: str | None = None
    google_client_secret: str | None = None
    public_base_url: str = f"http://localhost:{API_PORT}"
    frontend_url: str = f"http://localhost:{FRONTEND_DEV_PORT}"
    allowed_signin_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Email
    smtp_host: str | None = None
    smtp_port: int = Field(587, ge=1, le=65535)
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str | None = None
    resend_api_key: str | None = None

    # Alerts, nightly jobs, batches, reports
    alerts_enabled: bool = True
    nightly_jobs_hour_utc: int = Field(6, ge=0, le=23)
    max_batch_files: int = Field(200, ge=1, le=10_000)
    max_batch_bytes: int = Field(2 * 1024 * MB, ge=MB)
    report_logo_path: Path | None = None

    @field_validator("allowed_signin_domains", mode="before")
    @classmethod
    def _split_domains(cls, v: object) -> object:
        if isinstance(v, str):
            text = v.strip()
            if text.startswith("["):
                import json

                v = json.loads(text)
            else:
                v = [d for d in text.split(",")]
        if isinstance(v, list):
            return [str(d).strip().lower().lstrip("@") for d in v if str(d).strip()]
        return v

    @field_validator(
        "session_secret",
        "google_client_id",
        "google_client_secret",
        "smtp_host",
        "smtp_user",
        "smtp_password",
        "email_from",
        "resend_api_key",
        mode="before",
    )
    @classmethod
    def _blank_secret_to_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("public_base_url", "frontend_url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        text = v.strip()
        parts = urlsplit(text)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"Invalid URL {v!r}: expected http(s)://host[:port][/path].")
        return text.rstrip("/")

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            text = v.strip()
            if text.startswith("["):
                import json

                return json.loads(text)
            return [o.strip() for o in text.split(",") if o.strip()]
        return v

    @field_validator("allowed_origins")
    @classmethod
    def _check_origins(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for origin in v:
            if "*" in origin:
                raise ValueError(
                    "ALLOWED_ORIGINS must list explicit origins; wildcards are not allowed."
                )
            parts = urlsplit(origin)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise ValueError(f"Invalid origin {origin!r}: expected scheme://host[:port].")
            if parts.path not in ("", "/") or parts.query or parts.fragment:
                raise ValueError(f"Invalid origin {origin!r}: an origin has no path.")
            out.append(f"{parts.scheme}://{parts.netloc}")
        return out

    @field_validator(
        "thicket_data_dir",
        "serve_frontend_dir",
        "birdnet_model_dir",
        "frog_insect_model_path",
        "report_logo_path",
    )
    @classmethod
    def _absolute(cls, v: Path | None) -> Path | None:
        return v.expanduser().resolve() if v is not None else None

    @field_validator("client_ip_header", mode="before")
    @classmethod
    def _header_name(cls, v: object) -> object:
        if isinstance(v, str):
            name = v.strip()
            if not name:
                return None
            if not all(c.isalnum() or c in "-_" for c in name):
                raise ValueError(f"CLIENT_IP_HEADER {name!r} is not a valid header name.")
            return name.lower()
        return v

    @field_validator("database_url", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator(
        "serve_frontend_dir",
        "birdnet_model_dir",
        "frog_insect_model_path",
        "report_logo_path",
        mode="before",
    )
    @classmethod
    def _blank_path_to_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @model_validator(mode="after")
    def _cross_checks(self) -> Settings:
        for name in (
            "default_decision_threshold",
            "raw_threshold",
            "location_filter_threshold",
            "max_audio_duration_seconds",
        ):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name.upper()} must be a finite number.")
        if self.raw_threshold > self.default_decision_threshold:
            raise ValueError(
                "RAW_THRESHOLD (the ingestion floor) must not exceed DEFAULT_DECISION_THRESHOLD."
            )
        if self.min_audio_duration_seconds >= self.max_audio_duration_seconds:
            raise ValueError("MIN_AUDIO_DURATION_SECONDS must be below MAX_AUDIO_DURATION_SECONDS.")
        if self.database_url is None:
            self.database_url = f"sqlite:///{self.thicket_data_dir / 'thicket.sqlite3'}"
        if self.environment == "production" and self.auth_mode == "dev":
            raise ValueError(
                "AUTH_MODE=dev is an email-only sign-in form for development and is refused "
                "when ENVIRONMENT=production. Use AUTH_MODE=google (or disabled behind a proxy)."
            )
        if self.auth_mode == "google" and not (self.google_client_id and self.google_client_secret):
            raise ValueError(
                "AUTH_MODE=google needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
                "(see backend/README.md, Google sign-in)."
            )
        return self

    # Convenience accessors -------------------------------------------------

    @property
    def data_dir(self) -> Path:
        return self.thicket_data_dir

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def auth_enabled(self) -> bool:
        return self.auth_mode != "disabled"

    @property
    def cookie_secure(self) -> bool:
        return self.public_base_url.lower().startswith("https://")

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.public_base_url}/api/v1/auth/google/callback"

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host or self.resend_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, read lazily on first use."""
    return Settings()
