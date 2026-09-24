# Data sources checked for Thicket ML (September 2026)

This file records every audio source we looked at for the soundscape QC head
(Task 1) and for frog and insect species work (Task 2), whether we used it,
and why. It was written from checks run on 2026-09-24.

## Network rules for this work

Only GitHub (git, raw.githubusercontent.com, media.githubusercontent.com),
PyPI and npm were reachable. iNaturalist, xeno-canto, Zenodo, Hugging Face,
Kaggle, Freesound, Figshare, Dryad, archive.org and AWS S3 were blocked. We
did not use mirrors, proxies or re-uploads of content from blocked hosts.
Repositories were inspected cheaply first (`git clone --filter=blob:none
--no-checkout`, then `git ls-tree` for file names and `git show` for README
and LICENSE files) before any audio was downloaded.

## Used

| Source | License | What it contains | Recordist / source diversity | Used for |
|---|---|---|---|---|
| ESC-50, https://github.com/karolpiczak/ESC-50 (commit `33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6`) | CC BY-NC 3.0 for the dataset as a whole (ESC-10 subset CC BY 3.0); per-clip Freesound attribution in the repository LICENSE file | 2,000 five-second clips, 50 classes x 40, 5 predefined folds that keep clips of one source recording together. Includes `frog` (40), `insects` (40, mostly flying insects), `crickets` (40), `chirping_birds`, `crow`, `rain`, `wind`, `thunderstorm`, `engine` and others | 1,524 distinct Freesound source recordings by many Freesound users. Species and recording locations are not given | QC head training and evaluation (`ml/reports/qc_esc50_v1.md`); coarse BirdNET amphibian / insect benchmark (`ml/reports/birdnet_nonbird_benchmark.md`) |
| OpenSoundscape test file `tests/audio/great_plains_toad.wav`, https://github.com/kitzeslab/opensoundscape (commit `0aa40d995b0f73a606f2f34ace89d9a598dc0514`) | Repository is MIT licensed; recordist not stated | One 44.6 s recording labeled Great Plains Toad (*Anaxyrus cognatus*) | One file | Smoke check only in the BirdNET benchmark. Not evidence of accuracy |

## Checked and not used

| Source | License | Content | Why not used |
|---|---|---|---|
| iNaturalist research-grade sound observations (the planned `thicket-inat-v1` dataset, `ml/pipeline/collect_inat.py`) | Per recording CC0 / CC BY / CC BY-NC / CC BY-SA / CC BY-NC-SA | North American frogs, toads, crickets, katydids, cicadas, birds and open-set negatives, with observer ids | api.inaturalist.org and static.inaturalist.org are blocked here. This is still the right source: build it on a machine or GitHub Actions runner that can reach iNaturalist (see `ml/README.md`) and run `ml/train/frog_insect.py` on it |
| tconnie/cicada, https://github.com/tconnie/cicada | No license file; README says recordings were "collected from different online sources" | 43 WAV files of three periodical cicadas: *Magicicada cassini* (14), *M. septendecim* (15), *M. septendecula* (14) | License and provenance unclear, so we cannot use it. Also below the 15-per-class bar for two species, recordist diversity unknown, and BirdNET v2.4 has no cicada classes to benchmark |
| ak7ra/frog_classification, https://github.com/ak7ra/frog_classification | No license in the repository; audio derived from a Mendeley Data set (doi 10.17632/5j852hzfjs.1) whose license we could not check (Mendeley is not reachable) | About 6,300 segments of six frog species from Yasuni National Park, Ecuador | Not North American (BirdNET does not cover these species), a re-upload of another host's data, license unclear |
| soundclim/anuraset, https://github.com/soundclim/anuraset | Code MIT; data CC BY on Zenodo | Code only in the repository; audio of Brazilian anurans is on Zenodo | Audio not on GitHub (Zenodo blocked); not North American |
| mariusfaiss/InsectSet32 code repository | Code repository; data CC BY 4.0 on Zenodo | Code only; InsectSet32 / 47 / 66 / 459 audio is on Zenodo | Audio not reachable; mostly European Orthoptera and cicadas |
| visipedia/inat_sounds (iNatSounds 2024), https://github.com/visipedia/inat_sounds | Annotations in the repository; audio under iNaturalist terms | Annotation files on GitHub; audio archives (81 GB train) on AWS S3 | S3 not reachable; the audio is iNaturalist content, which is blocked here |
| ivclab/Sound20, https://github.com/ivclab/Sound20 | No license file seen | Precomputed spectrogram arrays (`.npy`), no audio | No audio, so no BirdNET embeddings can be computed |
| naturewaves/Rthoptera, https://github.com/naturewaves/Rthoptera | CC BY-NC 4.0 | R package for insect bioacoustics; no audio files in the repository | No audio |
| kitzeslab/opensoundscape other test files | MIT | 23 other short test files (birds, ARU samples, silence, stereo) | Not frog or insect data |
| scikit-maad/scikit-maad `data/` | BSD-style license | Soundscape recordings from France and French Guiana used for acoustic indices | No species labels |
| bioacoustic-ai/bioacoustics-datasets (list of 99 datasets), https://github.com/bioacoustic-ai/bioacoustics-datasets | List only | Frog or insect entries: ECOSoundSet, InsectSet32/47/66/459, InsectSound1000, Panama Katydids (two sets), HumBugDB, AnuraSet, Beehive sets, Rainforest Connection (Kaggle), VibroScape (GitHub, substrate vibrations), iNatSounds | Every airborne frog or insect audio set in the list is hosted on Zenodo, Kaggle, Figshare or S3, or is outside North America. VibroScape records substrate-borne vibrations, not airborne sound, so it does not match BirdNET input; not downloaded |
| Web searches ("github frog calls dataset wav", "cicada species recognition github", "orthoptera audio github", species-name searches) | n/a | Mostly papers, Zenodo records, and single-sound pages | No further openly licensed, species-labeled North American frog or insect audio on GitHub, PyPI or npm |

## Conclusion for Task 2

We found no reachable, openly licensed, species-labeled North American frog or
insect audio with at least about 15 recordings per class from at least 3
distinct recordists per class. We therefore did **not** train a species-level
frog or insect head here, and we did not run a species-level BirdNET benchmark.
What we did instead:

* a taxon-level benchmark of BirdNET's amphibian and insect labels on ESC-50
  (`ml/reports/birdnet_nonbird_benchmark.md`), and
* a ready-to-run training and evaluation pipeline for the iNaturalist feature
  dataset (`ml/train/frog_insect.py`, tested end to end on synthetic data in
  `ml/tests/test_frog_insect_pipeline.py`).
