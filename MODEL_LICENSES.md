# Model and data licenses

Thicket's source code is MIT licensed. Models and data are not, and they travel with their own terms.

| Item | Where | License | What it means for you |
|---|---|---|---|
| BirdNET GLOBAL 6K v2.4 weights and labels | Installed from the `birdnetlib==0.18.1` wheel | CC BY-NC-SA 4.0 | Non-commercial use with attribution. Derivatives must share alike. Paid or commercial use needs permission from the BirdNET team (Cornell Lab of Ornithology and TU Chemnitz). |
| Dual-output BirdNET graph (logits + embeddings) | Written to `~/.cache/thicket` at first load | Same as BirdNET | Weights are unchanged; only the graph outputs are rewired. |
| Soundscape QC head v1 | `backend/thicket/models/data/qc_head_v1.npz` | CC BY-NC-SA 4.0 | Trained on BirdNET embeddings of ESC-50 (CC BY-NC 3.0), so it inherits the non-commercial terms. |
| ESC-50 | Downloaded at training time, not in this repo | CC BY-NC 3.0 | Used for training and the stitched demo clip, with attribution to the Freesound sources. |
| BirdNET-Analyzer example soundscape | `backend/tests/fixtures/soundscape_30s.flac` (first 30 s) and the demo | Distributed in the MIT-licensed BirdNET-Analyzer repository | Used as a test fixture and demo with attribution. |
| Frog and insect head v1 | `backend/thicket/models/data/frog_insect_v1.npz` | CC BY-NC-SA 4.0 | Trained on BirdNET embeddings of CC-licensed iNaturalist recordings (some NC), so it inherits the non-commercial, share-alike terms. |
| iNaturalist training recordings | Attribution in `ml/datasets/inat_v1/ATTRIBUTION.csv`; features on branch `data/inat-v1` when built by the workflow | Per recording: CC0, CC BY, CC BY-NC, CC BY-SA or CC BY-NC-SA (no-derivatives licenses are excluded) | Only derived features and attribution are kept. Treat the set as non-commercial. |
| Perch 2.0 (optional comparison) | Downloaded on the Actions runner | Apache 2.0 | A commercially friendlier backbone worth evaluating if BirdNET's license is a blocker. |

Commercial path, if it ever matters: evaluate Perch 2.0 embeddings (Apache 2.0) with the same `ml/train` scripts, retrain the heads on data you have rights to, and license BirdNET or drop it.
