"""Validation of analysis request parameters (multipart form fields or CLI flags)."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from thicket.config import Settings
from thicket.errors import invalid_parameter
from thicket.models.registry import ModelRegistry
from thicket.services.intake import clean_text
from thicket.services.results import validate_threshold

ANALYSIS_FIELDS = frozenset(
    {
        "file",
        "preview_id",
        "models",
        "threshold",
        "latitude",
        "longitude",
        "captured_at",
        "timezone",
        "site_name",
        "notes",
        "recorder_type",
        # platform (schema 3)
        "organization_id",
        "site_id",
        "deployment_id",
        "recorder_id",
    }
)
MAX_MODELS = 4
_MODEL_KEY = re.compile(r"\A[a-z][a-z0-9_]{0,39}\Z")
DEFAULT_MODELS = ("birdnet",)


@dataclass(frozen=True)
class AnalysisParams:
    models: list[str]
    threshold: float
    latitude: float | None = None
    longitude: float | None = None
    captured_at: datetime | None = None
    timezone: str | None = None
    site_name: str | None = None
    notes: str | None = None
    recorder_type: str | None = None
    # Platform tenancy. ``organization_id`` is filled in by the route (the
    # caller's organization, or the implicit local workspace).
    organization_id: str | None = None
    site_id: str | None = None
    deployment_id: str | None = None
    recorder_id: str | None = None
    captured_at_source: str = "unknown"
    telemetry: dict | None = None
    source_filename: str | None = None
    batch_job_id: str | None = None

    @property
    def recording_date(self) -> date | None:
        """Local calendar date of the recording (used for BirdNET's week)."""
        if self.captured_at is None:
            return None
        dt = self.captured_at
        if self.timezone and dt.tzinfo is not None:
            dt = dt.astimezone(ZoneInfo(self.timezone))
        return dt.date()


def parse_models(value: str | None) -> list[str]:
    """Accept a JSON array (``["birdnet"]``) or a comma list (``birdnet,frog_insect``)."""
    if value is None or not value.strip():
        return list(DEFAULT_MODELS)
    text = value.strip()
    if text.startswith("["):
        try:
            items = json.loads(text)
        except json.JSONDecodeError as exc:
            raise invalid_parameter(
                "models must be a JSON array of strings or a comma-separated list.", field="models"
            ) from exc
        if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
            raise invalid_parameter("models must be a JSON array of strings.", field="models")
    else:
        items = text.split(",")
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key:
            continue
        if not _MODEL_KEY.match(key):
            raise invalid_parameter(
                f"'{key[:40]}' is not a model key. Use keys such as birdnet.", field="models"
            )
        if key not in out:
            out.append(key)
    if not out:
        raise invalid_parameter("Choose at least one model.", field="models")
    if len(out) > MAX_MODELS:
        raise invalid_parameter(f"Choose at most {MAX_MODELS} models.", field="models")
    return out


def _float(value: str | None, field: str) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        x = float(str(value).strip())
    except ValueError as exc:
        raise invalid_parameter(f"{field} must be a number.", field=field) from exc
    if not math.isfinite(x):
        raise invalid_parameter(f"{field} must be a finite number.", field=field)
    return x


def parse_timezone(value: str | None) -> str | None:
    text = clean_text(value, 64, "timezone")
    if text is None:
        return None
    try:
        ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise invalid_parameter(
            f"timezone must be an IANA time zone name such as America/New_York; got '{text[:40]}'.",
            field="timezone",
        ) from exc
    return text


def parse_captured_at(value: str | None, tz: str | None) -> datetime | None:
    text = clean_text(value, 64, "captured_at")
    if text is None:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise invalid_parameter(
            "captured_at must be an ISO 8601 date or date-time, for example 2026-05-14T06:30:00.",
            field="captured_at",
        ) from exc
    if dt.tzinfo is None and tz:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    if dt.year < 1900 or dt.year > 2200:
        raise invalid_parameter("captured_at is out of range.", field="captured_at")
    return dt


def parse_analysis_params(
    fields: dict[str, str], settings: Settings, registry: ModelRegistry
) -> AnalysisParams:
    models = parse_models(fields.get("models"))
    for key in models:
        registry.get(key)  # unknown_model / model_unavailable
    threshold = validate_threshold(
        _float(fields.get("threshold"), "threshold"),
        settings.raw_threshold,
        settings.default_decision_threshold,
    )
    lat = _float(fields.get("latitude"), "latitude")
    lon = _float(fields.get("longitude"), "longitude")
    if (lat is None) != (lon is None):
        raise invalid_parameter(
            "Provide both latitude and longitude, or neither.",
            field="latitude" if lat is None else "longitude",
        )
    if lat is not None and not -90.0 <= lat <= 90.0:
        raise invalid_parameter("latitude must be between -90 and 90.", field="latitude")
    if lon is not None and not -180.0 <= lon <= 180.0:
        raise invalid_parameter("longitude must be between -180 and 180.", field="longitude")
    tz = parse_timezone(fields.get("timezone"))
    captured = parse_captured_at(fields.get("captured_at"), tz)
    return AnalysisParams(
        models=models,
        threshold=threshold,
        latitude=lat,
        longitude=lon,
        captured_at=captured,
        timezone=tz,
        site_name=clean_text(fields.get("site_name"), 200, "site_name"),
        notes=clean_text(fields.get("notes"), 2000, "notes"),
        recorder_type=clean_text(fields.get("recorder_type"), 200, "recorder_type"),
        organization_id=_ref(fields.get("organization_id"), "org", "organization_id"),
        site_id=_ref(fields.get("site_id"), "site", "site_id"),
        deployment_id=_ref(fields.get("deployment_id"), "dep", "deployment_id"),
        recorder_id=_ref(fields.get("recorder_id"), "rcd", "recorder_id"),
        captured_at_source="user" if captured is not None else "unknown",
    )


def _ref(value: str | None, prefix: str, field: str) -> str | None:
    """A platform id (validated shape only; existence is checked by the route)."""
    from thicket.ids import is_valid_id

    text = clean_text(value, 64, field)
    if text is None:
        return None
    if not is_valid_id(text, prefix):  # type: ignore[arg-type]
        raise invalid_parameter(f"{field} is not a valid id.", field=field)
    return text
