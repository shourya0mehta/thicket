"""Benchmark Thicket's BirdNET detections against an expert-annotated gold set.

This is the tool for the pilot validation in docs/VALIDATION.md: a partner
annotates a few hundred short clips from their own site, and this script
reports how Thicket does there, per species, with uncertainty, and proposes a
site-specific threshold table.

Annotation CSV (one row per labeled call or per species present):

    recording,scientific_name,start_seconds,end_seconds,site,annotator
    dawn_01.wav,Cardinalis cardinalis,3.2,5.0,north_meadow,AB
    dawn_01.wav,Turdus migratorius,,,north_meadow,AB      <- clip-level presence
    dawn_02.wav,,,,north_meadow,AB                           <- annotated, no target species

* ``recording`` is a path relative to ``--audio-dir``. Every recording that
  was annotated must appear at least once (use an empty species for "none").
* Species outside the annotation scope (the set of species that appear
  anywhere in the file, or ``--scope`` if given) are reported separately and
  never counted as false positives, because annotators were not asked about
  them.
* Time bounds are optional. Rows with bounds also feed the event-level
  metrics.

Metrics
  Recording level, per species: a recording is predicted positive at
  threshold t if any window of that species scores >= t. Average precision
  over recordings, and precision / recall / F1 at fixed thresholds.
  Event level, per species (time-bounded rows only): a predicted event is a
  true positive if it overlaps an annotated interval of the same species
  (with ``--tolerance`` seconds of slack); an annotated interval is found if
  any predicted event overlaps it.
  Thresholds: per species, the lowest threshold reaching ``--target-precision``
  is chosen by two-fold cross-fitting over sites (or recordings when there is
  one site) and evaluated on the other fold, so the reported precision and
  recall at the chosen threshold are out of sample.
  95% intervals: bootstrap over sites (or recordings), 1000 resamples.

    python ml/eval/gold_benchmark.py --audio-dir clips/ --annotations gold.csv \\
        --out ml/reports/pilot_north_meadow --lat 42.44 --lon -76.50 --date 2026-05-14
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "ml" / "train"))

import evalkit as ek  # noqa: E402

FIXED_THRESHOLDS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


@dataclass
class Annotation:
    recording: str
    scientific_name: str
    start: float | None
    end: float | None
    site: str
    annotator: str


@dataclass
class Pred:
    """Window-level scores for one recording: species -> list of (start, end, conf)."""

    recording: str
    windows: dict[str, list[tuple[float, float, float]]]
    duration: float


class BenchmarkError(RuntimeError):
    pass


def _float(s: str | None) -> float | None:
    s = (s or "").strip()
    return float(s) if s else None


def read_annotations(path: Path) -> list[Annotation]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    need = {"recording", "scientific_name"}
    if not rows or not need.issubset(rows[0].keys()):
        raise BenchmarkError(f"{path} must have columns {sorted(need)}")
    out = []
    for i, r in enumerate(rows, start=2):
        a = Annotation(
            recording=r["recording"].strip(),
            scientific_name=(r.get("scientific_name") or "").strip(),
            start=_float(r.get("start_seconds")),
            end=_float(r.get("end_seconds")),
            site=(r.get("site") or "").strip() or "_single_site",
            annotator=(r.get("annotator") or "").strip(),
        )
        if (a.start is None) != (a.end is None):
            raise BenchmarkError(f"row {i}: give both start_seconds and end_seconds or neither")
        if a.start is not None and a.end is not None and a.end < a.start:
            raise BenchmarkError(f"row {i}: end_seconds is before start_seconds")
        out.append(a)
    return out


# ------------------------------------------------------------------ scoring


def presence_scores(
    preds: dict[str, Pred], recordings: list[str], species: list[str]
) -> np.ndarray:
    """(n_recordings, n_species) max window confidence, 0 when never detected."""
    s = np.zeros((len(recordings), len(species)))
    for i, rec in enumerate(recordings):
        p = preds.get(rec)
        if p is None:
            continue
        for j, sp in enumerate(species):
            w = p.windows.get(sp)
            if w:
                s[i, j] = max(c for _, _, c in w)
    return s


def presence_truth(anns: list[Annotation], recordings: list[str], species: list[str]) -> np.ndarray:
    idx = {r: i for i, r in enumerate(recordings)}
    jdx = {s: j for j, s in enumerate(species)}
    y = np.zeros((len(recordings), len(species)), dtype=bool)
    for a in anns:
        if a.scientific_name in jdx:
            y[idx[a.recording], jdx[a.scientific_name]] = True
    return y


def events_at(
    windows: list[tuple[float, float, float]], t: float, gap: float
) -> list[tuple[float, float]]:
    """Consolidate one species' windows at threshold t (same rule as the product)."""
    kept = sorted((s, e) for s, e, c in windows if c + 1e-9 >= t)
    out: list[list[float]] = []
    for s, e in kept:
        if out and s - out[-1][1] <= gap + 1e-9:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def overlaps(a: tuple[float, float], b: tuple[float, float], tol: float) -> bool:
    return a[0] < b[1] + tol and b[0] < a[1] + tol


def event_counts(
    preds: dict[str, Pred],
    anns: list[Annotation],
    species: str,
    t: float,
    gap: float,
    tol: float,
    recordings: list[str],
) -> tuple[int, int, int, int]:
    """(true positive predicted events, predicted events, found intervals, annotated intervals)."""
    ann_by_rec: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for a in anns:
        if a.scientific_name == species and a.start is not None and a.end is not None:
            ann_by_rec[a.recording].append((a.start, a.end))
    tp_pred = n_pred = found = n_ann = 0
    for rec in recordings:
        truth = ann_by_rec.get(rec, [])
        p = preds.get(rec)
        evs = events_at(p.windows.get(species, []), t, gap) if p else []
        n_pred += len(evs)
        n_ann += len(truth)
        tp_pred += sum(1 for ev in evs if any(overlaps(ev, g, tol) for g in truth))
        found += sum(1 for g in truth if any(overlaps(ev, g, tol) for ev in evs))
    return tp_pred, n_pred, found, n_ann


def cross_fit_thresholds(
    y: np.ndarray, s: np.ndarray, groups: np.ndarray, target_precision: float, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Two-fold cross-fitted threshold per species. Returns (fold thresholds, test predictions)."""
    uniq = np.unique(groups)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(uniq)
    fold_of = {g: i % 2 for i, g in enumerate(perm)}
    fold = np.array([fold_of[g] for g in groups])
    n_sp = y.shape[1]
    th = np.ones((2, n_sp))
    pred = np.zeros_like(y, dtype=bool)
    for k in (0, 1):
        tr, te = fold != k, fold == k
        for j in range(n_sp):
            if y[tr, j].sum() == 0 or te.sum() == 0:
                th[k, j] = np.nan
                continue
            th[k, j] = ek.choose_threshold(
                y[tr, j],
                s[tr, j],
                mode="precision",
                target_precision=target_precision,
                min_threshold=0.1,
            )
            pred[te, j] = s[te, j] >= th[k, j]
    return th, pred


# --------------------------------------------------------------- inference


def run_birdnet(
    audio_dir: Path, recordings: list[str], args: argparse.Namespace
) -> tuple[dict[str, Pred], dict]:
    from thicket.models.base import AnalysisContext
    from thicket.models.birdnet import BirdNETAdapter, SharedBirdNET
    from thicket.services.audio_io import decode

    adapter = BirdNETAdapter(SharedBirdNET())
    adapter.load()
    rec_date = date.fromisoformat(args.date) if args.date else None
    preds: dict[str, Pred] = {}
    t0 = time.time()
    for k, rec in enumerate(recordings):
        x, sr = decode(audio_dir / rec, target_sr=48000)
        ctx = AnalysisContext(
            analysis_id="benchmark",
            model_run_id="birdnet",
            latitude=args.lat,
            longitude=args.lon,
            recording_date=rec_date,
            raw_threshold=args.floor,
            hop_seconds=args.hop,
            location_filter=args.lat is not None and args.lon is not None,
        )
        out = adapter.analyze(x, sr, ctx)
        wins: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
        for d in out.detections:
            if d.taxon in {"human", "noise", "anthropogenic", "environmental", "domestic_animal"}:
                continue
            if args.exclude_unlikely and d.plausibility == "unlikely":
                continue
            wins[d.scientific_name].append((d.start_seconds, d.end_seconds, d.confidence))
        preds[rec] = Pred(rec, dict(wins), len(x) / sr)
        if (k + 1) % 25 == 0:
            print(
                f"[benchmark] {k + 1}/{len(recordings)} recordings, {time.time() - t0:.0f}s",
                flush=True,
            )
    meta = {
        "model": "BirdNET GLOBAL 6K V2.4",
        "model_sha256": adapter.model_sha256(),
        "labels": [lab.scientific_name for lab in adapter.runtime.labels],
    }
    return preds, meta


# ------------------------------------------------------------------ report


def evaluate(
    anns: list[Annotation], preds: dict[str, Pred], label_set: set[str], args: argparse.Namespace
) -> dict:
    recordings = sorted({a.recording for a in anns})
    scope = sorted({a.scientific_name for a in anns if a.scientific_name})
    if args.scope:
        scope = sorted({s.strip() for s in Path(args.scope).read_text().splitlines() if s.strip()})
    unknown = [s for s in scope if s not in label_set]
    if unknown:
        print(
            f"[check] WARN {len(unknown)} annotated species are not BirdNET labels and are "
            f"skipped: {unknown}",
            flush=True,
        )
    species = [s for s in scope if s in label_set]
    if not species:
        raise BenchmarkError("No annotated species match the model's label set.")
    site_of = {a.recording: a.site for a in anns}
    groups = np.array([site_of[r] for r in recordings])
    n_sites = len(np.unique(groups))
    boot_groups = groups if n_sites >= 5 else np.array(recordings)

    y = presence_truth(anns, recordings, species)
    s = presence_scores(preds, recordings, species)
    per_species = []
    for j, sp in enumerate(species):
        yj, sj = y[:, j], s[:, j]
        row: dict = {
            "scientific_name": sp,
            "n_positive_recordings": int(yj.sum()),
            "n_recordings": len(recordings),
        }
        if yj.sum() and (~yj).sum():
            ap = ek.cluster_bootstrap(
                lambda i, yj=yj, sj=sj: ek.safe_ap(yj[i], sj[i]),
                boot_groups,
                n_boot=args.n_boot,
                seed=j,
            )
            row["average_precision"] = ap
        row["at_threshold"] = {}
        for t in FIXED_THRESHOLDS:
            p, r, f = ek.prf(yj, sj >= t)
            row["at_threshold"][f"{t:.1f}"] = {
                "precision": p,
                "recall": r,
                "f1": f,
                "predicted": int((sj >= t).sum()),
            }
        tp, npred, found, nann = event_counts(
            preds, anns, sp, args.report_threshold, args.merge_gap, args.tolerance, recordings
        )
        row["events_at_report_threshold"] = {
            "threshold": args.report_threshold,
            "true_positive_events": tp,
            "predicted_events": npred,
            "found_intervals": found,
            "annotated_intervals": nann,
            "event_precision": tp / npred if npred else None,
            "interval_recall": found / nann if nann else None,
        }
        per_species.append(row)

    th, pred = cross_fit_thresholds(
        y, s, groups if n_sites >= 2 else np.array(recordings), args.target_precision
    )
    table = []
    for j, sp in enumerate(species):
        p, r, f = ek.prf(y[:, j], pred[:, j])
        final = (
            ek.choose_threshold(
                y[:, j],
                s[:, j],
                mode="precision",
                target_precision=args.target_precision,
                min_threshold=0.1,
            )
            if y[:, j].sum()
            else float("nan")
        )
        table.append(
            {
                "scientific_name": sp,
                "threshold_all_data": final,
                "fold_thresholds": [None if np.isnan(v) else float(v) for v in th[:, j]],
                "cross_fit_precision": p,
                "cross_fit_recall": r,
                "cross_fit_f1": f,
                "n_positive_recordings": int(y[:, j].sum()),
            }
        )

    outside = defaultdict(int)
    for rec in recordings:
        p = preds.get(rec)
        for sp, wins in p.windows.items() if p else []:
            if sp not in scope and max(c for _, _, c in wins) >= args.report_threshold:
                outside[sp] += 1
    micro = ek.prf(y.ravel(), (s >= args.report_threshold).ravel())
    return {
        "n_recordings": len(recordings),
        "n_sites": n_sites,
        "species_in_scope": species,
        "skipped_species_not_in_model": unknown,
        "per_species": per_species,
        "threshold_table": table,
        "micro_at_report_threshold": dict(zip(("precision", "recall", "f1"), micro, strict=True)),
        "outside_scope_detections": dict(sorted(outside.items(), key=lambda kv: -kv[1])),
        "bootstrap_unit": "site" if n_sites >= 5 else "recording",
    }


def write_report(res: dict, meta: dict, args: argparse.Namespace, ann_sha: str, out: Path) -> None:
    lines = [
        "# Gold-set benchmark",
        "",
        f"Generated by `ml/eval/gold_benchmark.py`. Annotations sha256 `{ann_sha[:16]}`, model "
        f"{meta['model']} sha256 `{(meta['model_sha256'] or '')[:16]}`.",
        "",
        f"* Recordings: {res['n_recordings']} from {res['n_sites']} site(s). Bootstrap unit: "
        f"{res['bootstrap_unit']}.",
        f"* Settings: window hop {args.hop} s, raw floor {args.floor}, merge gap {args.merge_gap} s, "
        f"event tolerance {args.tolerance} s, location filter "
        f"{'on' if args.lat is not None else 'off'}, unlikely species "
        f"{'excluded' if args.exclude_unlikely else 'kept'}.",
        f"* Micro precision / recall / F1 at {args.report_threshold}: "
        f"{res['micro_at_report_threshold']['precision']:.3f} / "
        f"{res['micro_at_report_threshold']['recall']:.3f} / {res['micro_at_report_threshold']['f1']:.3f}.",
        "",
        "These numbers describe this annotated set only. They are the evidence for this site and "
        "season, not a general accuracy claim.",
        "",
        "## Per species (recording level)",
        "",
        f"| Species | Positives | AP (95% CI) | P / R at {args.report_threshold} | "
        f"Events: precision | Intervals: recall |",
        "|---|---|---|---|---|---|",
    ]
    for r in res["per_species"]:
        ap = r.get("average_precision")
        ap_s = ek.fmt_ci(ap) if ap else "n/a"
        at = r["at_threshold"].get(f"{args.report_threshold:.1f}", {})
        ev = r["events_at_report_threshold"]
        ep = (
            f"{ev['event_precision']:.2f} ({ev['true_positive_events']}/{ev['predicted_events']})"
            if ev["event_precision"] is not None
            else "n/a"
        )
        ir = (
            f"{ev['interval_recall']:.2f} ({ev['found_intervals']}/{ev['annotated_intervals']})"
            if ev["interval_recall"] is not None
            else "n/a"
        )
        lines.append(
            f"| *{r['scientific_name']}* | {r['n_positive_recordings']} | {ap_s} | "
            f"{at.get('precision', 0):.2f} / {at.get('recall', 0):.2f} | {ep} | {ir} |"
        )
    lines += [
        "",
        f"## Site threshold table (target precision {args.target_precision})",
        "",
        "Cross-fit columns are out of sample: thresholds picked on one half of the sites (or "
        "recordings) and scored on the other. `Threshold` uses all data and is what you would "
        "configure.",
        "",
        "| Species | Threshold | Cross-fit precision | Cross-fit recall | Positives |",
        "|---|---|---|---|---|",
    ]
    for t in res["threshold_table"]:
        thr = (
            "n/a" if not np.isfinite(t["threshold_all_data"]) else f"{t['threshold_all_data']:.2f}"
        )
        lines.append(
            f"| *{t['scientific_name']}* | {thr} | {t['cross_fit_precision']:.2f} | "
            f"{t['cross_fit_recall']:.2f} | {t['n_positive_recordings']} |"
        )
    if res["outside_scope_detections"]:
        lines += [
            "",
            "## Detections outside the annotation scope",
            "",
            "Not scored. Worth a listen: they are either unannotated species or false positives.",
            "",
        ]
        lines += [
            f"* *{k}*: {v} recording(s)"
            for k, v in list(res["outside_scope_detections"].items())[:30]
        ]
    if res["skipped_species_not_in_model"]:
        lines += [
            "",
            "Annotated species the model cannot predict (skipped): "
            + ", ".join(f"*{s}*" for s in res["skipped_species_not_in_model"]),
        ]
    (out / "benchmark.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--audio-dir", type=Path, required=True)
    ap.add_argument("--annotations", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--scope", default=None, help="text file of scientific names annotators labeled"
    )
    ap.add_argument("--lat", type=float, default=None)
    ap.add_argument("--lon", type=float, default=None)
    ap.add_argument("--date", default=None, help="ISO date for the range/season check")
    ap.add_argument("--exclude-unlikely", action="store_true")
    ap.add_argument("--hop", type=float, default=3.0)
    ap.add_argument("--floor", type=float, default=0.05, help="lowest window score kept")
    ap.add_argument("--merge-gap", type=float, default=1.0)
    ap.add_argument("--tolerance", type=float, default=0.5)
    ap.add_argument("--report-threshold", type=float, default=0.6)
    ap.add_argument("--target-precision", type=float, default=0.9)
    ap.add_argument("--n-boot", type=int, default=1000)
    args = ap.parse_args()

    anns = read_annotations(args.annotations)
    recordings = sorted({a.recording for a in anns})
    missing = [r for r in recordings if not (args.audio_dir / r).exists()]
    if missing:
        raise BenchmarkError(f"{len(missing)} annotated recordings are missing, e.g. {missing[:3]}")
    ann_sha = hashlib.sha256(args.annotations.read_bytes()).hexdigest()
    preds, meta = run_birdnet(args.audio_dir, recordings, args)
    res = evaluate(anns, preds, set(meta["labels"]), args)
    args.out.mkdir(parents=True, exist_ok=True)
    res_out = {
        "annotations_sha256": ann_sha,
        "model": meta["model"],
        "model_sha256": meta["model_sha256"],
        "settings": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        **res,
    }
    (args.out / "results.json").write_text(json.dumps(res_out, indent=1, default=float))
    with open(args.out / "thresholds.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "scientific_name",
                "threshold",
                "cross_fit_precision",
                "cross_fit_recall",
                "n_positive_recordings",
            ]
        )
        for t in res["threshold_table"]:
            w.writerow(
                [
                    t["scientific_name"],
                    t["threshold_all_data"],
                    round(t["cross_fit_precision"], 4),
                    round(t["cross_fit_recall"], 4),
                    t["n_positive_recordings"],
                ]
            )
    write_report(res, meta, args, ann_sha, args.out)
    print(f"[benchmark] wrote {args.out / 'benchmark.md'}")


if __name__ == "__main__":
    main()
