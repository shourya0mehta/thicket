# Thicket ML

This folder holds everything used to build, evaluate and document Thicket's
own models. Thicket's detections come from pretrained BirdNET v2.4. The models
here are small heads on BirdNET's 1024-d window embeddings, trained only when
a benchmark justifies it (product spec, sections 2 and 8).

```
ml/
  configs/inat_v1.json        target species and dataset settings (iNaturalist)
  pipeline/                   dataset builder (iNaturalist -> BirdNET features)
  train/
    esc50_qc.py               soundscape QC head on ESC-50 (Task 1)
    esc50_qc_report.py        writes the QC report and model card from results
    esc50_qc_mix.py           QC head v2 experiment: synthetic mixture training
    esc50_qc_mix_report.py    writes the v2 report (and v2 card if it ships)
    birdnet_nonbird_benchmark.py  BirdNET amphibian / insect labels on ESC-50
    frog_insect.py            frog and insect species head (iNaturalist format)
    evalkit.py, linear.py, plotstyle.py   shared metrics, models, figure style
  tests/test_frog_insect_pipeline.py      synthetic end-to-end test
  reports/                    reports, figures, results JSON, data sources
```

Set up once (from the repository root):

```
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -e ".[birdnet,ml,dev]"      # BirdNET weights come from the birdnetlib wheel
sudo apt-get install ffmpeg              # decoding (libsndfile fallback also works)
cd ..
```

All BirdNET inference uses `thicket.models.birdnet_runtime.BirdNETRuntime`
and `frame_windows`, so training features match what the API computes.

## 1. Soundscape QC head (ESC-50)

Flags likely contamination and non-target sound sources (rain, wind, thunder,
water, engines and machinery, human non-speech sounds, domestic animals) and
reports bird, insect and frog presence as information. Output:
`backend/thicket/models/data/qc_head_v1.npz` (pickle-free) + `qc_head_v1.json`,
loaded by `backend/thicket/models/qc_head.py` (NumPy only at inference).

Reproduce every number in `ml/reports/qc_esc50_v1.md` and
`docs/model-cards/qc-soundscape-v1.md`:

```
python ml/train/esc50_qc.py all --data /home/claude/data/esc50
```

or stage by stage:

| Stage | What it does | Time on 2 vCPU |
|---|---|---|
| `features` | sparse git clone of ESC-50 (meta + audio, about 770 MB on disk), decode to 48 kHz mono, 3 s windows with 1 s hop, BirdNET logits + embeddings, cache `features.npz` | 8 min (489 s measured) |
| `evaluate` | Experiment A (50-class linear probe) and B (QC categories), BirdNET zero-shot baselines, bootstrap CIs, calibration, confusion matrix, long-recording pooling check, figures | 29 min (1713 s measured, CPU shared with other jobs) |
| `postcheck` | optional: recompute only the pooling and operating-point checks from the saved fold models | under 1 min |
| `noise` | mixes held-out bird / frog / insect clips with rain, wind and engine clips at +10, 0 and -10 dB SNR, re-embeds, measures flags and BirdNET decay | 5 min (299 s measured) |
| `export` | final head on all 5 folds, artifact + JSON card, backend parity check | about 6 min |
| `smoke` | scores the 30 s backend test soundscape with the exported head | seconds |
| `report` | writes the report, the model card and the JSON card from `ml/reports/qc_esc50_v1_results.json` | seconds |

The `--data` folder is a cache outside the repository. Do not commit audio.
All randomness is seeded; linear models are full-batch L-BFGS, so reruns give
the same numbers on the same BLAS (tiny floating point differences are
possible on other machines).

### v2 experiment: training with synthetic mixtures

v1 often misses a contaminant mixed under a bird, frog or insect call.
`ml/train/esc50_qc_mix.py` tests whether training on synthetic mixtures
fixes that without hurting clean-clip accuracy. Mixtures add two ESC-50 clips
from the same official fold (so no source recording crosses between train and
test) and are embedded exactly like v1. **They are synthetic, not field
recordings.**

```
python ml/train/esc50_qc_mix.py all --data /home/claude/data/esc50
```

| Stage | What it does | Time on 2 vCPU (measured) |
|---|---|---|
| `mixfeatures` | 2,000 training-pool mixtures (random SNR -10 to +15 dB) and 1,800 fixed-SNR evaluation mixtures (+10, 0, -10 dB), BirdNET embeddings cached as `mix_features.npz` | 12 min |
| `evaluate --variant v2a` | first attempt: union labels, one C for all categories | 9 min |
| `diagnose` | recipe comparison on training folds only (outer fold 1 untouched) | 2 min |
| `evaluate --variant v2b` | audibility-gated labels, per-category choice of mixture weight and C under a clean-AP constraint | 21 min |
| `export` | writes `qc_head_v2.npz` + `.json` only if the pre-registered ship criteria pass (`--force` overrides) | about 6 min |
| `report` | `ml/reports/qc_esc50_v2.md` (+ the v2 model card when shipped) | seconds |

Status on 2026-09-24: neither attempt met the pre-registered ship criteria
(v2b passed five of six; its clean-clip F1 at its own thresholds was too
low), so **v1 remains the default** and no v2 file is packaged. `qc_head.py`
already loads versions by name and would prefer a packaged v2. See
`ml/reports/qc_esc50_v2.md` for the numbers and the honesty note (v2b was
designed after seeing v2a's results).

## 2. BirdNET non-bird benchmark (ESC-50)

Taxon-level check of BirdNET's 41 amphibian and 42 insect labels on ESC-50
`frog`, `insects` and `crickets` clips. Needs the cached ESC-50 features:

```
python ml/train/birdnet_nonbird_benchmark.py --data /home/claude/data/esc50 --smoke
```

Writes `ml/reports/birdnet_nonbird_benchmark.md`. `--smoke` also scores one
Great Plains Toad file from the OpenSoundscape test suite (anecdote only).

## 3. Frog and insect species head (iNaturalist features)

### Rebuild the dataset

The dataset needs a machine that can reach `api.inaturalist.org` and
`static.inaturalist.org` (a laptop or a GitHub Actions runner; the sandbox
used for this work cannot). Two options:

* GitHub Actions: run the workflow **Dataset (iNaturalist v1)**
  (`.github/workflows/dataset-inat.yml`, manual dispatch). It plans the
  download, embeds 8 shards in parallel (rate limited to about 2 files/s in
  total, per iNaturalist API guidance), optionally adds Perch 2.0 embeddings,
  merges, and pushes the derived features to the `data/inat-v1` branch. Raw
  audio is never committed.
* Locally:

  ```
  python ml/pipeline/collect_inat.py plan  --config ml/configs/inat_v1.json --out work/plan.csv
  python ml/pipeline/collect_inat.py embed --config ml/configs/inat_v1.json --plan work/plan.csv \
      --shard 0 --num-shards 1 --out work/out --audio-dir work/audio --max-rate 0.5
  python ml/pipeline/collect_inat.py merge --inputs work/out --out data/inat_v1
  ```

The result is `manifest.csv` + `ATTRIBUTION.csv` + `birdnet_part_XX.npz` (+
optional `perch_part_XX.npz`); see `ml/pipeline/DATASET_README.md`.

### Train and evaluate

```
python ml/train/frog_insect.py --data data/inat_v1 --out ml/reports \
    --export-path ml/artifacts/frog_insect_head_v1.npz
```

Before any metric the script checks the run parameters, manifest integrity
(unique ids, window counts, duplicate audio), label-set compatibility with
`ml/configs/inat_v1.json`, and model identity (BirdNET v2.4 label space,
embedding size, weights hash when present), and stops on a failure. Splits
are grouped by observer (`user_id`), stratified and seeded (70/15/15). It
trains a stage-1 multi-label head on all windows with clip labels, then a
stage-2 multiple-instance refinement (top-k windows per positive recording),
chooses between them, the regularization strength, the temperature and the
per-class thresholds on validation only, and reports test metrics at the
recording level (max over windows) with observer-bootstrap CIs, calibration,
open-set false positive rates and a BirdNET zero-shot comparison (and Perch,
when its features exist). Output: `frog_insect_v1.md`, `results.json`,
`splits.csv`, figures and the head (`W1`, `b1`, optional `W2`, `b2`,
`labels`, `common_names`, `taxa`, `thresholds`, `temperature`,
`embedding_mean`, `embedding_std`), which `backend/thicket/models/frog_insect.py`
loads. A class is ready for users only if it passes the report's release bar
(default: at least 10 test recordings from at least 3 test observers) and a
model card exists.

Status on 2026-09-24: the iNaturalist dataset has not been built from this
sandbox, and no other reachable data met the bar (see
`ml/reports/data_sources.md`), so **no frog or insect species head has been
trained or released**. The pipeline is tested end to end on synthetic data:

```
pytest ml/tests -q
```

(CI currently runs only `backend/tests`; add `pytest ml/tests` to CI to keep this pipeline tested.)

## Data licenses

| Data | License | Consequence |
|---|---|---|
| BirdNET v2.4 weights (and therefore every embedding) | CC BY-NC-SA 4.0 | Every head trained on BirdNET embeddings is non-commercial, share-alike |
| ESC-50 | CC BY-NC 3.0 (ESC-10 subset CC BY 3.0) | QC head is CC BY-NC-SA 4.0 |
| iNaturalist recordings | CC0 / CC BY / CC BY-NC / CC BY-SA / CC BY-NC-SA per recording (no ND) | Keep `ATTRIBUTION.csv`; treat the dataset and any head as non-commercial |
| OpenSoundscape test file | MIT repository | Smoke check only |

## Honesty rules used here

* Every number in a report is read from a results JSON written by the script
  that computed it, together with its configuration.
* Hyperparameters, calibration and thresholds are chosen on training or
  validation data only; test folds are touched once.
* CIs resample groups (ESC-50 source recordings; iNaturalist observers), not
  single clips, because clips from one source are correlated.
* ESC-50 metrics are not field accuracy. Nothing here has been validated on
  passive field recordings yet.
