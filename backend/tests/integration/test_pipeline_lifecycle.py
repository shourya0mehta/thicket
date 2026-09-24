"""Temp cleanup, timeouts, janitor and restart recovery."""

import os
import time

import pytest
from tests.helpers import SOUNDSCAPE, make_settings, post_analysis

from thicket.container import Container
from thicket.ids import new_id
from thicket.models.base import AdapterError

pytestmark = pytest.mark.birdnet


def storage(client):
    return client.app.state.container.storage


def test_temp_dir_removed_on_success(client):
    r = post_analysis(client, SOUNDSCAPE)
    assert r.status_code == 201
    assert list(storage(client).tmp.iterdir()) == []


def test_temp_dir_removed_on_pipeline_failure(client, monkeypatch):
    adapter = client.app.state.container.registry.lookup("birdnet")

    def broken(*args, **kwargs):
        raise AdapterError("kaput")

    monkeypatch.setattr(adapter, "analyze", broken)
    r = post_analysis(client, SOUNDSCAPE)
    assert r.status_code == 500 and r.json()["error_code"] == "internal_error"
    aid = r.json()["detail"]["analysis_id"]
    assert list(storage(client).tmp.iterdir()) == []
    a = client.get(f"/api/v1/analyses/{aid}").json()
    assert a["status"] == "failed" and a["stage"] == "failed"
    assert a["error_code"] == "internal_error" and "kaput" not in a["error_message"]
    assert a["quality"] is not None  # QC ran before the model
    assert "model:birdnet" in a["stage_timings_ms"]


def test_unexpected_exception_is_contained(client, monkeypatch):
    adapter = client.app.state.container.registry.lookup("birdnet")
    monkeypatch.setattr(adapter, "analyze", lambda *a, **k: 1 / 0)
    r = post_analysis(client, SOUNDSCAPE)
    assert r.status_code == 500 and "division" not in r.text
    assert list(storage(client).tmp.iterdir()) == []


def test_analysis_timeout(make_client):
    client = make_client(analysis_timeout_seconds=0.001)
    r = post_analysis(client, SOUNDSCAPE)
    assert r.status_code == 504 and r.json()["error_code"] == "analysis_timeout"
    aid = r.json()["detail"]["analysis_id"]
    a = client.get(f"/api/v1/analyses/{aid}").json()
    assert a["status"] == "failed" and a["error_code"] == "analysis_timeout"
    time.sleep(0.2)
    assert list(storage(client).tmp.iterdir()) == []


def test_truncated_file_uses_decoded_duration(client, tmp_path):
    # The FLAC header still declares 30 s, but only about 14 s of frames remain.
    truncated = tmp_path / "truncated.flac"
    truncated.write_bytes(SOUNDSCAPE.read_bytes()[:400_000])
    r = post_analysis(client, truncated, data={"threshold": "0.1"})
    assert r.status_code == 201, r.text
    a = r.json()
    duration = a["recording"]["duration_seconds"]
    assert 10.0 < duration < 20.0
    duration_check = next(c for c in a["quality"]["checks"] if c["name"] == "duration")
    assert abs(duration_check["value"] - duration) < 0.05
    events = a["metrics"]["total_detection_events"]
    assert events > 0
    assert a["metrics"]["events_per_minute"] == round(events / (duration / 60.0), 3)
    assert any("declares 30.0 s" in w and "truncated" in w for w in a["warnings"])
    # An intact file gets no such warning.
    intact = post_analysis(client, SOUNDSCAPE).json()
    assert intact["recording"]["duration_seconds"] == 30.0
    assert not any("declares" in w for w in intact["warnings"])


def test_delete_while_queued(client):
    r = post_analysis(client, SOUNDSCAPE, wait=False)
    aid = r.json()["id"]
    assert client.delete(f"/api/v1/analyses/{aid}").status_code == 204
    client.app.state.container.analysis.wait(aid, timeout=30)
    assert client.get(f"/api/v1/analyses/{aid}").status_code == 404
    assert list(storage(client).tmp.iterdir()) == []
    assert not storage(client).spectrogram_path(aid).exists()


def test_janitor_removes_stale_temp_and_orphans(client):
    c = client.app.state.container
    st = c.storage
    old = time.time() - 2 * 3600
    stale = st.tmp / new_id("ana")
    stale.mkdir()
    (stale / "x.wav").write_bytes(b"123")
    os.utime(stale, (old, old))
    fresh = st.tmp / new_id("ana")
    fresh.mkdir()
    orphan = st.spectrograms / f"{new_id('ana')}.png"
    orphan.write_bytes(b"png")
    os.utime(orphan, (old, old))
    active = st.tmp / new_id("ana")
    active.mkdir()
    os.utime(active, (old, old))
    c.janitor.active_ids = lambda: {active.name}
    counts = c.janitor.run_once()
    assert counts["temp_dirs"] == 1 and counts["orphan_assets"] == 1
    assert not stale.exists() and fresh.exists() and active.exists() and not orphan.exists()


def test_interrupted_analyses_fail_on_restart(tmp_path):
    settings = make_settings(tmp_path)
    c = Container(settings)
    c.storage.ensure()
    c.db.create_all()
    from thicket.persistence.db import AnalysisRow, RecordingRow

    rec = RecordingRow(
        id=new_id("rec"),
        filename="a.wav",
        byte_size=1,
        checksum_sha256="0" * 64,
        duration_seconds=1.0,
        sample_rate_hz=48000,
        channels=1,
    )
    aid = new_id("ana")
    c.repo.create_analysis(
        rec,
        AnalysisRow(
            id=aid,
            recording_id=rec.id,
            status="processing",
            stage="model:birdnet",
            requested_models=["birdnet"],
            decision_threshold=0.6,
            raw_threshold=0.1,
            merge_gap_seconds=1.0,
            hop_seconds=3.0,
            location_filter=True,
            location_filter_threshold=0.03,
            software_version="test",
        ),
    )
    c.db.dispose()
    c2 = Container(settings)
    c2.startup(background=False)
    try:
        row = c2.repo.get_analysis(aid)
        assert row.status == "failed" and "restart" in row.error_message
    finally:
        c2.shutdown()
