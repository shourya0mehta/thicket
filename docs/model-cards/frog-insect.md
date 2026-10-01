# Model card: Thicket frog and insect head v1

## Summary

| | |
|---|---|
| What | Multi-label classifier for 30 Northeastern and Midwestern US frogs, toads, crickets, katydids and cicadas |
| How | Logistic head (one layer, 1024 to 30) on frozen BirdNET v2.4 embeddings of 3 s windows, temperature-calibrated |
| Shipped as | `backend/thicket/models/data/frog_insect_v1.npz` + `.json` card (pickle-free NumPy) |
| Status | **Experimental**, on by default (`FROG_INSECT_ENABLED=true`), always badged in the app |
| Trained | October 2026 on the thicket-inat-v1 dataset (9,016 iNaturalist recordings, 56,903 windows) |
| License | CC BY-NC-SA 4.0 (BirdNET embeddings and NC-licensed recordings) |
| Full report | [ml/reports/frog_insect_v1.md](../../ml/reports/frog_insect_v1.md) |

## Why it exists

BirdNET v2.4 already names many Eastern frogs and Orthoptera, but not every species a Northeastern farm hears. It has no *Neotibicen* or *Magicicada* cicadas, no Northern or Southern Leopard Frog, and no Blanchard's Cricket Frog. Where it does have the species, it often misses them: on this test set its own frog and insect labels reached a macro AP well below the head's (see below).

## Data

Research-grade iNaturalist sound observations under CC0, CC BY, CC BY-NC, CC BY-SA or CC BY-NC-SA (no-derivatives licenses excluded). At most 220 recordings and 4 per observer per species, first 60 s of each, downloaded at about 1.8 files per second. The negatives are 40 common birds (1,170 recordings) plus four open-set groups the head must not fire on: other frogs and toads (400 recordings, 60 species), other Orthoptera (400, 88), other cicadas (150, 38) and mammals (200, 49). Only features, a manifest and attribution are kept; no audio is redistributed. Labels are weak: the species is somewhere in the clip, and others may be too.

## Training and evaluation

* Splits are 70 / 15 / 15, grouped by observer (3,998 observers; no observer in two splits) and stratified by species.
* Two stages: stage 1 trains on every window with the clip label; stage 2 is multiple-instance refinement on each positive recording's top windows. Validation picked stage 1 (macro AP 0.790 vs 0.786). A one-hidden-layer MLP was also tried and was not meaningfully better on validation, so the linear head ships.
* Recording score is the max over windows. Per-class thresholds and temperature are fit on validation only.
* The test metrics use the test split once, with 95% intervals from a bootstrap over observers.

## Results (test split, recording level, all 36 modeled classes)

| Metric | Value (95% CI) |
|---|---|
| Macro average precision | **0.794** (0.770 to 0.838) |
| Macro F1 at validation thresholds | 0.729 (0.690 to 0.763) |
| Micro F1 | 0.761 (0.735 to 0.786) |
| Macro ROC AUC | 0.988 (0.984 to 0.991) |
| Calibration error (ECE) | 0.014 raw, 0.004 after temperature scaling |
| Head minus BirdNET macro AP, 27 shared species | **+0.155** (+0.109 to +0.190) |

Per species, from the full report: Wood Frog 0.80, American Toad 0.75, Gray Treefrog 0.88, Cope's Gray Treefrog 0.95, Green Frog 0.70, Bullfrog 0.82, Northern Leopard Frog 0.80, Western Chorus Frog 0.85, Fall Field Cricket 0.85, Snowy Tree Cricket 0.96, Common True Katydid 0.80, Dog-day Cicada 0.86, Scissor-grinder 0.89, Pharaoh Cicada 0.95 (AP).

![Per-species AP](../../ml/reports/figures/frog_insect_ap.png)

## Release bar and what ships

A class ships only when, on the test split, it has at least 10 test recordings from 3 or more observers, its AP's lower 95% bound is at least 0.5, and its AP is not below BirdNET's own label for the same species. **30 of 36 classes pass.** Withheld (not in the shipped head, so they cannot fire):

| Species | Why |
|---|---|
| Spring Peeper | AP 0.62, lower bound 0.44. BirdNET still reports it (at its own, weaker AP of 0.29) |
| Carolina Ground Cricket | AP lower bound 0.38 |
| Black-horned Tree Cricket, Narrow-winged Tree Cricket, Handsome Trig | Fewer than 10 test recordings |
| Fork-tailed Bush Katydid | Too few recordings, and BirdNET's label did better |
| Robust Conehead | Only 6 recordings in the whole dataset; not modeled |

Spring Peeper is the obvious gap for an Ithaca pilot. Its iNaturalist recordings are mostly dense mixed choruses, so clip labels are especially weak; a site gold set with call-level labels is the way to fix it.

## How the product uses it

* With both models in one analysis, BirdNET's windows for the 30 head species are set aside before consolidation, so a call is never counted twice. BirdNET's windows stay visible as raw detections, and the analysis says which species the rule applied to. All other species come from BirdNET.
* Per-class thresholds act as floors, and the decision threshold applies on top.
* BirdNET's range and season filter does not apply to these species; their plausibility is `unknown`.

## Limits

* **Open-set false positives.** On test recordings of species outside the label set, the head fired on 3% of bird recordings but on **26% of other frogs and toads, 27% of other Orthoptera and 22% of other cicadas**. Unlisted relatives get mistaken for listed ones. Review detections in regions with many unlisted species.
* iNaturalist clips are opportunistic, mostly close and loud, and centered on one caller. Passive recorders hear distant choruses through wind and rain, so expect lower recall in the field. These are not field numbers.
* Gray Treefrog and Cope's Gray Treefrog differ mainly in pulse rate and are often identified by range on iNaturalist; confusion between them is likely.
* Timing is window-level (3 s) and was never checked against call-level labels.
* Detection is not abundance. Chorus species (peepers, cicadas) are about presence and intensity, not events per animal.

## History

The 2025 prototype's 11-class OpenSoundscape ResNet18 (reported "0.849" validation score) failed later validation and is not reused. This head replaces it.

## Reproduce

```bash
python ml/pipeline/collect_inat.py plan  --config ml/configs/inat_v1.json --out data/plan.csv
python ml/pipeline/collect_inat.py embed --config ml/configs/inat_v1.json --plan data/plan.csv \
    --shard 0 --num-shards 1 --out data/out --audio-dir data/audio
python ml/pipeline/collect_inat.py merge --inputs data/out --out data/inat_v1
python ml/train/frog_insect.py --data data/inat_v1 --out data/model --model linear
python ml/train/package_head.py --run data/model --out backend/thicket/models/data/frog_insect_v1.npz
```

Or run the `Dataset (iNaturalist v1)` GitHub workflow, which does all of it on Actions runners.
