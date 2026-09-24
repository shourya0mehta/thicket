# Model card: Thicket soundscape QC head v1

Version `qc_head_v1`, created 2026-09-24. Status: experimental audio quality aid that produces warnings only; not validated on field recordings. Full evaluation: `ml/reports/qc_esc50_v1.md`.

## What it is

A small linear model on top of BirdNET v2.4 embeddings. For a recording it gives a score from 0 to 1 for each of 10 sound categories:

* `rain` (geophony): learned from ESC-50 rain.
* `wind` (geophony): learned from ESC-50 wind.
* `thunder` (geophony): learned from ESC-50 thunderstorm.
* `water` (geophony): learned from ESC-50 sea_waves, water_drops, pouring_water, toilet_flush.
* `engine_machinery` (anthropophony): learned from ESC-50 engine, train, airplane, helicopter, chainsaw, hand_saw, vacuum_cleaner, washing_machine, siren, car_horn.
* `human_nonspeech` (anthropophony): learned from ESC-50 crying_baby, sneezing, clapping, breathing, coughing, footsteps, laughing, brushing_teeth, snoring, drinking_sipping.
* `domestic_animal` (biophony non target): learned from ESC-50 dog, cat, hen, rooster, cow, pig, sheep.
* `bird` (biophony): learned from ESC-50 chirping_birds, crow.
* `insect` (biophony): learned from ESC-50 insects, crickets.
* `frog` (biophony): learned from ESC-50 frog.

Inputs: 1024-d BirdNET window embeddings (3 s windows, 48 kHz mono) from `BirdNETRuntime.infer`. A segment feature is the mean and max over its windows. A recording is scored in segments of 2 windows (about 6 s); each category's recording score is its k-th highest segment score with k = max(1, ceil(0.25 x segments)), so a category must be present in about a quarter of the recording to be flagged. Per-segment scores are available for localizing short events. Code: `backend/thicket/models/qc_head.py` (NumPy only). Weights: `backend/thicket/models/data/qc_head_v1.npz` (no pickle) with `qc_head_v1.json`.

## Intended use

* Flag likely contamination and non-target sound sources in field audio (rain, wind, thunder, running water, engines and machinery, human non-speech sounds, domestic animals) so the user knows why detections may be missing or unreliable.
* Show these as warnings next to BirdNET results in the audio QC step (`usable_with_warnings`). A person decides what to do.
* `bird`, `insect` and `frog` scores are for internal diagnostics only. They are not detections and should not be shown to users until they are validated on field audio (see Limitations).

## Out of scope

* Species identification of any kind, or counting animals.
* Weather measurement or event detection (for example rainfall amount or wind speed).
* Speech detection or any decision about people. Speech privacy is handled by BirdNET's `Human vocal` label in the backend.
* Automatic deletion or rejection of recordings without a person reviewing them.
* Commercial use (license below).

## Training data

ESC-50 (https://github.com/karolpiczak/ESC-50, commit `33c8ce9eb2cf`): 2,000 labeled 5 s clips in 50 classes, cut from 1524 Freesound recordings, CC BY-NC 3.0. The 50 classes were mapped to the 10 categories above; 11 classes (fire, bells, fireworks and indoor object sounds) are negatives for every category. The mapping and its reasons are in the report.

## Evaluation

ESC-50's 5 official folds (clips from one source recording stay in one fold). For each test fold, the regularization, Platt calibration and thresholds were chosen using the other 4 folds only. Numbers are pooled over the 5 test folds; 95% CIs come from a bootstrap over source recordings (1000 resamples).

| Category | Precision | Recall | F1 | Average precision | ROC AUC |
|---|---|---|---|---|---|
| `rain` | 0.700 (0.555 to 0.837) | 0.700 (0.552 to 0.826) | 0.700 (0.568 to 0.804) | 0.734 (0.597 to 0.846) | 0.971 (0.944 to 0.992) |
| `wind` | 0.529 (0.278 to 0.742) | 0.450 (0.222 to 0.667) | 0.486 (0.264 to 0.667) | 0.580 (0.324 to 0.758) | 0.965 (0.932 to 0.987) |
| `thunder` | 0.805 (0.630 to 0.939) | 0.825 (0.682 to 0.951) | 0.815 (0.675 to 0.917) | 0.881 (0.778 to 0.961) | 0.996 (0.992 to 0.999) |
| `water` | 0.829 (0.760 to 0.892) | 0.819 (0.746 to 0.878) | 0.824 (0.768 to 0.870) | 0.903 (0.861 to 0.939) | 0.981 (0.970 to 0.990) |
| `engine_machinery` | 0.805 (0.757 to 0.852) | 0.855 (0.818 to 0.891) | 0.829 (0.793 to 0.861) | 0.891 (0.854 to 0.923) | 0.970 (0.961 to 0.978) |
| `human_nonspeech` | 0.861 (0.823 to 0.896) | 0.838 (0.799 to 0.874) | 0.849 (0.817 to 0.876) | 0.918 (0.893 to 0.941) | 0.975 (0.967 to 0.982) |
| `domestic_animal` | 0.850 (0.801 to 0.897) | 0.914 (0.879 to 0.946) | 0.881 (0.847 to 0.910) | 0.940 (0.912 to 0.963) | 0.989 (0.984 to 0.993) |
| `bird` | 0.947 (0.879 to 1.000) | 0.887 (0.800 to 0.958) | 0.916 (0.859 to 0.964) | 0.982 (0.960 to 0.995) | 0.999 (0.998 to 1.000) |
| `insect` | 0.812 (0.714 to 0.909) | 0.812 (0.701 to 0.903) | 0.812 (0.727 to 0.884) | 0.879 (0.797 to 0.945) | 0.980 (0.959 to 0.996) |
| `frog` | 0.878 (0.725 to 0.979) | 0.900 (0.771 to 1.000) | 0.889 (0.789 to 0.961) | 0.957 (0.890 to 0.995) | 0.998 (0.995 to 1.000) |
| **macro** | 0.802 (0.764 to 0.834) | 0.800 (0.767 to 0.831) | 0.800 (0.768 to 0.827) | 0.866 (0.835 to 0.896) | 0.982 (0.977 to 0.987) |
| **micro** | 0.830 (0.811 to 0.850) | 0.843 (0.825 to 0.861) | 0.837 (0.819 to 0.852) | 0.908 (0.893 to 0.921) | |

* BirdNET's own labels used zero-shot for the same categories: macro AP 0.339 (0.309 to 0.370) (see the report for which label stands in for which category; BirdNET has no rain, wind, thunder or water label).
* Reference: a 50-class linear probe on the same embeddings scores 84.4% accuracy (std 1.4 points over folds) on standard ESC-50 5-fold CV.
* Calibration: expected calibration error 0.004 after Platt scaling (0.010 before).
* The backend warns only when a contamination score is above max(0.5, default threshold). At that rule, clip-level macro precision is 0.854 (0.815 to 0.886) and macro recall 0.745 (0.710 to 0.778).
* Long recordings (synthetic, backend warning rule): contamination covering half or all of a 30 s recording is flagged 80% / 93% of the time; clean bird, insect and frog recordings get a false warning 5% (30 s) / 1% (60 s) of the time; short bursts (one 5 s clip in 30 s) are flagged only 5% of the time.
* Noise stress test (held-out bird, frog and insect clips mixed with rain, wind or engine sound): contaminant flagged at +10 / 0 / -10 dB SNR in rain 10% / 22% / 48%; wind 2% / 4% / 12%; engine 10% / 28% / 42% of mixtures.

These are ESC-50 numbers, not field accuracy.

## Decision thresholds

Default thresholds maximize F1 on cross-validated training predictions. Strict thresholds are the lowest score that reached precision 0.9 on the same predictions; where the default already had that precision (for example `bird`), the strict value can be equal or slightly lower.

| Category | Default | Strict |
|---|---|---|
| `rain` | 0.425 | 0.570 |
| `wind` | 0.390 | 0.734 |
| `thunder` | 0.670 | 0.664 |
| `water` | 0.478 | 0.536 |
| `engine_machinery` | 0.373 | 0.787 |
| `human_nonspeech` | 0.370 | 0.611 |
| `domestic_animal` | 0.355 | 0.555 |
| `bird` | 0.387 | 0.354 |
| `insect` | 0.331 | 0.519 |
| `frog` | 0.293 | 0.293 |

## Limitations

* ESC-50 is a set of curated Freesound clips, mostly recorded close to the source, with one label per clip. Passive field recordings have distant, overlapping and quiet sources, recorder self-noise and long durations. Expect lower accuracy in the field; no field validation has been done.
* Co-occurring sources never appear in training (each clip has one class), so a clip with both rain and birds is out of distribution. The noise stress test is a first look at that case, with only three contaminants.
* Contamination mixed with a target sound is often missed. In the noise stress test, with the contaminant 10 dB louder than the bird, frog or insect, the head flagged wind in 12%, rain in 48% and engine sound in 42% of mixtures; at equal level (0 dB) in 4%, 22% and 28%. Training never saw mixtures; training on mixed clips is the obvious next step.
* Each category is learned from few source recordings (40 clips for rain, wind, thunder and frog). Rain on a tent and rain on leaves, or a distant highway, may not look like the ESC-50 examples.
* `bird`, `insect` and `frog` are coarse scores learned from 2, 2 and 1 ESC-50 classes. They are not species detectors and must not be reported as detections. On one real dawn-chorus recording the `bird` score stayed low, so do not show these three to users until they are validated on field audio.
* Probabilities are calibrated on ESC-50 5 s clips. A recording score is an order statistic over 6 s segments, not a single-clip probability, and base rates in the field are different, so the numbers are QC scores, not event probabilities.
* The head depends on the exact BirdNET v2.4 weights (sha256 stored in the artifact). A different BirdNET build needs retraining.
* Domain shift is the main risk: ESC-50 clips are short, loud and clean. Recorder noise, distance, reverberation, and phone microphones' automatic gain are not represented.

## Ethical and privacy notes

* `human_nonspeech` can reveal that people were present (coughs, footsteps, laughter). Treat it like other personal-data signals: show it only to the recording owner, and follow the retention and deletion policy for recordings with people in them.
* A missing flag does not prove a recording is free of people, speech or noise.
* Warnings should explain, not blame: a flagged recording can still hold valid detections.

## License and provenance

* License: CC BY-NC-SA 4.0. The head is derived from BirdNET v2.4 embeddings (CC BY-NC-SA 4.0) and trained on ESC-50 (CC BY-NC 3.0). Non-commercial use only; share alike.
* BirdNET weights sha256: `55f3e4055b1a13bfa9a2452731d0d34f6a02d6b775a334362665892794165e4c`. The loader exposes `matches_backbone()` so callers can skip the head when the weights differ.
* Artifact sha256: `6d0c2787c6eeb06a85e2922194c5d350a721cf5e09a550842b846a0ce5b8126c`.
* Reproduce: `python ml/train/esc50_qc.py all --data <cache dir>`.
