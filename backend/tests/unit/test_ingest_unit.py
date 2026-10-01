"""Batch ingestion building blocks: timestamp order, sidecars, zip safety,
and the interactive-first worker pool."""

import threading
import time
import zipfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from tests.platform_helpers import audiomoth_comment, write_wav

from thicket.errors import ThicketError
from thicket.services.analysis import PriorityWorkers
from thicket.services.ingest import StagedFile, expand_zip, resolve_timestamp
from thicket.services.telemetry import AudioMothConfig, SummaryRow

NY = "America/New_York"
MAY14_0530_UTC = datetime(2024, 5, 14, 5, 30, tzinfo=UTC)


def staged(path: Path, name: str | None = None, last_modified_ms: int | None = None) -> StagedFile:
    return StagedFile(
        path=path,
        filename=name or path.name,
        byte_size=path.stat().st_size,
        last_modified_ms=last_modified_ms,
    )


def resolve(f, **kw):
    kw.setdefault("tz_name", NY)
    kw.setdefault("recorder_make", None)
    kw.setdefault("summary_rows", [])
    kw.setdefault("config", None)
    kw.setdefault("override", None)
    return resolve_timestamp(f, **kw)


def test_filename_wins_over_metadata_and_audiomoth_is_utc(tmp_path):
    p = write_wav(
        tmp_path / "20240514_053000.WAV", 1.0, comment=audiomoth_comment(when="07:00:00 14/05/2024")
    )
    r = resolve(staged(p), override=datetime(2020, 1, 1, tzinfo=UTC))
    assert r.captured_at == MAY14_0530_UTC and r.source == "filename"
    assert r.telemetry["source"] == "audiomoth_comment" and r.telemetry["battery_v"] == 4.0
    assert r.device_id == "24A1D5F3A1B2C3D4" and r.device_make == "audiomoth"


def test_song_meter_names_are_local_time(tmp_path):
    p = write_wav(tmp_path / "SMM01234_20240514_053000.wav", 1.0)
    r = resolve(staged(p))
    assert r.captured_at.astimezone(UTC) == datetime(2024, 5, 14, 9, 30, tzinfo=UTC)
    assert r.source == "filename" and r.device_make == "song_meter" and r.device_id == "SMM01234"


def test_registered_recorder_make_overrides_the_pattern(tmp_path):
    p = write_wav(tmp_path / "20240514_053000.wav", 1.0)
    as_song_meter = resolve(staged(p), recorder_make="song_meter")
    assert as_song_meter.captured_at.astimezone(UTC) == datetime(2024, 5, 14, 9, 30, tzinfo=UTC)
    q = write_wav(tmp_path / "2024-05-14T05-30-00.wav", 1.0)
    as_audiomoth = resolve(staged(q), recorder_make="audiomoth")
    assert as_audiomoth.captured_at == MAY14_0530_UTC
    assert resolve(staged(q)).captured_at.astimezone(UTC).hour == 9  # ISO names are local


def test_audiomoth_config_offset_applies_to_utc_names(tmp_path):
    p = write_wav(tmp_path / "20240514_053000.WAV", 1.0)
    cfg = AudioMothConfig(utc_offset_hours=-5.0, raw={"Time zone": "UTC-5"})
    r = resolve(staged(p), config=cfg)
    assert r.captured_at.utcoffset() == timedelta(hours=-5)
    assert r.captured_at.astimezone(UTC) == datetime(2024, 5, 14, 10, 30, tzinfo=UTC)


def test_metadata_used_when_the_name_has_no_time(tmp_path):
    p = write_wav(tmp_path / "New Recording 7.wav", 1.0, comment=audiomoth_comment(offset="-4"))
    r = resolve(staged(p, last_modified_ms=1_000_000_000_000))
    assert r.source == "file_metadata"
    assert r.captured_at == datetime(2024, 5, 14, 5, 30, tzinfo=timezone(timedelta(hours=-4)))


def test_guano_timestamp_location_and_temperature(tmp_path):
    guano = "GUANO|Version:1.0\nTimestamp:2024-05-14 05:30:00\nLoc Position:42.44 -76.5\nTemperature Int:11.0\nSerial:ABC123\nMake:Wildlife Acoustics\n"
    p = write_wav(tmp_path / "clip.wav", 1.0, guano=guano)
    r = resolve(staged(p))
    assert r.source == "file_metadata"
    assert r.captured_at.astimezone(UTC) == datetime(
        2024, 5, 14, 9, 30, tzinfo=UTC
    )  # naive: recorder clock
    assert (r.latitude, r.longitude) == (42.44, -76.5)
    assert r.telemetry["source"] == "guano" and r.telemetry["temperature_c"] == 11.0
    assert r.device_id == "ABC123" and r.device_make == "song_meter"


def test_browser_last_modified_then_override_then_unknown(tmp_path):
    p = write_wav(tmp_path / "clip.wav", 1.0)
    ms = int(MAY14_0530_UTC.timestamp() * 1000)
    r = resolve(staged(p, last_modified_ms=ms), override=datetime(2020, 1, 1, tzinfo=UTC))
    assert r.source == "browser_last_modified" and r.captured_at == MAY14_0530_UTC
    r = resolve(staged(p), override=datetime(2024, 5, 14, 1, 30))
    assert (
        r.source == "user" and r.captured_at.astimezone(UTC) == MAY14_0530_UTC
    )  # naive override is local
    r = resolve(staged(p))
    assert r.source == "unknown" and r.captured_at is None and r.telemetry == {"source": "none"}


def test_song_meter_summary_row_supplies_telemetry(tmp_path):
    p = write_wav(tmp_path / "SMM01234_20240514_053000.wav", 1.0)
    rows = [
        SummaryRow(
            timestamp=datetime(2024, 5, 14, 5, 30, 20),
            latitude=42.4,
            longitude=-76.4,
            battery_v=4.9,
            temperature_c=8.5,
        ),
        SummaryRow(timestamp=datetime(2024, 5, 14, 6, 30), battery_v=4.8),
    ]
    r = resolve(staged(p), summary_rows=rows)
    assert r.telemetry["source"] == "song_meter_summary"
    assert (r.telemetry["battery_v"], r.telemetry["temperature_c"]) == (4.9, 8.5)
    assert (r.latitude, r.longitude) == (42.4, -76.4)


def test_config_device_id_fills_in(tmp_path):
    p = write_wav(tmp_path / "plain.wav", 1.0)
    cfg = AudioMothConfig(device_id="24A1D5F3A1B2C3D4", gain="medium", raw={"x": "y"})
    r = resolve(staged(p), config=cfg)
    assert r.telemetry["device_id"] == "24A1D5F3A1B2C3D4" and r.device_make == "audiomoth"


# ------------------------------------------------------------------ zips


def make_zip(path: Path, members: dict[str, bytes]) -> StagedFile:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return StagedFile(path=path, filename=path.name, byte_size=path.stat().st_size)


def expand(z, dest, **kw):
    kw.setdefault("per_file_max", 10 * 1024 * 1024)
    kw.setdefault("max_total_bytes", 100 * 1024 * 1024)
    kw.setdefault("max_files", 50)
    kw.setdefault("already_files", 0)
    kw.setdefault("already_bytes", 0)
    return expand_zip(z, dest, **kw)


def test_zip_extracts_only_safe_audio_and_sidecars(tmp_path):
    wav = write_wav(tmp_path / "w.wav", 1.0).read_bytes()
    z = make_zip(
        tmp_path / "card.zip",
        {
            "DATA/20240514_053000.WAV": wav,
            "DATA/CONFIG.TXT": b"Device ID : 24A1D5F3\n",
            "DATA/SMM01234_Summary.txt": b"DATE,TIME\n",
            "../../evil.wav": wav,
            "/abs/evil.wav": wav,
            "__MACOSX/DATA/._20240514_053000.WAV": b"junk",
            "DATA/.hidden.wav": wav,
            "DATA/readme.md": b"hello",
            "DATA/inner.zip": b"PK",
            "DATA/sub/": b"",
        },
    )
    dest = tmp_path / "out"
    dest.mkdir()
    files, skipped = expand(z, dest)
    assert sorted(f.filename for f in files) == [
        "20240514_053000.WAV",
        "CONFIG.TXT",
        "SMM01234_Summary.txt",
    ]
    assert all(f.path.parent == dest and f.from_zip == "card.zip" for f in files)
    assert {
        "../../evil.wav",
        "/abs/evil.wav",
        "DATA/readme.md",
        "DATA/inner.zip",
        "DATA/.hidden.wav",
    } <= set(skipped)
    assert not (tmp_path / "evil.wav").exists() and not Path("/abs/evil.wav").exists()
    assert all(f.last_modified_ms for f in files)


def test_zip_caps(tmp_path):
    wav = write_wav(tmp_path / "w.wav", 1.0).read_bytes()
    z = make_zip(tmp_path / "many.zip", {f"{i}.wav": wav for i in range(5)})
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ThicketError) as e:
        expand(z, dest, max_files=4)
    assert e.value.code.value == "invalid_parameter"
    with pytest.raises(ThicketError) as e:
        expand(z, dest, per_file_max=1000)
    assert e.value.code.value == "file_too_large"
    with pytest.raises(ThicketError) as e:
        expand(z, dest, max_total_bytes=len(wav) * 2)
    assert e.value.code.value == "file_too_large"
    with pytest.raises(ThicketError):
        expand(z, dest, already_files=3, max_files=5)


def test_member_lying_about_its_size_is_skipped(tmp_path):
    z = make_zip(tmp_path / "bomb.zip", {"zeros.wav": b"\x00" * (5 * 1024 * 1024), "ok.txt": b""})
    dest = tmp_path / "out"
    dest.mkdir()
    zf = zipfile.ZipFile(z.path)
    zf.infolist()[0].file_size = 100  # a central directory that understates the size
    import thicket.services.ingest as ingest

    real = ingest.zipfile.ZipFile
    ingest.zipfile.ZipFile = lambda *a, **k: zf  # type: ignore[assignment]
    try:
        files, skipped = expand(z, dest, per_file_max=1024 * 1024)
    finally:
        ingest.zipfile.ZipFile = real  # type: ignore[assignment]
    assert files == [] and "zeros.wav" in skipped
    assert list(dest.iterdir()) == []


def test_highly_compressible_audio_is_kept(tmp_path):
    silent = write_wav(tmp_path / "s.wav", 2.0, freq=None, amp=0.0).read_bytes()
    z = make_zip(tmp_path / "quiet.zip", {"20240514_053000.WAV": silent})
    dest = tmp_path / "out"
    dest.mkdir()
    files, skipped = expand(z, dest)
    assert [f.filename for f in files] == ["20240514_053000.WAV"] and skipped == []


def test_bad_zip(tmp_path):
    p = tmp_path / "bad.zip"
    p.write_bytes(b"PK\x03\x04 not really")
    with pytest.raises(ThicketError) as e:
        expand(StagedFile(path=p, filename="bad.zip", byte_size=10), tmp_path)
    assert e.value.code.value == "unsupported_file_type"


# ----------------------------------------------------------- worker pool


def test_interactive_tasks_jump_the_batch_queue():
    pool = PriorityWorkers(1, batch_cap=1)
    pool.start()
    order: list[str] = []
    gate = threading.Event()
    try:
        first = pool.submit(lambda: (gate.wait(5), order.append("b0")), batch=True)
        time.sleep(0.05)  # b0 is running and holds the only worker
        futures = [pool.submit(lambda i=i: order.append(f"b{i}"), batch=True) for i in (1, 2)]
        futures.append(pool.submit(lambda: order.append("i1")))
        gate.set()
        for f in [first, *futures]:
            f.result(timeout=5)
    finally:
        pool.shutdown(wait=True)
    assert order == ["b0", "i1", "b1", "b2"]


def test_batch_cap_leaves_a_worker_for_interactive_work():
    pool = PriorityWorkers(2, batch_cap=1)
    pool.start()
    gate = threading.Event()
    done = threading.Event()
    try:
        pool.submit(lambda: gate.wait(5), batch=True)
        pool.submit(lambda: gate.wait(5), batch=True)  # must wait: cap is 1
        f = pool.submit(done.set)
        assert f.result(timeout=2) is None and done.is_set()
        assert pool.pending() == (0, 1)
    finally:
        gate.set()
        pool.shutdown(wait=True)


def test_shutdown_cancels_queued_and_refuses_new_work():
    pool = PriorityWorkers(1)
    pool.start()
    gate = threading.Event()
    running = pool.submit(lambda: gate.wait(5))
    time.sleep(0.05)
    queued = pool.submit(lambda: None, batch=True)
    gate.set()
    pool.shutdown(wait=True)
    assert queued.cancelled() and running.done()
    with pytest.raises(RuntimeError):
        pool.submit(lambda: None)


def test_errors_travel_through_the_future():
    pool = PriorityWorkers(1)
    pool.start()
    try:
        f = pool.submit(lambda: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            f.result(timeout=5)
        assert pool.submit(lambda: 42).result(timeout=5) == 42
    finally:
        pool.shutdown(wait=True)
