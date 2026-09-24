# Model card: Thicket frog and insect head (not released)

## Status

**Not trained, not enabled.** The adapter, the dataset pipeline and the training and evaluation code exist and are tested. No weights ship with Thicket, and `FROG_INSECT_ENABLED` is `false` by default. This card describes what the model will be and the bar it must clear.

## Why it exists

BirdNET v2.4 already covers many Eastern frogs and Orthoptera, but not all of the species a Northeastern or Midwestern pilot hears. Missing from its label set: every *Neotibicen* and *Magicicada* cicada, Northern and Southern Leopard Frogs, and Blanchard's Cricket Frog. The head adds those and gives a second opinion on the rest.

## History

The 2025 prototype trained an 11-class OpenSoundscape ResNet18 on 490 iNaturalist clips and reported a best validation score of 0.849 with an unclear metric and a split that may have leaked related observations. It returned one whole-clip interval per class and failed a later validation. Those weights are not reused and that number is not an accuracy claim.

## Design

* **Backbone**: frozen BirdNET v2.4 embeddings (1024-d, 3 s windows), so the head gets localized windows and timestamps for free and shares the one BirdNET pass per analysis. Perch 2.0 embeddings (Apache 2.0) are collected in the same run for comparison.
* **Head**: multi-label logistic regression (or a one-hidden-layer MLP) in pure NumPy at inference, with per-class thresholds and temperature scaling, loaded from a pickle-free `.npz`.
* **Labels**: 17 anurans and 20 crickets, katydids and cicadas (`ml/configs/inat_v1.json`).
* **Negatives**: 40 common birds and open-set groups (other frogs and toads, other Orthoptera, other cicadas, mammals) with all-zero targets.

## Data (to be built)

`.github/workflows/dataset-inat.yml` collects research-grade iNaturalist sound observations under CC0, CC BY, CC BY-NC, CC BY-SA and CC BY-NC-SA (no-derivatives excluded), at most 4 recordings per observer per species and 220 per species, first 60 s of each, downloads rate limited to iNaturalist's guidance. Only features, a manifest (with observer id, rounded coordinates, license, audio hash) and an attribution file are stored. Labels are weak: the species is somewhere in the clip, and others may be too.

## Training and evaluation (`ml/train/frog_insect.py`)

1. Checks before any metric: manifest integrity, label-set compatibility with the config, embedding model hash.
2. Observer-grouped 70 / 15 / 15 split. No observer appears in two splits.
3. Stage 1 on all windows with clip labels; stage 2 multiple-instance refinement on each positive recording's top windows. The stage is picked on validation.
4. Recording-level scores (max over windows). Per-class thresholds and temperature on validation only.
5. Test: per-class AP, ROC AUC, precision, recall and F1 at the validation thresholds, observer-bootstrap 95% intervals, calibration, open-set false positive rate, and BirdNET's own labels on the same recordings for the species it covers.

## Release bar

A class is only enabled in the product when, on the observer-disjoint test split, it has at least 10 test recordings from at least 3 observers (checked by the script, which lists every class below the bar), its AP interval sits clearly above the class's base rate, and it beats BirdNET's own label where BirdNET has one (both read from the report by a person). Even then it stays marked experimental until a site gold set confirms it ([validation protocol](../VALIDATION.md)).

## Limitations to expect

* iNaturalist recordings are mostly close, phone-recorded and centered on one caller; passive recorders hear distant choruses. Expect a drop in the field.
* Gray Treefrog and Cope's Gray Treefrog differ mainly in pulse rate and are often identified by range on iNaturalist; confusion between them is likely.
* Chorus-forming species (peepers, cicadas) are about presence and intensity, not events per animal.
