from pathlib import Path

import pytest
from pydantic import ValidationError

from thicket.config import API_PORT, BACKEND_DIR, FRONTEND_DEV_PORT, Settings


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_defaults(monkeypatch):
    for key in ("THICKET_DATA_DIR", "DATABASE_URL", "ALLOWED_ORIGINS", "MAX_UPLOAD_BYTES"):
        monkeypatch.delenv(key, raising=False)
    s = make()
    assert s.environment == "development"
    assert s.data_dir == (BACKEND_DIR / "var").resolve()
    assert s.data_dir.is_absolute()
    assert s.database_url == f"sqlite:///{s.data_dir / 'thicket.sqlite3'}"
    assert s.allowed_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]
    assert s.max_upload_bytes == 50 * 1024 * 1024
    assert s.max_audio_duration_seconds == 600
    assert s.min_audio_duration_seconds == 1.0
    assert s.default_decision_threshold == 0.60
    assert s.raw_threshold == 0.10
    assert s.merge_gap_seconds == 1.0
    assert s.hop_seconds == 3.0
    assert s.birdnet_enabled and s.location_filter
    assert s.location_filter_threshold == 0.03
    assert not s.frog_insect_enabled and not s.retain_audio
    assert s.worker_concurrency == 1 and s.rate_limit_per_minute == 30
    assert (API_PORT, FRONTEND_DEV_PORT) == (8000, 5173)
    assert s.app_version


def test_env_parsing(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://thicket.example, http://localhost:5173/")
    monkeypatch.setenv("THICKET_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("RETAIN_AUDIO", "true")
    monkeypatch.setenv("HOP_SECONDS", "1.5")
    monkeypatch.setenv("SERVE_FRONTEND_DIR", "")
    s = make()
    assert s.allowed_origins == ["https://thicket.example", "http://localhost:5173"]
    assert s.data_dir == (tmp_path / "d").resolve()
    assert s.retain_audio and s.hop_seconds == 1.5
    assert s.serve_frontend_dir is None


def test_json_origins(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", '["https://a.example"]')
    assert make().allowed_origins == ["https://a.example"]


@pytest.mark.parametrize(
    "kw",
    [
        {"allowed_origins": ["*"]},
        {"allowed_origins": ["https://a.example/path"]},
        {"allowed_origins": ["ftp://a.example"]},
        {"raw_threshold": 0.7, "default_decision_threshold": 0.6},
        {"default_decision_threshold": 1.5},
        {"hop_seconds": 5.0},
        {"worker_concurrency": 0},
        {"max_upload_bytes": 10},
        {"min_audio_duration_seconds": 700, "max_audio_duration_seconds": 600},
        {"environment": "staging"},
        {"log_level": "LOUD"},
    ],
)
def test_invalid_settings_rejected(kw):
    with pytest.raises(ValidationError):
        make(**kw)


def test_relative_data_dir_resolved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = make(thicket_data_dir=Path("rel"))
    assert s.data_dir == (tmp_path / "rel").resolve()
