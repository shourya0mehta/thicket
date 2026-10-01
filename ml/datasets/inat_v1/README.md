# thicket-inat-v1: attribution

The frog and insect head (`backend/thicket/models/data/frog_insect_v1.npz`) was trained on BirdNET embeddings of these iNaturalist sound recordings. No audio or embeddings are stored in this repository.

* `ATTRIBUTION.csv`: every recording that contributed features, with its iNaturalist observation link, license and attribution string.
* `summary.json`: recordings by group and download status.
* `plan_report.json`: the iNaturalist taxon id each species name resolved to, and per-species counts.

Rebuild the full feature dataset with `ml/pipeline/collect_inat.py` (see `ml/README.md`) or the `Dataset (iNaturalist v1)` workflow.
