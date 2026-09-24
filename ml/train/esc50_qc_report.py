"""Write the QC head report and model card from ``qc_esc50_v1_results.json``.

Called by ``python ml/train/esc50_qc.py report``. Every number printed here is
read from the results file; nothing is typed in by hand.
"""

from __future__ import annotations

import json

import evalkit as ek
from esc50_qc import (
    CATEGORIES,
    CATEGORY_KIND,
    CATEGORY_MAP,
    CONTAMINATION,
    OTHER_CLASSES,
    REPO,
)

REPORT = REPO / "ml" / "reports" / "qc_esc50_v1.md"
CARD = REPO / "docs" / "model-cards" / "qc-soundscape-v1.md"
PUBLISHED = [
    ("Human listeners (crowdsourced)", "81.30%", "piczak2015a"),
    ("MFCC + ZCR, random forest baseline", "44.30%", "piczak2015a"),
    ("CNN baseline on mel spectrograms", "64.50%", "piczak2015b"),
    ("CNN pretrained on AudioSet", "83.50%", "kumar2017"),
    ("AST, transformer pretrained on AudioSet", "95.70%", "gong2021"),
    ("BEATs, transformer with acoustic tokenizers", "98.10%", "chen2022"),
]
RATIONALE = [
    "`crackling_fire` is a negative, not its own category. Fire is rare in passive monitoring, one 40-clip class would only teach a campfire detector, and its crackle can resemble rain on hard surfaces, so it is more useful as a hard negative for `rain`.",
    "`water` includes `toilet_flush` and `pouring_water` next to `sea_waves` and `water_drops`: they are indoor recordings, but acoustically they are running or dripping water, which is what streams, culverts and drips sound like in the field.",
    "`engine_machinery` covers motors and vehicles (`engine`, `train`, `airplane`, `helicopter`), powered and hand tools (`chainsaw`, `hand_saw`), motor appliances as stand-ins for pumps and generators (`vacuum_cleaner`, `washing_machine`), and traffic signals (`siren`, `car_horn`). `church_bells` and `fireworks` are human-made but not machinery; they stay negatives.",
    "`human_nonspeech` is exactly ESC-50's 'human, non-speech sounds' group (crying baby, sneezing, clapping, breathing, coughing, footsteps, laughing, brushing teeth, snoring, drinking). ESC-50 has no speech; speech is handled in the backend by BirdNET's `Human vocal` label.",
    "`hen` and `rooster` are birds, but they count as `domestic_animal` because in the product `bird` means wild bird sound. This penalizes the BirdNET baseline for `bird`, whose bird labels also respond to chickens (numbers below).",
    "Indoor object sounds (door knock, door creaks, mouse click, keyboard typing, can opening, clock alarm, clock tick, glass breaking) are negatives: they are not expected in field audio and there is no QC action for them.",
]


def f3(x: float) -> str:
    return f"{x:.3f}"


def ci(t) -> str:
    return ek.fmt_ci(t)


def wil(w) -> str:
    return f"{100 * w[0]:.0f}% ({100 * w[1]:.0f} to {100 * w[2]:.0f}%; {w[3]}/{w[4]})"


def pct(w) -> str:
    return f"{100 * w[0]:.0f}%"


def snr(x: float) -> str:
    return "0" if x == 0 else f"{x:+.0f}"


def summary_lines(res: dict) -> list[str]:
    A, B = res.get("experiment_a"), res["experiment_b"]
    H = B["head_at_f1_thresholds"]
    base = B["birdnet_baseline"]
    out = []
    if A:
        out.append(
            f"Reference probe (Experiment A): a linear classifier on frozen BirdNET embeddings reaches {100 * A['accuracy_mean']:.1f}% accuracy on the 50 ESC-50 classes (standard deviation {100 * A['accuracy_std']:.1f} points over the 5 official folds)."
        )
    out.append(
        f"QC head (Experiment B), pooled over the 5 test folds: macro average precision {ci(H['macro']['ap'])}, macro F1 {ci(H['macro']['f1'])}, micro F1 {ci(H['micro']['f1'])} at thresholds chosen on training folds."
    )
    better = [c for c, d in B["ap_difference_head_minus_baseline"].items() if d[1] > 0]
    worse = [c for c, d in B["ap_difference_head_minus_baseline"].items() if d[2] < 0]
    out.append(
        f"Against BirdNET's own labels used zero-shot, the trained head has higher average precision in {len(better)} of 10 categories (95% CI of the difference above zero: {', '.join(better) or 'none'})"
        + (
            f"; lower in {', '.join(worse)}."
            if worse
            else "; it is not clearly worse in any category."
        )
        + f" Macro AP: head {f3(H['macro']['ap'][0])} vs BirdNET labels {f3(base['macro']['ap'][0])}."
    )
    out.append(
        f"Calibration: expected calibration error {f3(B['reliability_raw']['ece'])} before and {f3(B['reliability_calibrated']['ece'])} after Platt scaling fitted on training folds."
    )
    pc = B["pooling_check"]["backgrounds"]["biophony"]["rules"]["backend"]
    dr, ff = pc["detection_rate"], pc["false_flag_rate"]
    out.append(
        "Long recordings (synthetic, from test-fold clips; backend warning rule): scoring 6 s segments and requiring a category in at least a quarter of them (the exported default) catches contamination covering half or all of a 30 s recording "
        f"{100 * dr['3']['mean_over_categories']['segment_top25']:.0f}% and {100 * dr['6']['mean_over_categories']['segment_top25']:.0f}% of the time, with false warnings on {100 * ff['6']['segment_top25']['any_contamination']:.0f}% (30 s) and {100 * ff['12']['segment_top25']['any_contamination']:.0f}% (60 s) of clean bird, insect and frog recordings. "
        f"It misses short bursts (1 of 6 clips: {100 * dr['1']['mean_over_categories']['segment_top25']:.0f}%). A plain max over segments would catch {100 * dr['1']['mean_over_categories']['segment_max']:.0f}% of bursts but falsely warn on {100 * ff['6']['segment_max']['any_contamination']:.0f}% (30 s) and {100 * ff['12']['segment_max']['any_contamination']:.0f}% (60 s) of clean recordings."
    )
    N = res.get("noise_robustness")
    if N:
        m = N["mixed"]
        parts = []
        for c in ("rain", "wind", "engine"):
            parts.append(
                f"{c} {pct(m[f'{c}@+10dB']['contaminant_flag_rate'])} / {pct(m[f'{c}@+0dB']['contaminant_flag_rate'])} / {pct(m[f'{c}@-10dB']['contaminant_flag_rate'])}"
            )
        out.append(
            f"Noise stress test ({N['n_target_clips']} held-out bird, frog and insect clips): the head flags the added contaminant at +10 / 0 / -10 dB SNR in {'; '.join(parts)} of mixtures."
        )
    out.append(
        "These are ESC-50 numbers: short, curated, mostly close-range clips with one label each. They are not field accuracy. The head is a QC aid, not a validated detector."
    )
    return out


def mapping_table() -> list[str]:
    L = ["| Category | Kind | ESC-50 classes | Clips |", "|---|---|---|---|"]
    for c in CATEGORIES:
        L.append(
            f"| `{c}` | {CATEGORY_KIND[c]} | {', '.join(CATEGORY_MAP[c])} | {40 * len(CATEGORY_MAP[c])} |"
        )
    L.append(
        f"| negatives (all zeros) | n/a | {', '.join(OTHER_CLASSES)} | {40 * len(OTHER_CLASSES)} |"
    )
    return L


def head_table(tab: dict) -> list[str]:
    L = [
        "| Category | Positives | Flagged | Precision | Recall | F1 | Average precision | ROC AUC |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in CATEGORIES:
        r = tab["per_class"][c]
        L.append(
            f"| `{c}` | {r['n_pos']} | {r['n_flagged']} | {ci(r['precision'])} | {ci(r['recall'])} | {ci(r['f1'])} | {ci(r['ap'])} | {ci(r['auc'])} |"
        )
    for agg in ("macro", "micro"):
        r = tab[agg]
        L.append(
            f"| **{agg}** | | | {ci(r['precision'])} | {ci(r['recall'])} | {ci(r['f1'])} | {ci(r['ap'])} | {ci(r['auc']) if 'auc' in r else 'n/a'} |"
        )
    return L


def baseline_table(B: dict, meta: dict) -> list[str]:
    base = B["birdnet_baseline"]["per_class"]
    head = B["head_at_f1_thresholds"]["per_class"]
    L = [
        "| Category | BirdNET score used | BirdNET AP | Head AP | AP difference (head minus BirdNET) | BirdNET F1 | Head F1 |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in CATEGORIES:
        src = (
            f"max over all {meta['baseline_taxa'][c]} labels"
            if c in meta["baseline_taxa"]
            else " or ".join(f"`{x.split('_')[0]}`" for x in meta["baseline_labels"][c])
        )
        L.append(
            f"| `{c}` | {src} | {ci(base[c]['ap'])} | {ci(head[c]['ap'])} | {ci(B['ap_difference_head_minus_baseline'][c])} | {ci(base[c]['f1'])} | {ci(head[c]['f1'])} |"
        )
    r = B["birdnet_baseline"]["macro"]
    L.append(
        f"| **macro** | | {ci(r['ap'])} | {ci(B['head_at_f1_thresholds']['macro']['ap'])} | | {ci(r['f1'])} | {ci(B['head_at_f1_thresholds']['macro']['f1'])} |"
    )
    return L


def write_report(res: dict) -> None:
    meta, A, B = res["meta"], res.get("experiment_a"), res["experiment_b"]
    H = B["head_at_f1_thresholds"]
    L: list[str] = []
    a = L.append
    a("# Soundscape QC head v1 on ESC-50: evaluation report")
    a("")
    a(
        f"Generated on {meta['date']} by `ml/train/esc50_qc.py` (report text by `ml/train/esc50_qc_report.py`). Every number comes from `ml/reports/qc_esc50_v1_results.json`, which also stores the settings used. Model card: `docs/model-cards/qc-soundscape-v1.md`."
    )
    a("")
    a("## Summary")
    a("")
    for s in summary_lines(res):
        a(f"* {s}")
    a("")
    a("## Setup")
    a("")
    a(
        f"* **Data.** ESC-50 (commit `{meta['esc50_commit'][:12]}`), {meta['n_clips']} clips of 5 s, 50 classes x 40, from {meta['n_source_recordings']} Freesound source recordings. License CC BY-NC 3.0. We use the 5 official folds, which keep clips cut from the same source recording in one fold."
    )
    a(
        f"* **Features.** Audio decoded with `thicket.services.audio_io.decode` to 48 kHz mono, cut by `frame_windows` into 3 s windows with a {meta['hop_seconds']:.0f} s hop ({meta['n_windows']} windows, 3 per clip), and run through `BirdNETRuntime` (BirdNET GLOBAL 6K v2.4 FP32, sha256 `{meta['birdnet_sha256'][:16]}...`). A clip feature is the mean and the max of its window embeddings (2 x 1024 = 2048 values)."
    )
    a(
        "* **Model.** Standardization, then one logistic regression per category (multi-label, L2 penalty, full-batch L-BFGS). Nothing else is learned."
    )
    a(
        f"* **Protocol.** Train on 4 folds, test on the fifth, rotate. Inside the 4 training folds, a leave-one-fold-out loop picks the regularization strength C (grid {B['grid']}) by macro average precision, then fits Platt scaling and the per-category decision thresholds on the out-of-fold training predictions. The test fold is used once. Test predictions from the 5 folds are pooled (each clip is tested exactly once)."
    )
    a(
        f"* **Uncertainty.** 95% intervals are percentile intervals from a cluster bootstrap over source recordings ({meta['n_boot']} resamples), so takes from the same Freesound recording move together. Rates in the stress tests use Wilson intervals."
    )
    a(
        "* **Possible overlap.** BirdNET is not documented as trained on ESC-50, but its training data (mainly xeno-canto and the Macaulay Library, plus other collections for its non-bird and noise classes) may share source recordings with ESC-50, which was cut from Freesound recordings. We could not check this, so all numbers may be somewhat optimistic, most of all the BirdNET-label baseline for sources BirdNET has labels for (dog, engine, siren, human)."
    )
    a("")
    a("## Category mapping")
    a("")
    L.extend(mapping_table())
    a("")
    a("Decisions:")
    a("")
    for r in RATIONALE:
        a(f"* {r}")
    a("")
    if A:
        a("## Experiment A: 50-class linear probe (reference)")
        a("")
        a(
            f"Softmax regression on the same 2048-d clip features, C chosen on inner folds (grid {A['grid']})."
        )
        a("")
        a("| Test fold | Accuracy | C chosen on training folds |")
        a("|---|---|---|")
        for k, v in A["folds"].items():
            a(f"| {k} | {100 * v['accuracy']:.2f}% | {v['C']} |")
        a(
            f"| **mean (std over folds)** | **{100 * A['accuracy_mean']:.2f}% ({100 * A['accuracy_std']:.2f})** | |"
        )
        a("")
        a(
            "Published ESC-50 accuracies for context, as listed in the ESC-50 repository README (5-fold CV; most are fully trained or fine-tuned networks, not linear probes on frozen features, so this is a rough comparison):"
        )
        a("")
        a("| Method | Accuracy | Source |")
        a("|---|---|---|")
        for m_, acc, src in PUBLISHED:
            a(f"| {m_} | {acc} | {src} |")
        a(
            f"| BirdNET v2.4 embeddings + linear probe (this work) | {100 * A['accuracy_mean']:.2f}% | this report |"
        )
        a("")
        pca = sorted(A["per_class_accuracy"].items(), key=lambda kv: kv[1])
        a(
            "Hardest classes: "
            + ", ".join(f"{c} {100 * v:.0f}%" for c, v in pca[:6])
            + ". Easiest: "
            + ", ".join(f"{c} {100 * v:.0f}%" for c, v in pca[-6:])
            + "."
        )
        a("")
        conf = sorted(A["most_common_confusion"].items(), key=lambda kv: -kv[1][1])[:6]
        a(
            "Most frequent confusions (true -> predicted, clips): "
            + "; ".join(f"{t} -> {p} ({n})" for t, (p, n) in conf)
            + "."
        )
        a("")
    a("## Experiment B: Thicket QC categories")
    a("")
    a("### Head at F1-optimal thresholds (chosen on training folds)")
    a("")
    L.extend(head_table(H))
    a("")
    fm = B["per_fold_macro_ap"]
    a(
        f"Macro AP per test fold: mean {f3(fm['mean'])}, standard deviation {f3(fm['std'])} ("
        + ", ".join(f"fold {k}: {f3(v['test_macro_ap'])}" for k, v in B["folds"].items())
        + "). C chosen per fold: "
        + ", ".join(f"{k}: {v['C']}" for k, v in B["folds"].items())
        + "."
    )
    a("")
    a("![Average precision per category](figures/qc_ap_by_category.png)")
    a("")
    a("![Precision-recall curves](figures/qc_pr_curves.png)")
    a("")
    a("### High-precision operating point")
    a("")
    a(
        "Thresholds chosen on training folds as the lowest score with precision >= 0.90 (out-of-fold). Test results:"
    )
    a("")
    P = B["head_at_p90_thresholds"]
    a("| Category | Precision | Recall | F1 |")
    a("|---|---|---|---|")
    for c in CATEGORIES:
        r = P["per_class"][c]
        a(f"| `{c}` | {ci(r['precision'])} | {ci(r['recall'])} | {ci(r['f1'])} |")
    a(
        f"| **macro** | {ci(P['macro']['precision'])} | {ci(P['macro']['recall'])} | {ci(P['macro']['f1'])} |"
    )
    a("")
    a("### Compared with BirdNET's own labels (zero-shot)")
    a("")
    a(
        "BirdNET has labels for some of these sources. Its clip score is the max over windows of the label probability. Its decision threshold was chosen on the training folds with the same F1 rule. BirdNET has no rain, wind, thunder or water label; for those four rows we show its generic `Environmental` label, which is the closest thing it has."
    )
    a("")
    L.extend(baseline_table(B, meta))
    a("")
    hr = B["birdnet_bird_label_on_hen_rooster"]
    a(
        f"On the 80 hen and rooster clips (our `domestic_animal`), BirdNET's highest bird label reaches 0.5 on {wil(hr['at_0.5'])} and 0.1 on {wil(hr['at_0.1'])}; these count as false positives for the BirdNET `bird` baseline under our mapping."
    )
    a("")
    a("### Single-label view")
    a("")
    a(
        f"Each clip gets the category with the highest calibrated score among those above their threshold, or `other` when none is. Accuracy of this view: {100 * B['single_label_accuracy']:.1f}% (11 labels including `other`)."
    )
    a("")
    a("![Confusion matrix](figures/qc_confusion.png)")
    a("")
    ff = sorted(
        ((c, v) for c, v in B["false_flags_by_esc_class"].items()),
        key=lambda kv: -kv[1]["clips_with_foreign_flag"],
    )[:8]
    a(
        "ESC-50 classes that most often raise a flag for a category they do not belong to (out of 40 clips each): "
        + "; ".join(
            f"{c} {v['clips_with_foreign_flag']} ("
            + ", ".join(f"{k} {n}" for k, n in v["top"])
            + ")"
            for c, v in ff
        )
        + f". Clips from the 11 negative classes raise at least one flag {100 * B['other_classes_any_flag_rate']:.1f}% of the time."
    )
    a("")
    a("### Calibration")
    a("")
    a(
        f"Expected calibration error over all 20,000 category-clip pairs, 10 equal-width bins: {f3(B['reliability_raw']['ece'])} for the raw logistic outputs and {f3(B['reliability_calibrated']['ece'])} after Platt scaling. Most pairs are easy negatives near 0, which makes this ECE look small; the per-category values below are more telling."
    )
    a("")
    a("| Category | ECE raw | ECE after Platt |")
    a("|---|---|---|")
    for c in CATEGORIES:
        e = B["ece_per_category"][c]
        a(f"| `{c}` | {f3(e['raw'])} | {f3(e['calibrated'])} |")
    a("")
    a("![Reliability diagram](figures/qc_reliability.png)")
    a("")
    a("### Fewer windows")
    a("")
    S1 = B["head_single_window"]
    a(
        f"The head was trained on 3 overlapping windows per clip. Scoring only the first 3 s window of each test clip (mean = max = that window): macro AP {ci(S1['macro']['ap'])} and macro F1 {ci(S1['macro']['f1'])}, vs {ci(H['macro']['ap'])} and {ci(H['macro']['f1'])} with all 3 windows."
    )
    a("")
    a("## Long recordings: pooling check")
    a("")
    pc = B["pooling_check"]
    bio = pc["backgrounds"]["biophony"]
    a(
        f"Field recordings are longer than 5 s, so the head must turn many window embeddings into one recording score. We built synthetic recordings from test-fold window embeddings (no new audio): each clip contributes 2 windows (at 0 s and 2 s, close to the product's 3 s hop). A contaminated recording has 6 clips (about 30 s) of which 1, 3 or all 6 come from one contamination category; the rest are background clips. Clean recordings have 6 or 12 background clips (about 30 s or 60 s). {pc['n_per_category_per_fold']} contaminated recordings per category, coverage and fold ({bio['n_contaminated_per_category_and_coverage']} per cell) and {bio['n_clean_per_length']} clean recordings per length. Every clip is scored by the fold model that did not train on it. The windows come from separate clips, not one continuous recording, so this is an approximation."
    )
    a("")
    a(
        "Pooling modes: `whole` pools all windows into one feature; the others score 2-window segments (about 6 s) and take, per category, the k-th highest segment probability: `segment_max` k = 1; `segment_top25` k = ceil(0.25 x segments); `segment_top50` k = ceil(0.5 x segments)."
    )
    a("")
    for bname, btitle in (
        ("biophony", "bird, insect and frog clips only"),
        ("mixed", "bird, insect, frog and ESC-50 negative classes"),
    ):
        rr = pc["backgrounds"][bname]["rules"]["backend"]
        a(
            f"Background: {btitle}. Decision rule: the backend's (p > max(0.5, threshold)). Detection = share of contaminated recordings flagged with the right category (mean over the 7 contamination categories); false warning = share of clean recordings with any contamination flag."
        )
        a("")
        a(
            "| Pooling | Detected, 1 of 6 clips | Detected, 3 of 6 | Detected, 6 of 6 | False warning, 30 s | False warning, 60 s |"
        )
        a("|---|---|---|---|---|---|")
        for md in pc["modes"]:
            d = rr["detection_rate"]
            f = rr["false_flag_rate"]
            a(
                f"| `{md}` | {100 * d['1']['mean_over_categories'][md]:.0f}% | {100 * d['3']['mean_over_categories'][md]:.0f}% | {100 * d['6']['mean_over_categories'][md]:.0f}% | {100 * f['6'][md]['any_contamination']:.0f}% | {100 * f['12'][md]['any_contamination']:.0f}% |"
            )
        a("")
    rr = bio["rules"]["backend"]
    a(
        "Per category with the exported default (`segment_top25`, biophony background, backend rule):"
    )
    a("")
    a("| Category | Detected, 3 of 6 clips | Detected, 6 of 6 | False flag, 60 s clean |")
    a("|---|---|---|---|")
    for c in CONTAMINATION:
        a(
            f"| `{c}` | {100 * rr['detection_rate']['3'][c]['segment_top25']:.0f}% | {100 * rr['detection_rate']['6'][c]['segment_top25']:.0f}% | {100 * rr['false_flag_rate']['12']['segment_top25'][c]:.1f}% |"
        )
    a("")
    cb = B["clean_biophony_clip_false_contamination_flag"]
    a(
        f"Why a plain max fails: a single clean bird, insect or frog clip already raises at least one contamination flag in {wil(cb['backend'])} of cases under the backend rule (flags by category: "
        + ", ".join(
            f"`{c}` {n}"
            for c, n in sorted(
                B["clean_biophony_clip_flags_by_category_backend"].items(), key=lambda kv: -kv[1]
            )
            if n
        )
        + "), so taking the max over many segments makes a false warning almost certain on long recordings. Pooling everything (`whole`) dilutes short contamination and also drifts on long recordings."
    )
    a("")
    exp = res.get("export", {})
    a(
        f"Decision: the exported head uses `{exp.get('recording_pooling', 'segment_quantile')}` with q = {exp.get('segment_quantile', 0.25)} and {exp.get('segment_windows', 2)}-window segments (the `segment_top25` rows). We chose it after seeing this table, which uses test-fold data, so it is a design choice, not a tuned and held-out result. It reports persistent contamination; short events (a passing car, one bark) are not flagged at the recording level but can be found with `QCHead.predict_segments`. Other decision rules and backgrounds are in the results JSON."
    )
    a("")
    hb = B["head_at_backend_rule"]
    a(
        f"Clip-level metrics under the backend rule (p > max(0.5, threshold)): macro precision {ci(hb['macro']['precision'])}, recall {ci(hb['macro']['recall'])}, F1 {ci(hb['macro']['f1'])}."
    )
    a("")
    N = res.get("noise_robustness")
    if N:
        a("## Noise stress test")
        a("")
        cfg = N["config"]
        a(
            f"Held-out ESC-50 clips of chirping birds, crows, frogs, flying insects and crickets ({N['n_target_clips']} clips from {len(cfg['folds'])} test folds) were mixed with a random rain, wind or engine clip from the same test fold at {', '.join(snr(s) for s in cfg['snr_db'])} dB signal-to-noise ratio, then re-embedded with BirdNET ({N['n_mixtures']} mixtures). The ratio compares the RMS level of the target and the contaminant over their non-silent 50 ms frames (ESC-50 pads some clips with digital silence); a negative value means the contaminant is louder. Each clip is scored by the fold model that never saw that fold. BirdNET's score is the max over windows of its bird, amphibian or insect labels, matching the clip's taxon; the product threshold is {cfg['birdnet_threshold']}."
        )
        a("")
        cl = N["clean"]
        a(
            f"Clean clips: the head flags the right taxon (bird, frog or insect) on {wil(cl['target_flag_rate'])} of clips; BirdNET's matching-taxon label reaches {cfg['birdnet_threshold']} on {wil(_pool(cl['birdnet_rate_at_threshold']))}. False contamination flags on clean clips: "
            + ", ".join(
                f"{c} {100 * cl['false_flag_rate'][c][0]:.0f}%"
                for c in ("rain", "wind", "engine_machinery")
            )
            + "."
        )
        a("")
        a(
            "| Contaminant | SNR | Head flags contaminant | Head flags any contamination | Head still flags taxon | BirdNET >= threshold (bird) | (frog) | (insect) |"
        )
        a("|---|---|---|---|---|---|---|---|")
        for v in N["mixed"].values():
            br = v["birdnet_rate_at_threshold"]
            a(
                f"| {v['contaminant']} | {snr(v['snr_db'])} dB | {wil(v['contaminant_flag_rate'])} | {wil(v['any_contamination_flag_rate'])} | {wil(v['target_flag_rate'])} | {pct(br['bird'])} | {pct(br['frog'])} | {pct(br['insect'])} |"
            )
        a("")
        a(
            "Median BirdNET taxon score (clean, then +10 / 0 / -10 dB): "
            + "; ".join(
                f"{t}: {cl['birdnet_median'][t]:.2f}, "
                + ", ".join(
                    " / ".join(
                        f"{N['mixed'][f'{c}@{s:+.0f}dB']['birdnet_median'][t]:.2f}"
                        for s in cfg["snr_db"]
                    )
                    + f" ({c})"
                    for c in ("rain", "wind", "engine")
                )
                for t in ("bird", "frog", "insect")
            )
            + "."
        )
        a("")
        a("![Noise stress test](figures/qc_noise_robustness.png)")
        a("")
    sm = res.get("fixture_smoke")
    if sm:
        a("## One real field soundscape (anecdote)")
        a("")
        a(
            f"`{sm['file']}` is the first 30 s of the BirdNET-Analyzer example soundscape, a dawn chorus ({sm['n_windows']} windows at the product's 3 s hop). BirdNET's top labels: "
            + ", ".join(f"{n} {p:.2f}" for n, p in sm["birdnet_top5"])
            + ". Scores of the exported head:"
        )
        a("")
        a("| Pooling | bird | insect | frog | highest contamination category |")
        a("|---|---|---|---|---|")
        for mode, pr in sm["probabilities"].items():
            worst = max(CONTAMINATION, key=lambda c, pr=pr: pr[c])
            a(
                f"| `{mode}` | {pr['bird']:.3f} | {pr['insect']:.3f} | {pr['frog']:.3f} | {worst} {pr[worst]:.3f} |"
            )
        a("")
        a(
            f"Backend warnings raised: {', '.join(sm['backend_warnings']) or 'none'}. The head raises no contamination warning here, which is right. But its `bird` score is low with the default pooling (bird threshold {exp.get('thresholds_f1', {}).get('bird', float('nan')):.3f}), even though BirdNET finds several species. One file proves nothing on its own, but it fits the other evidence: ESC-50's close 'chirping birds' clips do not look like a distant chorus. The `bird`, `insect` and `frog` scores should not be shown to users as presence hints until they are checked on field recordings."
        )
        a("")
    if exp:
        a("## Exported model")
        a("")
        a(
            f"`{exp['artifact']}` ({exp['artifact_bytes']} bytes, sha256 `{exp['artifact_sha256'][:16]}...`), trained on all 2,000 clips. C = {exp['C']} (5-fold CV macro AP by C: "
            + ", ".join(f"{k}: {v:.3f}" for k, v in exp["cv_macro_ap_by_C"].items())
            + "). Platt parameters and thresholds come from that CV's out-of-fold predictions. The backend loader reproduces the training-side probabilities to within "
            + f"{exp['backend_parity_max_abs_diff']:.1e}."
        )
        a("")
        a("| Category | Threshold (F1) | Threshold (precision >= 0.9) |")
        a("|---|---|---|")
        for c in CATEGORIES:
            a(f"| `{c}` | {exp['thresholds_f1'][c]:.3f} | {exp['thresholds_p90'][c]:.3f} |")
        a("")
        a(
            f"The out-of-fold macro AP of this final CV ({exp['oof_macro_ap_all_folds']:.3f}) is optimistic because C was picked on it; use the Experiment B numbers above as the estimate."
        )
        a("")
    a("## Limitations")
    a("")
    for s in limits(res):
        a(f"* {s}")
    a("")
    a("## Reproduce")
    a("")
    a("```")
    a("python ml/train/esc50_qc.py all --data /home/claude/data/esc50")
    a("```")
    a("")
    a(
        f"Software: Python {meta['python']}, NumPy {meta['numpy']}, SciPy {meta['scipy']}, scikit-learn {meta['sklearn']} (training only). Seed {meta['seed']}."
    )
    a("")
    REPORT.write_text("\n".join(L))


def limits(res: dict) -> list[str]:
    out = list(LIMITS)
    N = res.get("noise_robustness")
    if N:
        m = N["mixed"]
        out.insert(
            2,
            "Contamination mixed with a target sound is often missed. In the noise stress test, with the contaminant 10 dB louder than the bird, frog or insect, the head flagged wind in "
            f"{pct(m['wind@-10dB']['contaminant_flag_rate'])}, rain in {pct(m['rain@-10dB']['contaminant_flag_rate'])} and engine sound in {pct(m['engine@-10dB']['contaminant_flag_rate'])} of mixtures; at equal level (0 dB) in {pct(m['wind@+0dB']['contaminant_flag_rate'])}, {pct(m['rain@+0dB']['contaminant_flag_rate'])} and {pct(m['engine@+0dB']['contaminant_flag_rate'])}. Training never saw mixtures; training on mixed clips is the obvious next step.",
        )
    return out


LIMITS = [
    "ESC-50 is a set of curated Freesound clips, mostly recorded close to the source, with one label per clip. Passive field recordings have distant, overlapping and quiet sources, recorder self-noise and long durations. Expect lower accuracy in the field; no field validation has been done.",
    "Co-occurring sources never appear in training (each clip has one class), so a clip with both rain and birds is out of distribution. The noise stress test is a first look at that case, with only three contaminants.",
    "Each category is learned from few source recordings (40 clips for rain, wind, thunder and frog). Rain on a tent and rain on leaves, or a distant highway, may not look like the ESC-50 examples.",
    "`bird`, `insect` and `frog` are coarse scores learned from 2, 2 and 1 ESC-50 classes. They are not species detectors and must not be reported as detections. On one real dawn-chorus recording the `bird` score stayed low, so do not show these three to users until they are validated on field audio.",
    "Probabilities are calibrated on ESC-50 5 s clips. A recording score is an order statistic over 6 s segments, not a single-clip probability, and base rates in the field are different, so the numbers are QC scores, not event probabilities.",
    "The head depends on the exact BirdNET v2.4 weights (sha256 stored in the artifact). A different BirdNET build needs retraining.",
]


def _pool(d: dict) -> list:
    k = sum(v[3] for v in d.values())
    n = sum(v[4] for v in d.values())
    return ek.wilson(k, n)


def write_card(res: dict) -> None:
    meta, A, B = res["meta"], res.get("experiment_a"), res["experiment_b"]
    H = B["head_at_f1_thresholds"]
    exp = res.get("export", {})
    N = res.get("noise_robustness")
    L: list[str] = []
    a = L.append
    a("# Model card: Thicket soundscape QC head v1")
    a("")
    a(
        f"Version `qc_head_v1`, created {meta['date']}. Status: experimental audio quality aid that produces warnings only; not validated on field recordings. Full evaluation: `ml/reports/qc_esc50_v1.md`."
    )
    a("")
    a("## What it is")
    a("")
    a(
        "A small linear model on top of BirdNET v2.4 embeddings. For a recording it gives a score from 0 to 1 for each of 10 sound categories:"
    )
    a("")
    for c in CATEGORIES:
        a(
            f"* `{c}` ({CATEGORY_KIND[c].replace('_', ' ')}): learned from ESC-50 {', '.join(CATEGORY_MAP[c])}."
        )
    a("")
    a(
        f"Inputs: 1024-d BirdNET window embeddings (3 s windows, 48 kHz mono) from `BirdNETRuntime.infer`. A segment feature is the mean and max over its windows. A recording is scored in segments of {exp.get('segment_windows', 2)} windows (about 6 s); each category's recording score is its k-th highest segment score with k = max(1, ceil({exp.get('segment_quantile', 0.25)} x segments)), so a category must be present in about a quarter of the recording to be flagged. Per-segment scores are available for localizing short events. Code: `backend/thicket/models/qc_head.py` (NumPy only). Weights: `backend/thicket/models/data/qc_head_v1.npz` (no pickle) with `qc_head_v1.json`."
    )
    a("")
    a("## Intended use")
    a("")
    a(
        "* Flag likely contamination and non-target sound sources in field audio (rain, wind, thunder, running water, engines and machinery, human non-speech sounds, domestic animals) so the user knows why detections may be missing or unreliable."
    )
    a(
        "* Show these as warnings next to BirdNET results in the audio QC step (`usable_with_warnings`). A person decides what to do."
    )
    a(
        "* `bird`, `insect` and `frog` scores are for internal diagnostics only. They are not detections and should not be shown to users until they are validated on field audio (see Limitations)."
    )
    a("")
    a("## Out of scope")
    a("")
    a("* Species identification of any kind, or counting animals.")
    a("* Weather measurement or event detection (for example rainfall amount or wind speed).")
    a(
        "* Speech detection or any decision about people. Speech privacy is handled by BirdNET's `Human vocal` label in the backend."
    )
    a("* Automatic deletion or rejection of recordings without a person reviewing them.")
    a("* Commercial use (license below).")
    a("")
    a("## Training data")
    a("")
    a(
        f"ESC-50 (https://github.com/karolpiczak/ESC-50, commit `{meta['esc50_commit'][:12]}`): 2,000 labeled 5 s clips in 50 classes, cut from {meta['n_source_recordings']} Freesound recordings, CC BY-NC 3.0. The 50 classes were mapped to the 10 categories above; 11 classes (fire, bells, fireworks and indoor object sounds) are negatives for every category. The mapping and its reasons are in the report."
    )
    a("")
    a("## Evaluation")
    a("")
    a(
        f"ESC-50's 5 official folds (clips from one source recording stay in one fold). For each test fold, the regularization, Platt calibration and thresholds were chosen using the other 4 folds only. Numbers are pooled over the 5 test folds; 95% CIs come from a bootstrap over source recordings ({meta['n_boot']} resamples)."
    )
    a("")
    a("| Category | Precision | Recall | F1 | Average precision | ROC AUC |")
    a("|---|---|---|---|---|---|")
    for c in CATEGORIES:
        r = H["per_class"][c]
        a(
            f"| `{c}` | {ci(r['precision'])} | {ci(r['recall'])} | {ci(r['f1'])} | {ci(r['ap'])} | {ci(r['auc'])} |"
        )
    a(
        f"| **macro** | {ci(H['macro']['precision'])} | {ci(H['macro']['recall'])} | {ci(H['macro']['f1'])} | {ci(H['macro']['ap'])} | {ci(H['macro']['auc'])} |"
    )
    a(
        f"| **micro** | {ci(H['micro']['precision'])} | {ci(H['micro']['recall'])} | {ci(H['micro']['f1'])} | {ci(H['micro']['ap'])} | |"
    )
    a("")
    base = B["birdnet_baseline"]
    a(
        f"* BirdNET's own labels used zero-shot for the same categories: macro AP {ci(base['macro']['ap'])} (see the report for which label stands in for which category; BirdNET has no rain, wind, thunder or water label)."
    )
    if A:
        a(
            f"* Reference: a 50-class linear probe on the same embeddings scores {100 * A['accuracy_mean']:.1f}% accuracy (std {100 * A['accuracy_std']:.1f} points over folds) on standard ESC-50 5-fold CV."
        )
    a(
        f"* Calibration: expected calibration error {f3(B['reliability_calibrated']['ece'])} after Platt scaling ({f3(B['reliability_raw']['ece'])} before)."
    )
    hb = B["head_at_backend_rule"]["macro"]
    a(
        f"* The backend warns only when a contamination score is above max(0.5, default threshold). At that rule, clip-level macro precision is {ci(hb['precision'])} and macro recall {ci(hb['recall'])}."
    )
    pcb = B["pooling_check"]["backgrounds"]["biophony"]["rules"]["backend"]
    a(
        f"* Long recordings (synthetic, backend warning rule): contamination covering half or all of a 30 s recording is flagged {100 * pcb['detection_rate']['3']['mean_over_categories']['segment_top25']:.0f}% / {100 * pcb['detection_rate']['6']['mean_over_categories']['segment_top25']:.0f}% of the time; clean bird, insect and frog recordings get a false warning {100 * pcb['false_flag_rate']['6']['segment_top25']['any_contamination']:.0f}% (30 s) / {100 * pcb['false_flag_rate']['12']['segment_top25']['any_contamination']:.0f}% (60 s) of the time; short bursts (one 5 s clip in 30 s) are flagged only {100 * pcb['detection_rate']['1']['mean_over_categories']['segment_top25']:.0f}% of the time."
    )
    if N:
        m = N["mixed"]
        a(
            "* Noise stress test (held-out bird, frog and insect clips mixed with rain, wind or engine sound): contaminant flagged at +10 / 0 / -10 dB SNR in "
            + "; ".join(
                f"{c} {pct(m[f'{c}@+10dB']['contaminant_flag_rate'])} / {pct(m[f'{c}@+0dB']['contaminant_flag_rate'])} / {pct(m[f'{c}@-10dB']['contaminant_flag_rate'])}"
                for c in ("rain", "wind", "engine")
            )
            + " of mixtures."
        )
    a("")
    a("These are ESC-50 numbers, not field accuracy.")
    a("")
    a("## Decision thresholds")
    a("")
    if exp:
        a(
            "Default thresholds maximize F1 on cross-validated training predictions. Strict thresholds are the lowest score that reached precision 0.9 on the same predictions; where the default already had that precision (for example `bird`), the strict value can be equal or slightly lower."
        )
        a("")
        a("| Category | Default | Strict |")
        a("|---|---|---|")
        for c in CATEGORIES:
            a(f"| `{c}` | {exp['thresholds_f1'][c]:.3f} | {exp['thresholds_p90'][c]:.3f} |")
        a("")
    a("## Limitations")
    a("")
    for s in limits(res):
        a(f"* {s}")
    a(
        "* Domain shift is the main risk: ESC-50 clips are short, loud and clean. Recorder noise, distance, reverberation, and phone microphones' automatic gain are not represented."
    )
    a("")
    a("## Ethical and privacy notes")
    a("")
    a(
        "* `human_nonspeech` can reveal that people were present (coughs, footsteps, laughter). Treat it like other personal-data signals: show it only to the recording owner, and follow the retention and deletion policy for recordings with people in them."
    )
    a("* A missing flag does not prove a recording is free of people, speech or noise.")
    a("* Warnings should explain, not blame: a flagged recording can still hold valid detections.")
    a("")
    a("## License and provenance")
    a("")
    a(
        "* License: CC BY-NC-SA 4.0. The head is derived from BirdNET v2.4 embeddings (CC BY-NC-SA 4.0) and trained on ESC-50 (CC BY-NC 3.0). Non-commercial use only; share alike."
    )
    a(
        f"* BirdNET weights sha256: `{meta['birdnet_sha256']}`. The loader exposes `matches_backbone()` so callers can skip the head when the weights differ."
    )
    if exp:
        a(f"* Artifact sha256: `{exp['artifact_sha256']}`.")
    a("* Reproduce: `python ml/train/esc50_qc.py all --data <cache dir>`.")
    a("")
    CARD.parent.mkdir(parents=True, exist_ok=True)
    CARD.write_text("\n".join(L))


def write_all(res: dict) -> None:
    write_report(res)
    write_card(res)
    for p in (REPORT, CARD):
        text = p.read_text()
        if "\u2014" in text:
            raise RuntimeError(f"em dash found in {p}")
    print(f"[report] wrote {REPORT} and {CARD}")


if __name__ == "__main__":
    write_all(json.loads((REPO / "ml" / "reports" / "qc_esc50_v1_results.json").read_text()))
