# Model card: BirdNET v2.4 in Thicket

## Summary

| | |
|---|---|
| Model | BirdNET GLOBAL 6K V2.4, FP32 TFLite |
| Authors | K. Lisa Yang Center for Conservation Bioacoustics, Cornell Lab of Ornithology, and Chemnitz University of Technology |
| Weights sha256 | `55f3e4055b1a13bfa9a2452731d0d34f6a02d6b775a334362665892794165e4c` |
| Source in Thicket | `birdnetlib==0.18.1` wheel (weights only); inference by `thicket.models.birdnet_runtime` on `ai-edge-litert` |
| License | CC BY-NC-SA 4.0 |
| Status in Thicket | Stable default model, used as published. Not retrained. |

## What it does in Thicket

* Input: 48 kHz mono audio in 3 s windows (hop 3 s by default, 1.5 s optional). The last partial window is zero-padded when it holds at least 1 s of audio.
* Output: 6,522 sigmoid scores per window. Thicket keeps every score of at least 0.10 as a raw detection.
* Taxa: most labels are birds. It also has 41 frogs and toads, 42 insects (crickets, katydids, a honey bee), 7 mammals, and non-wildlife labels (Human vocal, Human non-vocal, Human whistle, Dog, Engine, Siren, Gun, Fireworks, Environmental, Noise). Thicket labels each detection with its taxon (`backend/thicket/models/data/birdnet_v24_taxa.json`), counts only wildlife toward metrics, and uses `Human vocal` for the speech and privacy flag.
* Range and season: when coordinates are given, BirdNET's meta model scores each label for the location and week. Birds below 0.03 are marked `unlikely`, shown, and left out of metrics. The meta model scores every frog and insect near zero (it was trained on bird observations), so it is never applied to them.
* Embeddings: the 1024-d pooled features feed the soundscape QC head and the experimental frog and insect head.

## Evidence so far

* Adapter contract test on a fixed 30 s soundscape: Black-capped Chickadee 0.81 at 0 s, House Finch 0.64 at 9 s, Blue Jay 0.44 at 18 s. This pins behavior, it is not accuracy.
* Coarse taxon-level check on ESC-50 ([report](../../ml/reports/birdnet_nonbird_benchmark.md)): amphibian labels AP 0.469 (0.222 to 0.700), and at 0.60 they catch 16 of 40 frog clips at 0.73 precision; insect labels catch 6 of 80 insect clips at 0.60. ESC-50 frogs and insects are mostly not North American species, so this understates what BirdNET does on its own species, but it is a warning against trusting frog and insect absences.
* No site gold set yet. Species-level precision and recall for any pilot site are unknown until [the validation protocol](../VALIDATION.md) runs.

## Known limitations

* Detection is not abundance; one bird can produce many events.
* Performance varies by species, region, recorder, distance and noise. Published BirdNET evaluations report wide per-species differences.
* Short, quiet or distant calls are missed; loud or repetitive species dominate event counts.
* Rain, wind and engines reduce scores sharply (in the QC stress test, BirdNET's bird label reached 0.6 on 72.5% of clean bird clips but on 9% when rain was 10 dB louder).
* The range filter depends on eBird coverage and can flag real vagrants as unlikely; they stay visible for review.

## Intended use

Screening and review support for biodiversity monitoring by trained staff. Not for regulatory determinations without a site validation and human review.
