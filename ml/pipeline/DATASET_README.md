# thicket-inat-v1 (derived features)

This branch holds **derived features only** for the Thicket frog and insect
model. No audio is redistributed here.

* `datasets/inat_v1/manifest.csv` one row per planned recording: group, label,
  iNaturalist observation and sound ids, license, observer id (numeric), date,
  coordinates rounded to 0.1 degree, download and decode status, SHA-256 of
  the audio bytes that were processed, duration, and window count.
* `datasets/inat_v1/ATTRIBUTION.csv` attribution string and license for every
  recording that contributed features. Each links to its iNaturalist
  observation.
* `datasets/inat_v1/birdnet_part_XX.npz` 3 s windows (hop 3 s, first 60 s of
  each recording) with BirdNET v2.4 1024-d embeddings (float16), logits for
  every non-bird BirdNET class plus the benchmark bird species, BirdNET top-5,
  window RMS level, and the max bird probability.
* `datasets/inat_v1/perch_part_XX.npz` (when available) 5 s windows with
  Perch 2.0 embeddings.
* `plan_report.json` per-taxon counts and the iNaturalist taxon ids that the
  names resolved to.

Labels are **clip level and weak**: an observation says the species is
audible somewhere in the recording, not in every window, and other species
may also be present. Evaluate at the recording level and split by observer.

Licenses: each recording keeps its own Creative Commons license (CC0, CC BY,
CC BY-NC, CC BY-SA or CC BY-NC-SA; no-derivatives licenses were excluded).
BirdNET embeddings come from a CC BY-NC-SA 4.0 model. Treat this dataset as
non-commercial.

Built by `.github/workflows/dataset-inat.yml` from `ml/pipeline/collect_inat.py`.
