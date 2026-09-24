"""Tests for ml/eval/gold_benchmark.py."""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ml" / "eval"))

import gold_benchmark as gb  # noqa: E402


def _ann(rec, sp, s=None, e=None, site="a"):
    return gb.Annotation(rec, sp, s, e, site, "x")


def test_events_at_merges_like_the_product():
    wins = [(0.0, 3.0, 0.9), (3.0, 6.0, 0.4), (6.0, 9.0, 0.8), (12.0, 15.0, 0.7)]
    assert gb.events_at(wins, 0.5, 1.0) == [(0.0, 3.0), (6.0, 9.0), (12.0, 15.0)]
    assert gb.events_at(wins, 0.3, 1.0) == [(0.0, 9.0), (12.0, 15.0)]


def test_event_counts_overlap_and_tolerance():
    preds = {"r1": gb.Pred("r1", {"A b": [(0.0, 3.0, 0.9), (10.0, 13.0, 0.9)]}, 20.0)}
    anns = [
        _ann("r1", "A b", 1.0, 2.0),
        _ann("r1", "A b", 13.3, 14.0),
        _ann("r1", "A b", 17.0, 18.0),
    ]
    tp, npred, found, nann = gb.event_counts(preds, anns, "A b", 0.5, 1.0, 0.5, ["r1"])
    assert (tp, npred, found, nann) == (2, 2, 2, 3)
    tp, npred, found, nann = gb.event_counts(preds, anns, "A b", 0.5, 1.0, 0.0, ["r1"])
    assert (tp, found) == (1, 1)


def test_presence_matrices_and_scope():
    recs = ["r1", "r2"]
    preds = {"r1": gb.Pred("r1", {"A b": [(0, 3, 0.8)]}, 3), "r2": gb.Pred("r2", {}, 3)}
    anns = [_ann("r1", "A b"), _ann("r2", "")]
    y = gb.presence_truth(anns, recs, ["A b"])
    s = gb.presence_scores(preds, recs, ["A b"])
    assert y.tolist() == [[True], [False]] and s.tolist() == [[0.8], [0.0]]


def test_cross_fit_thresholds_are_out_of_sample():
    rng = np.random.default_rng(0)
    y = rng.random((40, 1)) < 0.5
    s = np.where(y, 0.8, 0.2) + rng.normal(0, 0.05, y.shape)
    groups = np.array([f"g{i % 4}" for i in range(40)])
    th, pred = gb.cross_fit_thresholds(y, s, groups, 0.9)
    assert th.shape == (2, 1) and np.all(th > 0.2) and np.all(th < 0.8)
    assert (pred[:, 0] == y[:, 0]).mean() >= 0.9


def test_read_annotations_validates(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("recording,scientific_name,start_seconds,end_seconds\nx.wav,A b,2,\n")
    with pytest.raises(gb.BenchmarkError):
        gb.read_annotations(p)


@pytest.mark.birdnet
def test_end_to_end_on_fixture(tmp_path):
    fixture = REPO / "backend" / "tests" / "fixtures" / "soundscape_30s.flac"
    audio = tmp_path / "audio"
    audio.mkdir()
    (audio / "scape.flac").write_bytes(fixture.read_bytes())
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-t",
            "10",
            str(audio / "silence.wav"),
        ],
        check=True,
    )
    ann = tmp_path / "gold.csv"
    with open(ann, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["recording", "scientific_name", "start_seconds", "end_seconds", "site"])
        w.writerow(["scape.flac", "Poecile atricapillus", 0, 3, "s1"])
        w.writerow(["scape.flac", "Haemorhous mexicanus", 9, 12, "s1"])
        w.writerow(["scape.flac", "Cyanocitta cristata", 18, 24, "s1"])
        w.writerow(["silence.wav", "", "", "", "s1"])
    out = tmp_path / "out"
    subprocess.run(
        [
            sys.executable,
            str(REPO / "ml" / "eval" / "gold_benchmark.py"),
            "--audio-dir",
            str(audio),
            "--annotations",
            str(ann),
            "--out",
            str(out),
            "--n-boot",
            "50",
            "--report-threshold",
            "0.3",
        ],
        check=True,
    )
    import json

    res = json.loads((out / "results.json").read_text())
    by = {r["scientific_name"]: r for r in res["per_species"]}
    assert by["Poecile atricapillus"]["at_threshold"]["0.3"]["recall"] == 1.0
    assert by["Poecile atricapillus"]["events_at_report_threshold"]["found_intervals"] == 1
    assert (out / "benchmark.md").exists() and (out / "thresholds.csv").exists()
