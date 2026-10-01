"""Platform settings: auth modes, production guard, lists, secrets, URLs."""

import pytest
from pydantic import ValidationError

from thicket.config import Settings
from thicket.services.auth import SECRET_FILE, load_session_secret


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_platform_defaults():
    s = make()
    assert s.auth_mode == "disabled" and not s.auth_enabled
    assert s.max_batch_files == 200 and s.max_batch_bytes == 2 * 1024**3
    assert s.nightly_jobs_hour_utc == 6 and s.alerts_enabled
    assert s.public_base_url == "http://localhost:8000"
    assert s.frontend_url == "http://localhost:5173"
    assert s.google_redirect_uri == "http://localhost:8000/api/v1/auth/google/callback"
    assert s.allowed_signin_domains == [] and not s.email_configured
    assert s.smtp_port == 587 and s.report_logo_path is None


def test_production_refuses_dev_auth():
    with pytest.raises(ValidationError, match="AUTH_MODE=dev"):
        make(environment="production", auth_mode="dev")
    assert make(environment="development", auth_mode="dev").auth_enabled


def test_google_mode_needs_client_credentials():
    with pytest.raises(ValidationError, match="GOOGLE_CLIENT_ID"):
        make(auth_mode="google")
    s = make(auth_mode="google", google_client_id="id", google_client_secret="secret")
    assert s.auth_mode == "google"


def test_env_lists_and_blank_values(monkeypatch):
    monkeypatch.setenv("ALLOWED_SIGNIN_DOMAINS", " Example.org, @farm.coop ,,")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("RESEND_API_KEY", "re_123")
    monkeypatch.setenv("REPORT_LOGO_PATH", "")
    s = make()
    assert s.allowed_signin_domains == ["example.org", "farm.coop"]
    assert s.smtp_host is None and s.email_configured and s.report_logo_path is None


def test_secure_cookie_follows_public_url():
    assert not make().cookie_secure
    s = make(public_base_url="https://thicket.example.org/")
    assert s.cookie_secure and s.public_base_url == "https://thicket.example.org"


@pytest.mark.parametrize(
    "kw", [{"public_base_url": "thicket.example"}, {"frontend_url": "ftp://x"}]
)
def test_invalid_urls(kw):
    with pytest.raises(ValidationError):
        make(**kw)


@pytest.mark.parametrize(
    "kw", [{"nightly_jobs_hour_utc": 24}, {"max_batch_files": 0}, {"max_batch_bytes": 10}]
)
def test_bounds(kw):
    with pytest.raises(ValidationError):
        make(**kw)


def test_session_secret_is_generated_once_and_persisted(tmp_path):
    s = make(thicket_data_dir=tmp_path)
    first = load_session_secret(s)
    assert len(first) >= 32
    assert (tmp_path / SECRET_FILE).read_text() == first
    assert load_session_secret(s) == first
    assert load_session_secret(make(thicket_data_dir=tmp_path, session_secret="x" * 40)) == "x" * 40


def test_generated_secret_warns_in_production(tmp_path, caplog):
    s = make(
        thicket_data_dir=tmp_path,
        environment="production",
        auth_mode="google",
        google_client_id="id",
        google_client_secret="secret",
    )
    with caplog.at_level("WARNING"):
        load_session_secret(s)
    assert any("SESSION_SECRET is unset" in r.getMessage() for r in caplog.records)
