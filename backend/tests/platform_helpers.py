"""Helpers for platform tests: synthetic analyses written straight to the
database (no model needed), a tone-driven fake adapter for pipeline tests,
RIFF/WAV builders with metadata chunks, and sign-in helpers for the API."""

from __future__ import annotations

import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from thicket.container import Container
from thicket.domain.consolidation import WindowDetection
from thicket.ids import LOCAL_ORG_ID, model_run_id, new_id
from thicket.models.base import AdapterOutput
from thicket.models.registry import ModelRegistry
from thicket.persistence.db import AnalysisRow, ModelRunRow, RecordingRow

CSRF = {"X-Requested-With": "thicket"}
SR = 48_000

DEFAULT_PROFILE = {
    "rms_dbfs": -40.0,
    "peak_dbfs": -20.0,
    "clipping_fraction": 0.0,
    "dc_offset": 0.0,
    "band_fraction_0_1k": 0.40,
    "band_fraction_1_4k": 0.30,
    "band_fraction_4_8k": 0.20,
    "band_fraction_8k_plus": 0.10,
    "spectral_centroid_hz": 2500.0,
    "channel_rms_dbfs": [-40.0],
}

SPECIES = {
    "Poecile atricapillus": ("Black-capped Chickadee", "bird"),
    "Haemorhous mexicanus": ("House Finch", "bird"),
    "Cyanocitta cristata": ("Blue Jay", "bird"),
    "Dolichonyx oryzivorus": ("Bobolink", "bird"),
    "Pseudacris crucifer": ("Spring Peeper", "amphibian"),
    "Turdus migratorius": ("American Robin", "bird"),
}


def insert_analysis(
    c: Container,
    *,
    org_id: str = LOCAL_ORG_ID,
    site_id: str | None = None,
    site_name: str | None = None,
    captured_at: datetime | None = None,
    species: dict[str, int] | None = None,
    duration: float = 60.0,
    threshold: float = 0.6,
    quality_status: str = "usable",
    speech: bool = False,
    profile: dict | None = None,
    telemetry: dict | None = None,
    recorder_id: str | None = None,
    deployment_id: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    timezone: str | None = None,
    channels: int = 1,
    filename: str | None = None,
    rollup: bool = True,
    indices: dict | None = None,
    confidence: float = 0.9,
) -> tuple[str, str]:
    """Write a completed analysis with ``species`` events and return (analysis_id, recording_id)."""
    aid, rid = new_id("ana"), new_id("rec")
    captured = captured_at.astimezone(UTC) if captured_at and captured_at.tzinfo else captured_at
    rec = RecordingRow(
        id=rid,
        filename=filename or f"{rid}.wav",
        source_filename=filename,
        content_type="audio/wav",
        byte_size=1000,
        checksum_sha256="0" * 64,
        format="wav",
        duration_seconds=duration,
        sample_rate_hz=SR,
        channels=channels,
        bit_depth=16,
        captured_at=captured.isoformat() if captured else None,
        captured_at_utc=captured,
        captured_at_source="user" if captured else "unknown",
        timezone=timezone,
        latitude=latitude,
        longitude=longitude,
        site_name=site_name,
        organization_id=org_id,
        site_id=site_id,
        recorder_id=recorder_id,
        deployment_id=deployment_id,
        telemetry=telemetry,
        signal_profile=dict(DEFAULT_PROFILE, **(profile or {}))
        if profile is not None
        else dict(DEFAULT_PROFILE),
    )
    row = AnalysisRow(
        id=aid,
        recording_id=rid,
        status="queued",
        stage="queued",
        requested_models=["birdnet"],
        decision_threshold=threshold,
        raw_threshold=0.1,
        merge_gap_seconds=1.0,
        hop_seconds=3.0,
        location_filter=True,
        location_filter_threshold=0.03,
        warnings=[],
        software_version="test",
        stage_timings={},
        has_spectrogram=False,
    )
    c.repo.create_analysis(rec, row)
    run_id = model_run_id(aid, "birdnet")
    detections: list[WindowDetection] = []
    i = 0
    t = 0.0
    for sci, n in (species or {}).items():
        common, taxon = SPECIES.get(sci, (sci, "bird"))
        for _ in range(n):
            detections.append(
                WindowDetection(
                    id=f"det_{i}",
                    model_run_id=run_id,
                    label_raw=f"{sci}_{common}",
                    scientific_name=sci,
                    common_name=common,
                    taxon=taxon,
                    start_seconds=t,
                    end_seconds=t + 3.0,
                    confidence=confidence,
                    plausibility="plausible",
                )
            )
            i += 1
            t += 6.0  # gaps of 3 s keep every window its own event
    quality = {
        "status": quality_status,
        "score": 1.0 if quality_status == "usable" else 0.5,
        "peak_dbfs": -20.0,
        "rms_dbfs": -40.0,
        "clipping_fraction": 0.0,
        "silence_fraction": 0.0,
        "low_frequency_energy_fraction": 0.3,
        "speech_detected": speech,
        "checks": [],
        "warnings": [],
    }
    run = ModelRunRow(
        id=run_id,
        analysis_id=aid,
        position=0,
        adapter="birdnet",
        model="BirdNET GLOBAL 6K V2.4",
        version="2.4",
        model_sha256="a" * 64,
        taxa=["bird"],
        experimental=False,
        required_sample_rate_hz=SR,
        window_seconds=3.0,
        hop_seconds=3.0,
        raw_threshold=0.1,
        configuration={},
        runtime_ms=1,
        n_windows=int(duration // 3),
    )
    ok = c.repo.complete(
        aid,
        quality=quality,
        indices=indices
        or {
            "acoustic_complexity_index": 150.0,
            "acoustic_diversity_index": 1.2,
            "acoustic_evenness_index": 0.4,
            "bioacoustic_index": 10.0,
            "ndsi": 0.2,
            "spectral_entropy": 0.8,
            "temporal_entropy": 0.9,
        },
        warnings=[],
        timings={"total": 1},
        model_runs=[run],
        detections=detections,
        storage_uri=None,
        duration_seconds=duration,
    )
    assert ok
    if rollup:
        c.rollups.on_analysis_completed(aid)
    return aid, rid


def days_ago(n: float, hour: int = 6, base: datetime | None = None) -> datetime:
    base = base or datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    return (base - timedelta(days=n)).replace(hour=hour)


# ---------------------------------------------------------------- WAV files


def _chunk(cid: bytes, data: bytes) -> bytes:
    if len(data) % 2:
        data += b"\x00"
    return cid + struct.pack("<I", len(data)) + data


def write_wav(
    path: Path,
    seconds: float = 4.0,
    freq: float | None = 2000.0,
    *,
    sr: int = SR,
    channels: int = 1,
    amp: float = 0.3,
    comment: str | None = None,
    guano: str | None = None,
    channel_gains: list[float] | None = None,
    dc: float = 0.0,
    seed: int = 0,
) -> Path:
    """A PCM16 WAV written by hand so INFO/ICMT and guan chunks can be added."""
    n = int(seconds * sr)
    t = np.arange(n) / sr
    if freq is None:
        x = np.random.default_rng(seed).standard_normal(n) * amp * 0.3
    else:
        x = amp * np.sin(2 * np.pi * freq * t)
    x = x + dc
    if channels > 1:
        gains = channel_gains or [1.0] * channels
        x = np.stack([x * g for g in gains], axis=1)
    pcm = (np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    fmt = struct.pack("<HHIIHH", 1, channels, sr, sr * 2 * channels, 2 * channels, 16)
    body = _chunk(b"fmt ", fmt)
    if comment is not None:
        body += _chunk(b"LIST", b"INFO" + _chunk(b"ICMT", comment.encode() + b"\x00"))
    body += _chunk(b"data", pcm)
    if guano is not None:
        body += _chunk(b"guan", guano.encode())
    path.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)
    return path


def audiomoth_comment(
    when: str = "05:30:00 14/05/2024",
    offset: str = "",
    device: str = "24A1D5F3A1B2C3D4",
    gain: str = "medium",
    battery: str = "4.0",
    temp: str = "12.3",
) -> str:
    return (
        f"Recorded at {when} (UTC{offset}) by AudioMoth {device} at {gain} gain while "
        f"battery was {battery}V and temperature was {temp}C."
    )


# ------------------------------------------------------------- fake adapter


class ToneAdapter:
    """Detects species from the dominant frequency of each 3 s window.

    Below 1.5 kHz: nothing. 1.5 to 3 kHz: Black-capped Chickadee. 3 to 5 kHz:
    House Finch. 5 kHz and up: Blue Jay. Lets pipeline tests choose species
    by synthesizing tones, without BirdNET weights.
    """

    key = "birdnet"
    name = "Tone adapter"
    model_name = "ToneAdapter"
    version = "0.0.1"
    taxon_scope = ["bird"]
    required_sample_rate_hz = SR
    window_seconds = 3.0
    experimental = False
    license = "MIT"
    description = "Test adapter"
    model_card_url = None

    def is_ready(self) -> bool:
        return True

    def status(self) -> str:
        return "ready"

    def unavailable_reason(self) -> str | None:
        return None

    def load(self) -> None:
        return None

    def model_sha256(self) -> str | None:
        return "f" * 64

    def analyze(self, samples, sample_rate, context) -> AdapterOutput:  # type: ignore[no-untyped-def]
        win = int(3.0 * sample_rate)
        dets = []
        i = 0
        for start in range(0, max(len(samples), 1), win):
            seg = np.asarray(samples[start : start + win], dtype=np.float64)
            if seg.size < sample_rate // 2 or float(np.sqrt(np.mean(seg**2))) < 1e-3:
                continue
            spec = np.abs(np.fft.rfft(seg))
            f = np.fft.rfftfreq(seg.size, 1.0 / sample_rate)[np.argmax(spec)]
            if f < 1500:
                continue
            sci = (
                "Poecile atricapillus"
                if f < 3000
                else "Haemorhous mexicanus"
                if f < 5000
                else "Cyanocitta cristata"
            )
            common, taxon = SPECIES[sci]
            dets.append(
                WindowDetection(
                    id=f"det_{i}",
                    model_run_id=context.model_run_id,
                    label_raw=f"{sci}_{common}",
                    scientific_name=sci,
                    common_name=common,
                    taxon=taxon,
                    start_seconds=start / sample_rate,
                    end_seconds=min(start + win, len(samples)) / sample_rate,
                    confidence=0.9,
                    plausibility="unknown",
                )
            )
            i += 1
        return AdapterOutput(detections=dets, n_windows=max(1, len(samples) // win), runtime_ms=1)


def tone_registry() -> ModelRegistry:
    reg = ModelRegistry()
    reg.register(ToneAdapter())
    return reg


# ----------------------------------------------------------------- sign-in


def dev_login(client: TestClient, email: str, name: str | None = None) -> dict:
    r = client.post("/api/v1/auth/dev", json={"email": email, "name": name}, headers=CSRF)
    assert r.status_code == 200, r.text
    return r.json()


def create_org(client: TestClient, name: str = "Hilltop Farm", **extra) -> dict:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/orgs", json={"name": name, **extra}, headers=CSRF)
    assert r.status_code == 201, r.text
    return r.json()
