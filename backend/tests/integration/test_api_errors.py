"""Typed errors across the API surface."""

import time

import pytest
from tests.helpers import SOUNDSCAPE, post_analysis

from thicket.api.schemas import ErrorResponse


def err(r, status, code):
    assert r.status_code == status, r.text
    body = ErrorResponse.model_validate(r.json())
    assert body.error_code == code
    return body


def tmp_empty(client) -> bool:
    tmp = client.app.state.container.storage.tmp
    return not any(tmp.iterdir())


def test_oversized_upload_413(make_client):
    client = make_client(max_upload_bytes=4096)
    # Declared size is over the limit: rejected before reading.
    body = err(post_analysis(client, SOUNDSCAPE), 413, "file_too_large")
    assert body.detail["max_upload_bytes"] == 4096
    assert tmp_empty(client)


def test_oversized_upload_streaming_cap(make_client):
    client = make_client(max_upload_bytes=4096)
    data = SOUNDSCAPE.read_bytes()

    def chunks():
        boundary = b"XBOUNDARY"
        yield (
            b"--"
            + boundary
            + b'\r\nContent-Disposition: form-data; name="file"; filename="a.flac"\r\n\r\n'
        )
        for i in range(0, len(data), 1024):
            yield data[i : i + 1024]
        yield b"\r\n--" + boundary + b"--\r\n"

    r = client.post(
        "/api/v1/analyses",
        content=chunks(),
        headers={"content-type": "multipart/form-data; boundary=XBOUNDARY"},
    )
    err(r, 413, "file_too_large")
    assert tmp_empty(client)


@pytest.mark.parametrize("key", ["txt", "wav_named_mp3", "corrupt_random"])
def test_unsupported_type_415(client, audio, key):
    body = err(post_analysis(client, audio[key]), 415, "unsupported_file_type")
    assert ".wav" in body.message
    assert tmp_empty(client)


def test_decode_failure_422(client, audio):
    err(post_analysis(client, audio["corrupt_riff"]), 422, "audio_decode_failed")
    assert tmp_empty(client)


def test_too_short_422(client, audio):
    body = err(post_analysis(client, audio["short"]), 422, "audio_too_short")
    assert body.detail["min_seconds"] == 1.0


def test_too_long_422(make_client):
    client = make_client(max_audio_duration_seconds=10)
    err(post_analysis(client, SOUNDSCAPE), 422, "audio_too_long")


def test_sample_rate_too_low_422(client, audio):
    body = err(post_analysis(client, audio["lowrate_8k"]), 422, "unsupported_audio")
    assert "8000 Hz" in body.message


def test_unknown_and_disabled_models(client):
    body = err(post_analysis(client, SOUNDSCAPE, data={"models": "perch"}), 422, "unknown_model")
    assert "birdnet" in body.message
    err(
        post_analysis(client, SOUNDSCAPE, data={"models": "birdnet,frog_insect"}),
        422,
        "model_unavailable",
    )
    err(
        post_analysis(client, SOUNDSCAPE, data={"models": '["frog_insect"]'}),
        422,
        "model_unavailable",
    )
    assert tmp_empty(client)


def test_parameter_validation(client):
    for data, field in [
        ({"threshold": "0.01"}, "threshold"),
        ({"threshold": "1.5"}, "threshold"),
        ({"latitude": "95", "longitude": "10"}, "latitude"),
        ({"latitude": "10"}, "longitude"),
        ({"timezone": "Not/AZone"}, "timezone"),
        ({"captured_at": "last tuesday"}, "captured_at"),
        ({"surprise": "x"}, "surprise"),
    ]:
        body = err(post_analysis(client, SOUNDSCAPE, data=data), 422, "invalid_parameter")
        assert body.detail and body.detail.get("field") == field, (data, body)
    body = err(
        post_analysis(client, SOUNDSCAPE, data={"threshold": "0.05"}), 422, "invalid_parameter"
    )
    assert "ingestion floor" in body.message


def test_missing_file(client):
    err(post_analysis(client, None, data={"threshold": "0.5"}), 422, "invalid_parameter")
    err(client.post("/api/v1/analyses", json={"x": 1}), 422, "invalid_parameter")


def test_not_found_and_method(client):
    err(client.get("/api/v1/analyses/ana_000000000000000000000000"), 404, "analysis_not_found")
    # Decoded slashes never match the id route: a plain 404.
    err(client.get("/api/v1/analyses/..%2F..%2Fetc%2Fpasswd"), 404, "not_found")
    err(client.get("/api/v1/analyses/ana_..%5C..%5Cx"), 404, "analysis_not_found")
    err(client.get("/api/v1/analyses/not-an-id/spectrogram.png"), 404, "analysis_not_found")
    err(client.get("/api/v1/nope"), 404, "not_found")
    err(client.put("/api/v1/analyses"), 405, "invalid_parameter")


def test_internal_error_does_not_leak(client, monkeypatch):
    def boom(limit):
        raise RuntimeError("secret database path /var/lib/x")

    monkeypatch.setattr(client.app.state.container.analysis, "list_recent", boom)
    body = err(client.get("/api/v1/analyses"), 500, "internal_error")
    assert "secret" not in body.message and "/var" not in body.message


def test_request_timeout(make_client, monkeypatch):
    client = make_client(request_timeout_seconds=0.2)

    def slow(limit):
        time.sleep(0.6)
        return None

    monkeypatch.setattr(client.app.state.container.analysis, "list_recent", slow)
    err(client.get("/api/v1/analyses"), 504, "request_timeout")


def test_rate_limit_posts(make_client):
    client = make_client(rate_limit_per_minute=2)
    for _ in range(2):
        assert client.post("/api/v1/previews", files={"x": (None, "1")}).status_code == 422
    r = client.post("/api/v1/previews", files={"x": (None, "1")})
    body = err(r, 429, "rate_limited")
    assert int(r.headers["retry-after"]) >= 1 and body.detail["retry_after_seconds"] >= 1
    assert client.get("/api/v1/health").status_code == 200  # GETs are not limited


def test_cors_is_strict(client):
    ok = client.options(
        "/api/v1/analyses",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    bad = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    good = client.get("/api/v1/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert good.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_security_headers(client):
    r = client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert len(r.headers["x-request-id"]) == 16
