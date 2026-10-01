"""Package a trained frog/insect head for the backend, applying the release bar.

Reads the output folder of ``ml/train/frog_insect.py`` (``results.json`` and
``frog_insect_head_v1.npz``) and writes a head that contains ONLY the classes
that pass the release bar, plus a JSON model card next to it:

* at least ``min_test_recordings`` test recordings from ``min_test_observers``
  observers (checked by the trainer, read from ``readiness``);
* test AP lower 95% bound of at least ``--min-ap-lower`` (default 0.5), a
  product bar well above chance (positives are about 2% of test recordings);
* where BirdNET has the same species, the head's test AP is not below
  BirdNET's (point estimate).

Classes that fail stay out of the shipped head, so they can never fire.

    python ml/train/package_head.py --run /path/to/model_dir \\
        --out backend/thicket/models/data/frog_insect_v1.npz
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--min-ap-lower", type=float, default=0.5)
    args = ap.parse_args()

    res = json.loads((args.run / "results.json").read_text())
    head = np.load(args.run / "frog_insect_head_v1.npz", allow_pickle=False)
    stage = res["results"]["stage_selection"]["chosen"]
    test = res["results"][f"test_{stage}"]
    per_class = test["per_class"]
    ready = res["readiness"]["classes"]
    bn = res["results"]["birdnet_zero_shot"]
    bn_pc = bn["test"]["per_class"]

    labels = [str(x) for x in head["labels"]]
    keep: list[int] = []
    decisions: dict[str, dict] = {}
    for i, lab in enumerate(labels):
        pc = per_class.get(lab, {})
        rd = ready.get(lab, {})
        ap_ci = pc.get("ap") or [float("nan")] * 3
        reasons = []
        if not rd.get("meets_bar"):
            reasons.append(
                f"only {rd.get('test_recordings', 0)} test recordings from "
                f"{rd.get('test_observers', 0)} observers"
            )
        if not (ap_ci[1] >= args.min_ap_lower):
            reasons.append(f"test AP lower 95% bound {ap_ci[1]:.3f} is below {args.min_ap_lower}")
        if lab in bn_pc and bn_pc[lab].get("ap") and ap_ci[0] < bn_pc[lab]["ap"][0]:
            reasons.append(
                f"test AP {ap_ci[0]:.3f} below BirdNET's {bn_pc[lab]['ap'][0]:.3f} for this species"
            )
        decisions[lab] = {
            "released": not reasons,
            "reasons": reasons,
            "test_recordings": rd.get("test_recordings"),
            "test_observers": rd.get("test_observers"),
            "ap": ap_ci,
            "precision": pc.get("precision"),
            "recall": pc.get("recall"),
            "f1": pc.get("f1"),
            "birdnet_ap": bn_pc.get(lab, {}).get("ap"),
        }
        if not reasons:
            keep.append(i)

    idx = np.asarray(keep, dtype=np.int64)
    arrays = {
        "W1": head["W1"][:, idx],
        "b1": head["b1"][idx],
        "labels": head["labels"][idx],
        "common_names": head["common_names"][idx],
        "taxa": head["taxa"][idx],
        "thresholds": head["thresholds"][idx],
        "temperature": head["temperature"],
        "embedding_mean": head["embedding_mean"],
        "embedding_std": head["embedding_std"],
        "format": head["format"],
        "pooling": head["pooling"],
        "stage": head["stage"],
        "manifest_sha256": head["manifest_sha256"],
        "created": np.asarray(str(head["created"])),
        "license": head["license"],
    }
    if "W2" in head.files:  # MLP: keep the hidden layer, slice the output layer
        arrays["W1"] = head["W1"]
        arrays["b1"] = head["b1"]
        arrays["W2"] = head["W2"][:, idx]
        arrays["b2"] = head["b2"][idx]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, **arrays)
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()

    released = [lab for lab in labels if decisions[lab]["released"]]
    macro = test["macro"]
    card = {
        "name": "Thicket frog and insect head",
        "version": args.version,
        "license": "CC BY-NC-SA 4.0",
        "description": (
            f"Multi-label head on BirdNET v2.4 embeddings for {len(released)} Northeastern and "
            "Midwestern US frogs, toads, crickets, katydids and cicadas. Trained and tested on "
            "research-grade iNaturalist recordings with observer-disjoint splits. Clip-level "
            "labels, so window timing is approximate. Experimental: not validated on passive "
            "field recordings."
        ),
        "packaged": date.today().isoformat(),
        "sha256": digest,
        "stage": stage,
        "temperature": float(head["temperature"]),
        "dataset_manifest_sha256": str(head["manifest_sha256"]),
        "benchmark": {
            "split": "observer-disjoint 70/15/15, recording level (max over 3 s windows)",
            "macro_all_modeled": {k: macro[k] for k in ("ap", "f1", "precision", "recall", "auc")},
            "macro_ap_head_minus_birdnet_on_shared_species": bn[
                "macro_ap_difference_head_minus_birdnet"
            ],
            "open_set_false_positive_rate": res["results"]["open_set_false_positive_rate_test"],
            "calibration_ece": {
                "raw": res["results"]["calibration_test"]["raw"]["ece"],
                "calibrated": res["results"]["calibration_test"]["calibrated"]["ece"],
            },
            "report": "ml/reports/frog_insect_v1.md",
        },
        "release_bar": {
            "min_test_recordings": res["readiness"]["min_test_recordings"],
            "min_test_observers": res["readiness"]["min_test_observers"],
            "min_ap_lower_95": args.min_ap_lower,
            "not_worse_than_birdnet_ap": True,
        },
        "released_classes": released,
        "withheld_classes": {
            lab: d["reasons"] for lab, d in decisions.items() if not d["released"]
        },
        "classes": decisions,
    }
    args.out.with_suffix(".json").write_text(json.dumps(card, indent=1) + "\n")
    print(f"released {len(released)} of {len(labels)} classes -> {args.out} ({digest[:12]})")
    for lab, d in decisions.items():
        if not d["released"]:
            print(f"  withheld {lab}: {'; '.join(d['reasons'])}")


if __name__ == "__main__":
    main()
