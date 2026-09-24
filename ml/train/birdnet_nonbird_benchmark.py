"""Coarse benchmark of BirdNET v2.4's built-in amphibian and insect labels on ESC-50.

Question: when a clip contains a frog or an insect, does any BirdNET amphibian
or insect label fire, and how often do those labels fire on other sounds?
This is a taxon-level check only. ESC-50 clips are not species labeled and
are not necessarily North American, while BirdNET's amphibian and insect
labels are North American species (plus a few others).

Reads the cached ESC-50 features written by ``esc50_qc.py features``.
Optionally runs one real North American toad recording from the
OpenSoundscape test suite as a smoke check (``--smoke``).

Writes ``ml/reports/birdnet_nonbird_benchmark.md``,
``ml/reports/birdnet_nonbird_results.json`` and a figure.

    python ml/train/birdnet_nonbird_benchmark.py --data /home/claude/data/esc50 --smoke
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "backend"))

import esc50_qc as q  # noqa: E402
import evalkit as ek  # noqa: E402

REPORT = REPO / "ml" / "reports" / "birdnet_nonbird_benchmark.md"
RESULTS = REPO / "ml" / "reports" / "birdnet_nonbird_results.json"
FIG = REPO / "ml" / "reports" / "figures" / "birdnet_nonbird_pr.png"
THRESHOLDS = [round(t, 1) for t in np.arange(0.1, 0.95, 0.1)]
TASKS = {
    "amphibian": {"positives": ["frog"], "taxon": "amphibian"},
    "insect": {"positives": ["insects", "crickets"], "taxon": "insect"},
}
SMOKE_URL = "https://raw.githubusercontent.com/kitzeslab/opensoundscape/master/tests/audio/great_plains_toad.wav"


def taxon_scores(
    F: dict, taxon: str, first_window_only: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """Clip score = max over windows and over labels of the taxon; plus argmax label."""
    taxa = F["birdnet_taxa"]
    cols = np.flatnonzero(taxa == taxon)
    P = ek.sigmoid(F["logits"][:, cols].astype(np.float32))
    bounds = q.clip_bounds(F)
    Pc = P[bounds[:-1]] if first_window_only else np.maximum.reduceat(P, bounds[:-1], axis=0)
    return Pc.max(1), cols[np.argmax(Pc, 1)]


def top1_taxon(F: dict) -> np.ndarray:
    """Taxon of BirdNET's single highest label per clip (max over windows)."""
    P = ek.sigmoid(F["logits"].astype(np.float32))
    Pc = np.maximum.reduceat(P, q.clip_bounds(F)[:-1], axis=0)
    return F["birdnet_taxa"][np.argmax(Pc, 1)]


def evaluate(F: dict, n_boot: int) -> dict:
    esc = F["category"]
    groups = F["src_file"]
    labels = F["birdnet_labels"]
    out: dict = {}
    top1 = top1_taxon(F)
    for name, spec in TASKS.items():
        y = np.isin(esc, spec["positives"])
        s, arg = taxon_scores(F, spec["taxon"])
        s1, _ = taxon_scores(F, spec["taxon"], first_window_only=True)
        rows = []
        for t in THRESHOLDS:
            d = s >= t
            tp, fp = int((d & y).sum()), int((d & ~y).sum())
            row = {
                "threshold": t,
                "tp": tp,
                "fp": fp,
                "fn": int((~d & y).sum()),
                "precision": ek.wilson(tp, tp + fp),
                "recall": ek.wilson(tp, int(y.sum())),
                "recall_by_class": {
                    c: ek.wilson(int((d & (esc == c)).sum()), int((esc == c).sum()))
                    for c in spec["positives"]
                },
                "false_positive_rate": ek.wilson(fp, int((~y).sum())),
                "recall_first_window_only": ek.wilson(int(((s1 >= t) & y).sum()), int(y.sum())),
            }
            fp_classes = Counter(esc[d & ~y].tolist()).most_common(5)
            row["top_false_positive_classes"] = fp_classes
            rows.append(row)
        fired_labels = Counter(str(labels[a]) for a in arg[y & (s >= 0.1)]).most_common(8)
        out[name] = {
            "positives": spec["positives"],
            "n_pos": int(y.sum()),
            "n_neg": int((~y).sum()),
            "n_birdnet_labels": int((F["birdnet_taxa"] == spec["taxon"]).sum()),
            "ap": ek.cluster_bootstrap(
                lambda i, y=y, s=s: ek.safe_ap(y[i], s[i]), groups, n_boot, 1
            ),
            "auc": ek.cluster_bootstrap(
                lambda i, y=y, s=s: ek.safe_auc(y[i], s[i]), groups, n_boot, 2
            ),
            "median_score_positives": float(np.median(s[y])),
            "median_score_negatives": float(np.median(s[~y])),
            "by_threshold": rows,
            "top_labels_on_positives_at_0.1": fired_labels,
            "top1_taxon_on_positives": {
                c: dict(Counter(top1[esc == c].tolist())) for c in spec["positives"]
            },
        }
    return out


def smoke(data: Path) -> dict | None:
    """One real North American toad file (OpenSoundscape tests, MIT repo). Anecdote only."""
    import urllib.request

    from thicket.models.birdnet_runtime import BirdNETRuntime, frame_windows
    from thicket.services.audio_io import decode

    dest = data / "smoke" / "great_plains_toad.wav"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        try:
            urllib.request.urlretrieve(SMOKE_URL, dest)
        except OSError as exc:
            print(f"[smoke] download failed: {exc}")
            return None
    rt = BirdNETRuntime()
    x, _ = decode(dest, target_sr=48000)
    win, st = frame_windows(x)
    logits, _ = rt.infer(win)
    p = rt.sigmoid(logits).max(0)
    order = np.argsort(-p)[:5]
    taxa = np.array([lab.taxon for lab in rt.labels])
    return {
        "file": SMOKE_URL,
        "duration_s": round(len(x) / 48000, 2),
        "n_windows": int(len(st)),
        "top5": [[rt.labels[i].raw, round(float(p[i]), 3), rt.labels[i].taxon] for i in order],
        "max_amphibian": round(float(p[taxa == "amphibian"].max()), 3),
        "great_plains_toad_prob": round(float(p[rt.index_by_scientific["Anaxyrus cognatus"]]), 3),
    }


def figure(res: dict) -> None:
    from plotstyle import BLUE, NEUTRAL, ORANGE, plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    for ax, (name, r) in zip(axes, res.items(), strict=True):
        t = [row["threshold"] for row in r["by_threshold"]]
        for key, col, lab in (("precision", BLUE, "Precision"), ("recall", ORANGE, "Recall")):
            v = np.array([row[key][:3] for row in r["by_threshold"]], dtype=float)
            ax.fill_between(t, v[:, 1], v[:, 2], color=col, alpha=0.12, lw=0)
            ax.plot(t, v[:, 0], marker="o", ms=5, color=col, label=lab)
        ax.axvline(0.6, color=NEUTRAL, ls=":", lw=1)
        ax.text(0.61, 0.97, "product default 0.60", fontsize=8, color=NEUTRAL, va="top")
        pos = " + ".join(r["positives"])
        ax.set_title(f"Any BirdNET {name} label fires (positives: ESC-50 {pos})", fontsize=10)
        ax.set_xlabel("BirdNET confidence threshold")
        ax.set_ylim(0, 1.02)
    axes[0].set_ylabel("Clip-level rate (95% Wilson CI)")
    axes[0].legend(loc="center right")
    fig.suptitle(
        "BirdNET v2.4 zero-shot, taxon level, ESC-50 (2000 clips)",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    fig.tight_layout()
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG)
    plt.close(fig)


def fmt_w(w: list) -> str:
    return f"{w[0]:.2f} ({w[1]:.2f} to {w[2]:.2f}; {w[3]}/{w[4]})"


def write_report(res: dict, meta: dict) -> None:
    L: list[str] = []
    a = L.append
    a("# BirdNET v2.4 non-bird labels: coarse benchmark on ESC-50")
    a("")
    a(
        f"Generated by `ml/train/birdnet_nonbird_benchmark.py` on {meta['date']}. Raw numbers: `ml/reports/birdnet_nonbird_results.json`."
    )
    a("")
    a("## What this measures and what it does not")
    a("")
    a(
        "* BirdNET v2.4 has 41 amphibian and 42 insect labels, mostly North American species (plus, for example, the honey bee)."
    )
    a(
        "* ESC-50 has a `frog` class (40 clips), an `insects` class (40 clips; the ESC-50 README calls it 'Insects (flying)') and a `crickets` class (40 clips). They are not species labeled and we do not know where they were recorded, so many are probably not North American species."
    )
    a(
        "* So this is a **taxon-level** check: does any amphibian (or insect) label fire on a frog (or insect) clip, and how often do those labels fire on the other 1,960 (or 1,920) clips? It says nothing about species-level accuracy."
    )
    a(
        "* Clip score = highest probability over all labels of the taxon and over the three 3 s windows (1 s hop) of each 5 s clip. The product uses a 3 s hop, which gives fewer chances to fire, so recall here is an upper bound for the product setting. We also report recall with the first window only."
    )
    a(
        f"* BirdNET model sha256 `{meta['birdnet_sha256']}`; ESC-50 commit `{meta['esc50_commit']}`. 95% CIs: Wilson intervals for rates; cluster bootstrap over source recordings ({meta['n_boot']} resamples) for AP and ROC AUC."
    )
    a("")
    for name, r in res["tasks"].items():
        a(f"## {name.capitalize()} labels")
        a("")
        a(
            f"Positives: ESC-50 {', '.join(r['positives'])} ({r['n_pos']} clips). Negatives: all other classes ({r['n_neg']} clips). BirdNET labels in this taxon: {r['n_birdnet_labels']}."
        )
        a("")
        a(f"* Average precision {ek.fmt_ci(r['ap'])}; ROC AUC {ek.fmt_ci(r['auc'])}.")
        a(
            f"* Median clip score: {r['median_score_positives']:.3f} on positives, {r['median_score_negatives']:.4f} on negatives."
        )
        a("")
        multi = len(r["positives"]) > 1
        pos_cols = r["positives"] if multi else []
        cols = (
            "| Threshold | Precision | Recall | "
            + "".join(f"Recall on {c} | " for c in pos_cols)
            + "Recall, first window only | False positive rate | Most common false positive classes |"
        )
        a(cols)
        a("|" + "---|" * (6 + len(pos_cols)))
        for row in r["by_threshold"]:
            prec = fmt_w(row["precision"]) if row["tp"] + row["fp"] else "n/a (nothing fired)"
            byc = "".join(fmt_w(row["recall_by_class"][c]) + " | " for c in pos_cols)
            fps = ", ".join(f"{c} ({n})" for c, n in row["top_false_positive_classes"]) or "none"
            a(
                f"| {row['threshold']:.1f} | {prec} | {fmt_w(row['recall'])} | {byc}{fmt_w(row['recall_first_window_only'])} | {fmt_w(row['false_positive_rate'])} | {fps} |"
            )
        a("")
        a(
            "Labels that fire most often on the positives (highest label per clip, score >= 0.1): "
            + (
                ", ".join(f"`{lab}` ({n})" for lab, n in r["top_labels_on_positives_at_0.1"])
                or "none"
            )
            + "."
        )
        a("")
        a(
            "BirdNET's single top label per positive clip, by taxon: "
            + "; ".join(
                f"{c}: "
                + ", ".join(f"{t} {n}" for t, n in sorted(d.items(), key=lambda kv: -kv[1]))
                for c, d in r["top1_taxon_on_positives"].items()
            )
            + "."
        )
        a("")
    a("![Precision and recall vs threshold](figures/birdnet_nonbird_pr.png)")
    a("")
    sm = res.get("smoke")
    if sm:
        a("## Smoke check on one North American toad recording")
        a("")
        a(
            f"`great_plains_toad.wav` from the OpenSoundscape test suite (MIT-licensed repository; recordist unknown), {sm['duration_s']} s, {sm['n_windows']} windows. This is one file: an anecdote, not evidence."
        )
        a("")
        a(
            f"* Great Plains Toad (*Anaxyrus cognatus*) max probability: {sm['great_plains_toad_prob']:.3f}; highest amphibian label: {sm['max_amphibian']:.3f}."
        )
        a(
            "* Top 5 labels (max over windows): "
            + "; ".join(f"`{lab}` {p:.3f} ({t})" for lab, p, t in sm["top5"])
            + "."
        )
        a("")
    a("## Reading the results")
    a("")
    for line in res["summary"]:
        a(f"* {line}")
    a("")
    a("## Limits")
    a("")
    a(
        "* ESC-50 clips are short, curated Freesound clips, often recorded close to the source. Field recordings are harder."
    )
    a(
        "* A taxon-level hit does not mean the species is right. A species-level benchmark needs species-labeled North American recordings from many recordists; see `ml/reports/data_sources.md` for why we could not run one here and `ml/train/frog_insect.py` for the pipeline that will run on the iNaturalist feature dataset."
    )
    a(
        "* BirdNET may have been trained on some of the same Freesound or xeno-canto source recordings that ESC-50 uses. We cannot check this, so these numbers may be optimistic."
    )
    a("")
    REPORT.write_text("\n".join(L))


def summarize(res: dict) -> list[str]:
    out = []
    for name, r in res.items():
        rows = {row["threshold"]: row for row in r["by_threshold"]}
        r6 = rows[0.6]
        per = "; ".join(
            f"{c} {r6['recall_by_class'][c][3]}/{r6['recall_by_class'][c][4]}"
            for c in r["positives"]
        )
        top1 = r["top1_taxon_on_positives"]
        birdish = sum(d.get("bird", 0) for d in top1.values())
        n_pos = sum(sum(d.values()) for d in top1.values())
        out.append(
            f"{name.capitalize()}, at the product default 0.60: recall {r6['recall'][0]:.2f} ({per}), "
            + (f"precision {r6['precision'][0]:.2f}, " if r6["tp"] + r6["fp"] else "")
            + f"{r6['fp']} false positives among {r['n_neg']} other clips. BirdNET's single top label is a bird label on {birdish} of {n_pos} positive clips."
        )
        r5, r1 = rows[0.5], rows[0.1]
        out.append(
            f"{name.capitalize()}: at 0.5, recall {r5['recall'][0]:.2f} with precision "
            + (f"{r5['precision'][0]:.2f}" if r5["tp"] + r5["fp"] else "n/a")
            + f"; at 0.1, recall {r1['recall'][0]:.2f} with precision "
            + (f"{r1['precision'][0]:.2f}" if r1["tp"] + r1["fp"] else "n/a")
            + f" and {r1['fp']} false positives among {r['n_neg']} negatives."
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--data", default="/home/claude/data/esc50")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--smoke", action="store_true", help="also run the single toad file")
    args = ap.parse_args()
    F = q.load_features(Path(args.data))
    tasks = evaluate(F, args.n_boot)
    res = {"tasks": tasks, "summary": summarize(tasks)}
    if args.smoke:
        res["smoke"] = smoke(Path(args.data))
    meta = {
        "date": date.today().isoformat(),
        "birdnet_sha256": str(F["birdnet_sha256"]),
        "esc50_commit": str(F["esc50_commit"]),
        "n_boot": args.n_boot,
        "hop_seconds": float(F["hop_seconds"]),
        "thresholds": THRESHOLDS,
    }
    RESULTS.write_text(json.dumps({"meta": meta, **res}, indent=1, default=q._json_default))
    figure(tasks)
    write_report(res, meta)
    for line in res["summary"]:
        print(line)


if __name__ == "__main__":
    main()
