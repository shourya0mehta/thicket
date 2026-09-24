"""End-to-end test of ml/train/frog_insect.py on a synthetic thicket-inat-v1 dataset.

The synthetic dataset uses the exact on-disk format written by
``ml/pipeline/collect_inat.py merge``: ``manifest.csv`` plus
``birdnet_part_XX.npz`` (and a ``perch_part_XX.npz``). Embeddings are
clustered per class, only some windows of a positive recording carry the
class signal (weak labels), and recordings belong to fake observers.

Run: pytest ml/tests -q
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ml" / "train"))
sys.path.insert(0, str(REPO / "ml" / "pipeline"))
sys.path.insert(0, str(REPO / "backend"))

import frog_insect as fi  # noqa: E402
from collect_inat import PLAN_FIELDS  # noqa: E402

TAXA = json.loads((REPO / "backend/thicket/models/data/birdnet_v24_taxa.json").read_text())
NON_BIRD = sorted(TAXA["non_bird_labels"])

FROGS = [
    ["Pseudacris crucifer", "Spring Peeper"],
    ["Anaxyrus americanus", "American Toad"],
    ["Lithobates catesbeianus", "American Bullfrog"],
]
INSECTS = [
    ["Gryllus pennsylvanicus", "Fall Field Cricket"],
    ["Magicicada septendecim", "Pharaoh Cicada"],  # not a BirdNET class
    ["Neotibicen linnei", "Linne's Cicada"],  # in config, no recordings
]
BIRDS = [["Cardinalis cardinalis", "Northern Cardinal"], ["Turdus migratorius", "American Robin"]]


def make_config(path: Path) -> Path:
    cfg = json.loads((REPO / "ml/configs/inat_v1.json").read_text())
    cfg["targets"]["frogs"] = FROGS
    cfg["targets"]["insects"] = INSECTS
    cfg["birds"]["species"] = BIRDS
    path.write_text(json.dumps(cfg))
    return path


def make_dataset(root: Path, seed: int = 0, n_per_class: int = 36, n_observers: int = 48) -> Path:
    rng = np.random.default_rng(seed)
    d = 1024
    present = [s for s, _ in FROGS + INSECTS[:2]]
    groups = {s: ("frog" if [s, c] in FROGS else "insect") for s, c in FROGS + INSECTS}
    centroids = {
        name: np.abs(rng.normal(0, 1, d)) * (rng.uniform(size=d) < 0.08)
        for name in present + ["other_anura", "bird"]
    }
    birdnet_sub = NON_BIRD + [f"{s}_{c}" for s, c in BIRDS]
    sub_index = {lab.split("_")[0]: i for i, lab in enumerate(birdnet_sub)}

    specs: list[tuple[str, str]] = []  # (group, label)
    for s in present:
        specs += [(groups[s], s)] * n_per_class
    specs += [("bird", "Cardinalis cardinalis")] * 20 + [("bird", "Turdus migratorius")] * 20
    specs += [("other_anura", "")] * 30 + [("other_orthoptera", "")] * 20 + [("mammals", "")] * 10
    rows, embs, sids, starts, rms, subs = [], [], [], [], [], []
    for i, (group, label) in enumerate(specs):
        sid = 100000 + i
        n = int(rng.integers(3, 9))
        bg = np.abs(rng.normal(0, 0.35, (n, d)))
        sub = rng.normal(-5, 0.7, (n, len(birdnet_sub)))
        key = (
            label
            if group in ("frog", "insect")
            else (
                "other_anura" if group == "other_anura" else ("bird" if group == "bird" else None)
            )
        )
        if key is not None:
            on = rng.uniform(size=n) < 0.5
            on[rng.integers(0, n)] = True
            bg[on] += 1.6 * centroids[key]
            if label in sub_index:
                sub[on, sub_index[label]] = rng.normal(1.0, 1.5, on.sum())
        r = rng.normal(-32, 4, n)
        r[rng.uniform(size=n) < 0.1] = -85.0
        embs.append(bg.astype(np.float16))
        sids.append(np.full(n, sid, dtype=np.int64))
        starts.append(np.arange(n, dtype=np.float32) * 3.0)
        rms.append(r.astype(np.float16))
        subs.append(sub.astype(np.float16))
        user = int(rng.integers(0, n_observers))
        rows.append(
            {
                "row": i,
                "group": group,
                "label": label,
                "label_common": "",
                "observation_id": 5000 + i,
                "sound_id": sid,
                "file_url": f"https://example.invalid/{sid}.wav",
                "license_code": "cc-by",
                "attribution": f"(c) user{user}, some rights reserved (CC BY)",
                "taxon_id": 1,
                "taxon_name": label,
                "common_name": "",
                "user_id": 900 + user,
                "observed_on": "2025-05-01",
                "latitude": 40.1,
                "longitude": -88.2,
                "obscured": "false",
                "status": "ok",
                "bytes": 1000,
                "sha256": f"{sid:064x}",
                "duration_s": 3.0 * n,
                "n_windows": n,
            }
        )
    # One failed download, as in real manifests.
    rows.append(
        {
            **rows[0],
            "row": len(rows),
            "sound_id": 999999,
            "status": "download_failed",
            "sha256": "",
            "n_windows": 0,
        }
    )
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=PLAN_FIELDS + ["status", "bytes", "sha256", "duration_s", "n_windows"]
        )
        w.writeheader()
        w.writerows(rows)
    emb, sid, st, rm, sb = (np.concatenate(x) for x in (embs, sids, starts, rms, subs))
    half = len(specs) // 2
    cut = int(np.searchsorted(sid, 100000 + half))
    for part, sl in ((0, slice(0, cut)), (1, slice(cut, None))):
        n = len(sid[sl])
        np.savez_compressed(
            root / f"birdnet_part_{part:02d}.npz",
            embedding=emb[sl],
            sound_id=sid[sl],
            start_s=st[sl],
            rms_dbfs=rm[sl],
            subset_logits=sb[sl],
            subset_labels=np.asarray(birdnet_sub),
            top5_index=np.zeros((n, 5), np.int16),
            top5_prob=np.zeros((n, 5), np.float16),
            max_bird_prob=np.zeros(n, np.float16),
        )
    # Perch-style part: 5 s windows, 1536-d, same recordings.
    proj = rng.normal(0, 0.05, (d, 1536))
    ids = np.unique(sid)
    pe = np.stack([emb[sid == s].astype(np.float32).mean(0) @ proj for s in ids])
    np.savez_compressed(
        root / "perch_part_00.npz",
        embedding=pe.astype(np.float16),
        sound_id=ids,
        start_s=np.zeros(len(ids), np.float32),
        subset_logits=np.zeros((0, 0), np.float16),
        subset_labels=np.asarray([]),
        model_handle=np.asarray("synthetic/perch"),
    )
    return root


@pytest.fixture(scope="module")
def run_output(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fi")
    data = make_dataset(tmp / "data")
    cfg = make_config(tmp / "config.json")
    out = tmp / "out"
    res = fi.main(
        [
            "--data",
            str(data),
            "--out",
            str(out),
            "--config",
            str(cfg),
            "--n-boot",
            "50",
            "--min-train-recordings",
            "8",
        ]
    )
    return data, cfg, out, res


def test_pipeline_runs_end_to_end(run_output):
    _, _, out, res = run_output
    assert (out / "frog_insect_v1.md").exists()
    assert (out / "results.json").exists()
    assert (out / "figures" / "frog_insect_ap.png").exists()
    report = (out / "frog_insect_v1.md").read_text()
    assert "Pre-metric checks" in report and "\u2014" not in report
    assert all(c["status"] in ("pass", "warn") for c in res["checks"])
    assert "Neotibicen linnei" in res["labels"]["not_modeled"]
    chosen = res["results"]["stage_selection"]["chosen"]
    macro_ap = res["results"][f"test_{chosen}"]["macro"]["ap"][0]
    assert macro_ap > 0.8, macro_ap  # clustered synthetic data must be learnable
    bn = res["results"]["birdnet_zero_shot"]
    assert "Pseudacris crucifer" in bn["covered"] and "Magicicada septendecim" not in bn["covered"]
    assert res["results"]["perch_comparison"]["handle"] == "synthetic/perch"
    assert "all_negatives" in res["results"]["open_set_false_positive_rate_test"]


def test_splits_are_observer_disjoint(run_output):
    _, _, out, _ = run_output
    with open(out / "splits.csv") as f:
        rows = list(csv.DictReader(f))
    by_split: dict[str, set[str]] = {}
    for r in rows:
        by_split.setdefault(r["split"], set()).add(r["user_id"])
    assert set(by_split) == {"train", "val", "test"}
    assert not by_split["train"] & by_split["val"]
    assert not by_split["train"] & by_split["test"]
    assert not by_split["val"] & by_split["test"]
    n = len(rows)
    n_train = sum(r["split"] == "train" for r in rows)
    assert 0.5 < n_train / n < 0.85


def test_exported_head_format(run_output):
    _, _, out, res = run_output
    with np.load(out / "frog_insect_head_v1.npz", allow_pickle=False) as z:
        labels = [str(x) for x in z["labels"]]
        k = len(labels)
        assert z["W1"].shape == (1024, k) and z["b1"].shape == (k,)
        assert z["embedding_mean"].shape == (1024,) and z["embedding_std"].dtype == np.float32
        assert z["thresholds"].shape == (k,) and float(z["temperature"]) > 0
        assert set(str(t) for t in z["taxa"]) <= {"amphibian", "insect"}
        assert len(z["common_names"]) == k
        assert "W2" not in z.files
    assert labels == res["labels"]["modeled"]


def test_backend_loader_accepts_head(run_output):
    _, _, out, _ = run_output
    try:
        from thicket.models.frog_insect import FrogInsectHead
    except Exception as exc:  # noqa: BLE001 - backend module is optional for ml tests
        pytest.skip(f"backend frog_insect module not importable: {exc}")
    head = FrogInsectHead.from_npz(out / "frog_insect_head_v1.npz")
    p = head.predict_proba(np.zeros((4, 1024), np.float32))
    assert p.shape == (4, head.n_classes) and np.all((p >= 0) & (p <= 1))


def test_split_function_is_seeded_and_disjoint():
    rng = np.random.default_rng(1)
    n = 300
    rec = {
        "label": np.array(rng.choice(["a", "b", "c", ""], n)),
        "group": np.array(["frog"] * n),
        "user_id": np.array([str(u) for u in rng.integers(0, 60, n)]),
    }
    s1 = fi.observer_split(rec, (0.7, 0.15, 0.15), seed=3)
    s2 = fi.observer_split(rec, (0.7, 0.15, 0.15), seed=3)
    assert np.array_equal(s1, s2)
    fi.assert_observer_disjoint(rec["user_id"], s1)
    bad = s1.copy()
    u0 = rec["user_id"][s1 == "train"][0]
    bad[np.flatnonzero(rec["user_id"] == u0)[0]] = "test"
    if (rec["user_id"] == u0).sum() > 1:
        with pytest.raises(fi.ValidationError):
            fi.assert_observer_disjoint(rec["user_id"], bad)


def test_validation_rejects_window_count_mismatch(tmp_path):
    data = make_dataset(tmp_path / "data", n_per_class=12, n_observers=20)
    cfg = make_config(tmp_path / "config.json")
    with open(data / "manifest.csv") as f:
        rows = list(csv.DictReader(f))
    rows[3]["n_windows"] = str(int(rows[3]["n_windows"]) + 1)
    with open(data / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(fi.ValidationError, match="window count"):
        fi.main(
            [
                "--data",
                str(data),
                "--out",
                str(tmp_path / "out"),
                "--config",
                str(cfg),
                "--n-boot",
                "20",
            ]
        )


def test_validation_rejects_unknown_label(tmp_path):
    data = make_dataset(tmp_path / "data", n_per_class=12, n_observers=20)
    cfg = json.loads(make_config(tmp_path / "config.json").read_text())
    cfg["targets"]["frogs"] = FROGS[1:]  # Pseudacris crucifer now missing from the config
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    with pytest.raises(fi.ValidationError, match="not in config targets"):
        fi.main(
            [
                "--data",
                str(data),
                "--out",
                str(tmp_path / "out"),
                "--config",
                str(tmp_path / "config.json"),
                "--n-boot",
                "20",
            ]
        )


def test_validation_rejects_bad_split_fractions(tmp_path):
    with pytest.raises(fi.ValidationError, match="fractions"):
        fi.main(
            [
                "--data",
                str(tmp_path),
                "--out",
                str(tmp_path / "o"),
                "--train-frac",
                "0.9",
                "--val-frac",
                "0.2",
            ]
        )
