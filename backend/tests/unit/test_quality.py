import sys
import types

import numpy as np
import pytest
from tests.helpers import SR, tone, white_noise

from thicket.domain import quality as q


def assess(x, sr=SR, native=None, native_sr=None, duration=None, min_d=1.0, max_d=600.0):
    native = x if native is None else native
    return q.assess_quality(
        duration_seconds=duration if duration is not None else x.size / sr,
        sample_rate_hz=native_sr or sr,
        levels=q.level_stats(native),
        mono=x,
        mono_sample_rate=sr,
        min_duration_seconds=min_d,
        max_duration_seconds=max_d,
    )


def check(report, name):
    return next(c for c in report.checks if c.name == name)


def test_clean_tone_is_usable():
    x = tone(2000, 5.0, amp=0.3) + white_noise(5.0, std=0.01)
    r = assess(x)
    assert r.status.value == "usable"
    assert r.score == 1.0
    assert r.warnings == []
    assert r.peak_dbfs == pytest.approx(20 * np.log10(np.abs(x).max()), abs=0.01)
    assert r.rms_dbfs == pytest.approx(
        20 * np.log10(np.sqrt(np.mean(x.astype(float) ** 2))), abs=0.01
    )
    assert all(c.status == "pass" for c in r.checks)


def test_levels_and_dbfs():
    stats = q.level_stats(np.full(1000, 0.5, dtype=np.float32))
    assert stats.peak == pytest.approx(0.5)
    assert stats.rms == pytest.approx(0.5)
    assert stats.dc_offset == pytest.approx(0.5)
    assert q.to_dbfs(1.0) == 0.0
    assert q.to_dbfs(0.0) == q.DB_FLOOR


def test_clipping_counts_native_per_channel_samples():
    clean = tone(1000, 2.0, amp=0.3)
    hot = np.clip(tone(1000, 2.0, amp=2.0), -1, 1)
    stereo = np.stack([clean, hot], axis=1)
    stats = q.level_stats(stereo)
    assert stats.channels == 2
    # Mono mix would hide it; per-channel counting sees half the samples at full scale.
    assert 0.2 < stats.clipping_fraction < 0.5
    r = assess(stereo.mean(axis=1), native=stereo)
    assert check(r, "clipping").status == "fail"
    assert r.status.value == "not_usable"
    assert r.score <= 0.3


def test_mild_clipping_warns():
    x = tone(1000, 5.0, amp=0.5)
    x[:500] = 1.0  # 0.2% of samples
    r = assess(x)
    assert check(r, "clipping").status == "warn"
    assert r.status.value == "usable_with_warnings"
    assert r.score == pytest.approx(0.85)


def test_silence_fails_level_check():
    r = assess(np.zeros(5 * SR, dtype=np.float32))
    assert check(r, "level").status == "fail"
    assert r.peak_dbfs == q.DB_FLOOR and r.rms_dbfs == q.DB_FLOOR
    assert r.silence_fraction == 1.0
    assert r.status.value == "not_usable"


def test_mostly_silent_warns():
    x = np.zeros(10 * SR, dtype=np.float32)
    x[: 3 * SR] = tone(2000, 3.0, amp=0.3)
    r = assess(x)
    assert check(r, "silence").status == "warn"
    assert r.silence_fraction == pytest.approx(0.7, abs=0.01)


def test_low_frequency_energy_heuristic():
    wind = tone(60, 5.0, amp=0.5) + white_noise(5.0, std=0.001)
    r = assess(wind)
    assert r.low_frequency_energy_fraction > 0.95
    assert check(r, "low_frequency_noise").status == "warn"
    assert "wind" in check(r, "low_frequency_noise").message
    assert assess(white_noise(5.0)).low_frequency_energy_fraction < 0.02


def test_sample_rate_checks():
    x = tone(1000, 5.0)
    assert check(assess(x, native_sr=48000), "sample_rate").status == "pass"
    warn = check(assess(x, native_sr=22050), "sample_rate")
    assert warn.status == "warn" and "11.0 kHz" in warn.message and "15 kHz" in warn.message
    fail = assess(x, native_sr=8000)
    assert check(fail, "sample_rate").status == "fail"
    assert fail.status.value == "not_usable"


def test_duration_checks():
    short = tone(1000, 0.5)
    assert check(assess(short, min_d=1.0), "duration").status == "fail"
    assert check(assess(tone(1000, 2.0)), "duration").status == "warn"
    assert check(assess(tone(1000, 5.0), duration=700.0), "duration").status == "fail"


def test_dc_offset_warns():
    x = tone(1000, 5.0, amp=0.3) + 0.1
    assert check(assess(x), "dc_offset").status == "warn"


def test_finalize_quality_speech():
    base = assess(tone(2000, 5.0, amp=0.3))
    speech = q.finalize_quality(base, 0.83)
    assert speech.speech_detected is True
    assert check(speech, "speech").status == "warn"
    assert any("personal information" in w for w in speech.warnings)
    assert speech.status.value == "usable_with_warnings"
    quiet = q.finalize_quality(base, 0.01)
    assert quiet.speech_detected is False and check(quiet, "speech").status == "pass"
    # Idempotent: finalizing twice keeps one speech check.
    again = q.finalize_quality(speech, 0.2)
    assert [c.name for c in again.checks].count("speech") == 1
    assert q.finalize_quality(base, None) == base


def test_qc_head_hook_is_noop_without_module(monkeypatch):
    q._load_qc_head.cache_clear()
    monkeypatch.setitem(sys.modules, "thicket.models.qc_head", None)  # import raises ImportError
    base = assess(tone(2000, 5.0, amp=0.3))
    assert q.apply_qc_head(base, np.zeros((3, 1024), dtype=np.float32)) == base
    q._load_qc_head.cache_clear()


def test_qc_head_hook_adds_warnings(monkeypatch):
    class Head:
        def predict(self, embeddings):
            assert embeddings.shape == (4, 1024)
            return {"rain": 0.81, "wind": 0.2, "engine": 0.55, "bird": 0.99}

    mod = types.ModuleType("thicket.models.qc_head")
    mod.load_default = lambda: Head()
    q._load_qc_head.cache_clear()
    monkeypatch.setitem(sys.modules, "thicket.models.qc_head", mod)
    try:
        base = assess(tone(2000, 5.0, amp=0.3))
        r = q.apply_qc_head(base, np.zeros((4, 1024), dtype=np.float32))
        names = [c.name for c in r.checks if c.status == "warn"]
        # Birds are the target, never contamination.
        assert names == ["soundscape_rain", "soundscape_engine"]
        assert any(w.startswith("Rain") for w in r.warnings)
        assert r.status.value == "usable_with_warnings"
        assert q.apply_qc_head(base, None) == base
    finally:
        q._load_qc_head.cache_clear()


def test_qc_head_uses_kinds_thresholds_and_backbone(monkeypatch):
    class Head:
        category_kind = {"rain": "geophony", "wind": "geophony", "frog": "biophony"}

        def predict(self, embeddings):
            return {"rain": 0.7, "wind": 0.6, "frog": 0.9}

        def threshold(self, category):
            return {"rain": 0.5, "wind": 0.65, "frog": 0.1}[category]

        def matches_backbone(self, sha):
            return sha == "abc"

    mod = types.ModuleType("thicket.models.qc_head")
    mod.load_default = lambda: Head()
    q._load_qc_head.cache_clear()
    monkeypatch.setitem(sys.modules, "thicket.models.qc_head", mod)
    try:
        base = assess(tone(2000, 5.0, amp=0.3))
        r = q.apply_qc_head(base, np.zeros((2, 1024)), "abc")
        assert [c.name for c in r.checks if c.status == "warn"] == ["soundscape_rain"]
        assert q.apply_qc_head(base, np.zeros((2, 1024)), "other-weights") == base
    finally:
        q._load_qc_head.cache_clear()


def test_qc_head_failure_is_ignored(monkeypatch):
    class Broken:
        def predict(self, embeddings):
            raise RuntimeError("boom")

    mod = types.ModuleType("thicket.models.qc_head")
    mod.load_default = lambda: Broken()
    q._load_qc_head.cache_clear()
    monkeypatch.setitem(sys.modules, "thicket.models.qc_head", mod)
    try:
        base = assess(tone(2000, 5.0, amp=0.3))
        assert q.apply_qc_head(base, np.zeros((2, 1024))) == base
    finally:
        q._load_qc_head.cache_clear()


def test_report_values_are_finite_json():
    r = assess(np.zeros(SR * 2, dtype=np.float32))
    text = r.model_dump_json()
    assert "Infinity" not in text and "NaN" not in text
