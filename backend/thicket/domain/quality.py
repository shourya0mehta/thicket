"""Audio quality control (QC).

QC runs in two passes. :func:`assess_quality` works on the signal alone (it
also powers previews); :func:`finalize_quality` adds the speech check once
BirdNET has produced its "Human vocal" scores, and :func:`apply_qc_head`
adds soundscape contamination flags when the optional QC head is installed.

Measurements
------------
* Levels use the decoded file at its native sample rate, every channel:
  peak dBFS = 20 log10(max |x|); RMS dBFS = 20 log10(sqrt(mean x^2)), both
  relative to digital full scale (a full-scale square wave is 0 dBFS, a
  full-scale sine is -3 dBFS) and floored at -120 dBFS.
* Clipping fraction: share of native samples with |x| >= 0.999.
* DC offset: largest per-channel mean.
* Silence fraction: share of 50 ms frames of the 48 kHz mono mix whose RMS is
  below -60 dBFS.
* Low-frequency energy fraction: share of Welch PSD energy below 200 Hz
  (DC excluded) in the 48 kHz mono mix; a wind and handling-noise heuristic.

Score
-----
A transparent 0..1 heuristic, not a probability::

    score = clamp(1 - 0.15 * n_warn - 0.40 * n_fail, 0, 1)

and at most 0.3 when any check fails. ``status`` is ``not_usable`` when any
check fails, ``usable_with_warnings`` when any warns, else ``usable``.
"""

from __future__ import annotations

import importlib
import logging
import math
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from thicket.api.schemas import QualityCheck, QualityReport, QualityStatus
from thicket.domain.spectral import frame_blocks, welch_psd

log = logging.getLogger(__name__)

DB_FLOOR = -120.0
CLIP_LEVEL = 0.999
CLIP_WARN_FRACTION = 0.001
CLIP_FAIL_FRACTION = 0.10
SILENT_PEAK_DBFS = -90.0
QUIET_RMS_DBFS = -60.0
SILENCE_FRAME_SECONDS = 0.05
SILENCE_FRAME_DBFS = -60.0
SILENCE_WARN_FRACTION = 0.5
LOW_FREQ_CUTOFF_HZ = 200.0
# Distant traffic and rumble routinely put 80 to 90% of energy below 200 Hz;
# wind on the microphone or handling pushes it above 95%.
LOW_FREQ_WARN_FRACTION = 0.95
DC_WARN = 0.02
SAMPLE_RATE_WARN_HZ = 32_000
SAMPLE_RATE_FAIL_HZ = 16_000
BIRDNET_MAX_HZ = 15_000
BIRDNET_WINDOW_SECONDS = 3.0
SPEECH_PROBABILITY = 0.5
QC_HEAD_WARN_PROBABILITY = 0.5

PRIVACY_NOTE = (
    "Speech can contain personal information. Audio is deleted after analysis unless "
    "retention is enabled; review before sharing this recording or its exports."
)


def to_dbfs(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        return DB_FLOOR
    return max(DB_FLOOR, 20.0 * math.log10(value))


@dataclass
class LevelStats:
    peak: float
    rms: float
    clipping_fraction: float
    dc_offset: float
    total_samples: int
    channels: int
    # Per-channel RMS (linear, 0..1) from the original channels; schema 3.
    channel_rms: list[float] = field(default_factory=list)


@dataclass
class LevelAccumulator:
    """Streaming level statistics over native-rate, per-channel blocks."""

    channels: int = 0
    peak: float = 0.0
    clipped: int = 0
    total: int = 0
    sum_squares: float = 0.0
    channel_sums: np.ndarray = field(default_factory=lambda: np.zeros(0))
    channel_counts: int = 0
    channel_sum_squares: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def update(self, block: np.ndarray) -> None:
        """``block`` is (frames,) or (frames, channels) float in [-1, 1]."""
        x = np.asarray(block, dtype=np.float64)
        if x.ndim == 1:
            x = x[:, None]
        if x.size == 0:
            return
        if self.channels == 0:
            self.channels = x.shape[1]
            self.channel_sums = np.zeros(self.channels)
            self.channel_sum_squares = np.zeros(self.channels)
        ax = np.abs(x)
        self.peak = max(self.peak, float(ax.max()))
        self.clipped += int(np.count_nonzero(ax >= CLIP_LEVEL))
        self.total += int(x.size)
        sq = x * x
        self.sum_squares += float(np.sum(sq))
        self.channel_sums += x.sum(axis=0)
        self.channel_sum_squares += sq.sum(axis=0)
        self.channel_counts += x.shape[0]

    def result(self) -> LevelStats:
        if self.total == 0:
            return LevelStats(0.0, 0.0, 0.0, 0.0, 0, max(self.channels, 1))
        dc = self.channel_sums / max(self.channel_counts, 1)
        per_channel = np.sqrt(self.channel_sum_squares / max(self.channel_counts, 1))
        return LevelStats(
            peak=self.peak,
            rms=math.sqrt(self.sum_squares / self.total),
            clipping_fraction=self.clipped / self.total,
            dc_offset=float(dc[np.argmax(np.abs(dc))]) if dc.size else 0.0,
            total_samples=self.total,
            channels=self.channels,
            channel_rms=[float(v) for v in per_channel],
        )


def level_stats(samples: np.ndarray) -> LevelStats:
    acc = LevelAccumulator()
    acc.update(samples)
    return acc.result()


def silence_fraction(mono: np.ndarray, sample_rate: int) -> float:
    """Share of 50 ms frames whose RMS is below -60 dBFS."""
    x = np.asarray(mono)
    if x.size == 0:
        return 1.0
    frame = max(1, int(round(SILENCE_FRAME_SECONDS * sample_rate)))
    threshold = 10 ** (SILENCE_FRAME_DBFS / 20.0)
    if x.size < frame:  # one partial frame
        y = np.asarray(x, dtype=np.float64)
        return float(np.sqrt(np.mean(y * y)) < threshold)
    quiet = total = 0
    for frames in frame_blocks(x, frame):  # bounded memory on long recordings
        rms = np.sqrt(np.mean(frames * frames, axis=1))
        quiet += int(np.count_nonzero(rms < threshold))
        total += rms.size
    return quiet / total


def low_frequency_fraction(mono: np.ndarray, sample_rate: int) -> float:
    """Share of Welch PSD energy below 200 Hz (DC bin excluded)."""
    x = np.asarray(mono)
    if x.size < 64:
        return 0.0
    f, p = welch_psd(x, sample_rate, nperseg=4096)
    keep = f > 0
    total = float(np.sum(p[keep]))
    if total <= 0 or not math.isfinite(total):
        return 0.0
    low = float(np.sum(p[keep & (f < LOW_FREQ_CUTOFF_HZ)]))
    return low / total


def summarize(
    base: dict,
    checks: list[QualityCheck],
) -> QualityReport:
    """Build a QualityReport: status, score and warnings from the checks."""
    n_warn = sum(1 for c in checks if c.status == "warn")
    n_fail = sum(1 for c in checks if c.status == "fail")
    score = min(1.0, max(0.0, 1.0 - 0.15 * n_warn - 0.40 * n_fail))
    if n_fail:
        score = min(score, 0.3)
        status = QualityStatus.not_usable
    elif n_warn:
        status = QualityStatus.usable_with_warnings
    else:
        status = QualityStatus.usable
    warnings = [c.message for c in checks if c.status != "pass"]
    return QualityReport(
        status=status,
        score=round(score, 3),
        checks=checks,
        warnings=warnings,
        **base,
    )


def _base_fields(report: QualityReport) -> dict:
    return {
        "peak_dbfs": report.peak_dbfs,
        "rms_dbfs": report.rms_dbfs,
        "clipping_fraction": report.clipping_fraction,
        "silence_fraction": report.silence_fraction,
        "low_frequency_energy_fraction": report.low_frequency_energy_fraction,
        "speech_detected": report.speech_detected,
    }


def assess_quality(
    *,
    duration_seconds: float,
    sample_rate_hz: int,
    levels: LevelStats,
    mono: np.ndarray,
    mono_sample_rate: int,
    min_duration_seconds: float,
    max_duration_seconds: float,
) -> QualityReport:
    """Signal-level QC. Speech is added later by :func:`finalize_quality`."""
    peak_db = round(to_dbfs(levels.peak), 2)
    rms_db = round(to_dbfs(levels.rms), 2)
    silence = round(silence_fraction(mono, mono_sample_rate), 4)
    low = round(low_frequency_fraction(mono, mono_sample_rate), 4)
    clip = round(levels.clipping_fraction, 6)
    checks: list[QualityCheck] = []

    # Duration
    if duration_seconds < min_duration_seconds:
        checks.append(
            QualityCheck(
                name="duration",
                value=round(duration_seconds, 3),
                unit="s",
                status="fail",
                message=(
                    f"The recording is {duration_seconds:.2f} s long; at least "
                    f"{min_duration_seconds:.1f} s is needed."
                ),
            )
        )
    elif duration_seconds > max_duration_seconds:
        checks.append(
            QualityCheck(
                name="duration",
                value=round(duration_seconds, 3),
                unit="s",
                status="fail",
                message=(
                    f"The recording is {duration_seconds:.0f} s long, over the "
                    f"{max_duration_seconds:.0f} s limit. Trim it before analysis."
                ),
            )
        )
    elif duration_seconds < BIRDNET_WINDOW_SECONDS:
        checks.append(
            QualityCheck(
                name="duration",
                value=round(duration_seconds, 3),
                unit="s",
                status="warn",
                message=(
                    "The recording is shorter than one 3 s analysis window, so the window "
                    "is padded with silence."
                ),
            )
        )
    else:
        checks.append(
            QualityCheck(
                name="duration",
                value=round(duration_seconds, 3),
                unit="s",
                status="pass",
                message=f"Duration of {duration_seconds:.1f} s is within the supported range.",
            )
        )

    # Sample rate / band
    nyq_khz = sample_rate_hz / 2000.0
    if sample_rate_hz < SAMPLE_RATE_FAIL_HZ:
        checks.append(
            QualityCheck(
                name="sample_rate",
                value=float(sample_rate_hz),
                unit="Hz",
                status="fail",
                message=(
                    f"The sample rate of {sample_rate_hz} Hz is too low: content above "
                    f"{nyq_khz:.1f} kHz is missing. At least {SAMPLE_RATE_FAIL_HZ} Hz is required."
                ),
            )
        )
    elif sample_rate_hz < SAMPLE_RATE_WARN_HZ:
        checks.append(
            QualityCheck(
                name="sample_rate",
                value=float(sample_rate_hz),
                unit="Hz",
                status="warn",
                message=(
                    f"The sample rate of {sample_rate_hz} Hz drops content above {nyq_khz:.1f} kHz. "
                    f"BirdNET listens up to {BIRDNET_MAX_HZ // 1000} kHz, so high-pitched "
                    "species may be missed."
                ),
            )
        )
    else:
        checks.append(
            QualityCheck(
                name="sample_rate",
                value=float(sample_rate_hz),
                unit="Hz",
                status="pass",
                message=f"The sample rate of {sample_rate_hz} Hz covers the band BirdNET analyzes.",
            )
        )

    # Clipping
    if clip >= CLIP_FAIL_FRACTION:
        status, msg = (
            "fail",
            f"{clip * 100:.1f}% of samples are clipped. The audio is heavily distorted; "
            "record again with lower gain.",
        )
    elif clip >= CLIP_WARN_FRACTION:
        status, msg = (
            "warn",
            f"{clip * 100:.2f}% of samples are clipped, so loud sounds may be distorted. "
            "Lower the recorder gain if you can.",
        )
    else:
        status, msg = "pass", "No meaningful clipping."
    checks.append(
        QualityCheck(name="clipping", value=clip, unit="fraction", status=status, message=msg)
    )

    # Level
    if peak_db <= SILENT_PEAK_DBFS:
        status, msg = "fail", "The recording is silent or nearly silent."
    elif rms_db < QUIET_RMS_DBFS:
        status, msg = (
            "warn",
            f"The level is very low (RMS {rms_db:.0f} dBFS); quiet or distant calls may be missed.",
        )
    else:
        status, msg = "pass", f"The level is adequate (RMS {rms_db:.0f} dBFS)."
    checks.append(QualityCheck(name="level", value=rms_db, unit="dBFS", status=status, message=msg))

    # Silence
    if peak_db > SILENT_PEAK_DBFS and silence >= SILENCE_WARN_FRACTION:
        status, msg = (
            "warn",
            f"{silence * 100:.0f}% of the recording is near silence (below -60 dBFS).",
        )
    else:
        status, msg = "pass", f"{silence * 100:.0f}% of the recording is near silence."
    checks.append(
        QualityCheck(name="silence", value=silence, unit="fraction", status=status, message=msg)
    )

    # Low-frequency energy (wind / handling)
    if low >= LOW_FREQ_WARN_FRACTION:
        status, msg = (
            "warn",
            f"{low * 100:.0f}% of the sound energy is below 200 Hz, which often means wind "
            "or handling noise.",
        )
    else:
        status, msg = (
            "pass",
            f"{low * 100:.0f}% of the sound energy is below 200 Hz. Distant traffic or "
            f"wind often does this; Thicket warns at {LOW_FREQ_WARN_FRACTION * 100:.0f}%.",
        )
    checks.append(
        QualityCheck(
            name="low_frequency_noise", value=low, unit="fraction", status=status, message=msg
        )
    )

    # DC offset
    dc = round(levels.dc_offset, 5)
    if abs(dc) > DC_WARN:
        status, msg = (
            "warn",
            f"A DC offset of {dc:+.3f} was found; the recorder or cable may be faulty.",
        )
    else:
        status, msg = "pass", "No significant DC offset."
    checks.append(
        QualityCheck(name="dc_offset", value=dc, unit="fraction", status=status, message=msg)
    )

    base = {
        "peak_dbfs": peak_db,
        "rms_dbfs": rms_db,
        "clipping_fraction": clip,
        "silence_fraction": silence,
        "low_frequency_energy_fraction": low,
        "speech_detected": False,
    }
    return summarize(base, checks)


def finalize_quality(report: QualityReport, human_vocal_max: float | None) -> QualityReport:
    """Add the speech check from BirdNET's per-window 'Human vocal' probability."""
    checks = [c for c in report.checks if c.name != "speech"]
    base = _base_fields(report)
    if human_vocal_max is None or not math.isfinite(human_vocal_max):
        return summarize(base, checks)
    p = round(float(human_vocal_max), 4)
    detected = p >= SPEECH_PROBABILITY
    if detected:
        checks.append(
            QualityCheck(
                name="speech",
                value=p,
                unit="probability",
                status="warn",
                message=f"Human speech may be present (probability {p:.2f}). {PRIVACY_NOTE}",
            )
        )
    else:
        checks.append(
            QualityCheck(
                name="speech",
                value=p,
                unit="probability",
                status="pass",
                message="No human speech was detected.",
            )
        )
    base["speech_detected"] = detected
    return summarize(base, checks)


# ------------------------------------------------------------------ QC head

_QC_LABELS = {
    "rain": "Rain",
    "wind": "Wind",
    "thunder": "Thunder",
    "water": "Running or splashing water",
    "engine": "Engine or traffic noise",
    "engine_machinery": "Engine or machinery noise",
    "traffic": "Traffic noise",
    "aircraft": "Aircraft noise",
    "machinery": "Machinery noise",
    "human": "Human activity",
    "human_nonspeech": "Human sounds other than speech",
    "speech": "Human speech",
    "domestic_animal": "Domestic animals",
    "handling": "Handling noise",
}
# Category kinds that contaminate a wildlife soundscape. Target biophony
# (bird, insect, frog) is never a QC warning.
_CONTAMINATION_KINDS = frozenset({"geophony", "anthropophony", "biophony_non_target"})


@lru_cache(maxsize=1)
def _load_qc_head():  # pragma: no cover - exercised via monkeypatch in tests
    try:
        module = importlib.import_module("thicket.models.qc_head")
    except ImportError:
        return None
    try:
        return module.load_default()
    except Exception:  # noqa: BLE001 - optional component must never break analysis
        log.warning("qc head unavailable; skipping soundscape QC", exc_info=True)
        return None


def _is_contamination(head: object, category: str) -> bool:
    kinds = getattr(head, "category_kind", None)
    if isinstance(kinds, dict) and category in kinds:
        return kinds[category] in _CONTAMINATION_KINDS
    return category not in {"bird", "birds", "insect", "insects", "frog", "frogs", "amphibian"}


def _category_threshold(head: object, category: str) -> float:
    """At least 0.5, or the head's own calibrated threshold when it is stricter."""
    thr = QC_HEAD_WARN_PROBABILITY
    getter = getattr(head, "threshold", None)
    if callable(getter):
        try:
            thr = max(thr, float(getter(category)))
        except Exception:  # noqa: BLE001
            pass
    return thr


def apply_qc_head(
    report: QualityReport,
    embeddings: np.ndarray | None,
    backbone_sha256: str | None = None,
) -> QualityReport:
    """Add soundscape contamination flags from the optional QC head.

    No-op unless ``thicket.models.qc_head`` is importable and its
    ``load_default()`` succeeds. The head's ``predict(embeddings)`` returns
    clip-level probabilities per category. A category becomes a ``warn``
    check when it is a contamination source (rain, wind, water, engines,
    human sounds, domestic animals; never target birds, insects or frogs)
    and its probability is above 0.5, or above the head's own calibrated
    threshold when that is stricter. If the head reports the BirdNET weights
    it was trained on and they differ from ``backbone_sha256``, it is skipped.
    """
    if embeddings is None or len(embeddings) == 0:
        return report
    head = _load_qc_head()
    if head is None:
        return report
    matches = getattr(head, "matches_backbone", None)
    if backbone_sha256 and callable(matches) and not matches(backbone_sha256):
        log.warning("qc head trained on different BirdNET weights; skipping soundscape QC")
        return report
    try:
        probs = head.predict(np.asarray(embeddings, dtype=np.float32))
    except Exception:  # noqa: BLE001
        log.warning("qc head prediction failed; skipping soundscape QC", exc_info=True)
        return report
    checks = [c for c in report.checks if not c.name.startswith("soundscape")]
    clean = {
        str(k): float(v)
        for k, v in dict(probs).items()
        if v is not None and math.isfinite(float(v)) and _is_contamination(head, str(k))
    }
    flagged = sorted(
        ((k, p) for k, p in clean.items() if p > _category_threshold(head, k)),
        key=lambda kv: (-kv[1], kv[0]),
    )
    for cat, p in flagged:
        label = _QC_LABELS.get(cat, cat.replace("_", " ").capitalize())
        checks.append(
            QualityCheck(
                name=f"soundscape_{cat}",
                value=round(p, 4),
                unit="probability",
                status="warn",
                message=(
                    f"{label} is likely present (score {p:.2f}); it can mask calls and "
                    "lower detection rates."
                ),
            )
        )
    if not flagged:
        top = max(clean.values(), default=0.0)
        checks.append(
            QualityCheck(
                name="soundscape",
                value=round(top, 4),
                unit="probability",
                status="pass",
                message="No strong rain, wind, water, engine or other contamination was detected.",
            )
        )
    return summarize(_base_fields(report), checks)
