import time

import pytest
from tests.helpers import SOUNDSCAPE, post_analysis

from thicket.api.schemas import ErrorResponse, Preview


def post_preview(client, path, name=None):
    with open(path, "rb") as fh:
        return client.post("/api/v1/previews", files={"file": (name or path.name, fh)})


def test_preview_shape_and_spectrogram(client):
    r = post_preview(client, SOUNDSCAPE)
    assert r.status_code == 201, r.text
    p = Preview.model_validate(r.json())
    assert p.id.startswith("prv_")
    assert p.recording.duration_seconds == 30.0 and p.recording.sample_rate_hz == 48000
    assert p.recording.format == "flac (flac)"
    assert p.spectrogram_url == f"/api/v1/previews/{p.id}/spectrogram.png"
    assert (p.spectrogram_min_hz, p.spectrogram_max_hz) == (0, 16000)
    assert all(c.name != "speech" for c in p.quality.checks)  # needs the model
    img = client.get(p.spectrogram_url)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert img.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert Preview.model_validate(client.get(f"/api/v1/previews/{p.id}").json()) == p


@pytest.mark.birdnet
def test_reuse_preview_for_analysis(client):
    p = post_preview(client, SOUNDSCAPE).json()
    r = post_analysis(client, None, data={"preview_id": p["id"], "threshold": "0.3"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["recording"]["checksum_sha256"] == p["recording"]["checksum_sha256"]
    assert a["recording"]["filename"] == "soundscape_30s.flac"
    assert "Black-capped Chickadee" in {s["common_name"] for s in a["species"]}
    # The preview survives for another run until its TTL.
    assert client.get(f"/api/v1/previews/{p['id']}").status_code == 200


def test_preview_id_errors(client):
    r = post_analysis(client, None, data={"preview_id": "prv_000000000000000000000000"})
    assert r.status_code == 404 and r.json()["error_code"] == "not_found"
    r = post_analysis(client, None, data={"preview_id": "../../etc/passwd"})
    assert r.status_code == 404
    p = post_preview(client, SOUNDSCAPE).json()
    with open(SOUNDSCAPE, "rb") as fh:
        r = client.post(
            "/api/v1/analyses",
            files={"file": ("a.flac", fh), "preview_id": (None, p["id"])},
        )
    assert r.status_code == 422 and "not both" in r.json()["message"]


def test_preview_expires(make_client):
    client = make_client(preview_ttl_minutes=0.005)  # 0.3 s
    p = post_preview(client, SOUNDSCAPE).json()
    time.sleep(0.5)
    r = client.get(f"/api/v1/previews/{p['id']}/spectrogram.png")
    assert r.status_code == 404
    assert ErrorResponse.model_validate(r.json()).error_code == "not_found"
    c = client.app.state.container
    assert c.previews.purge_expired() == 1
    assert not any(c.storage.previews.iterdir())


def test_preview_quality_states(client, audio):
    short = post_preview(client, audio["short"])
    assert short.status_code == 201
    q = short.json()["quality"]
    assert q["status"] == "not_usable"
    assert next(c for c in q["checks"] if c["name"] == "duration")["status"] == "fail"
    low = post_preview(client, audio["lowrate_8k"]).json()["quality"]
    assert next(c for c in low["checks"] if c["name"] == "sample_rate")["status"] == "fail"
    clipped = post_preview(client, audio["clipped"]).json()["quality"]
    assert next(c for c in clipped["checks"] if c["name"] == "clipping")["status"] == "fail"
    silent = post_preview(client, audio["silence"]).json()["quality"]
    assert silent["status"] == "not_usable" and silent["silence_fraction"] == 1.0
    stereo = post_preview(client, audio["stereo_one_clipped"]).json()
    assert stereo["recording"]["channels"] == 2
    assert stereo["quality"]["clipping_fraction"] > 0.2


def test_preview_errors(make_client, audio):
    client = make_client(max_audio_duration_seconds=10)
    assert post_preview(client, SOUNDSCAPE).json()["error_code"] == "audio_too_long"
    assert post_preview(client, audio["txt"]).status_code == 415
    assert post_preview(client, audio["corrupt_riff"]).json()["error_code"] == "audio_decode_failed"
    assert client.post("/api/v1/previews", files={"x": (None, "1")}).status_code == 422
    assert not any(client.app.state.container.storage.previews.iterdir())
