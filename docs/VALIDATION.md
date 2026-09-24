# Validating Thicket at a pilot site

Thicket makes no field accuracy claim until a site has been checked. This is the protocol, and the tooling that runs it.

## 1. Agree on targets before looking at results

Write these down with the partner first:

* Priority species (the ones decisions depend on) and the list annotators will label (the annotation scope).
* Targets, for example precision at least 0.90 on priority species at the chosen threshold, recall at least 0.70 where feasible, and a site richness within an agreed range of expert point counts.
* What happens to a species that misses the bar: it is shown for review only, or dropped.

## 2. Build a site gold set

* 200 to 400 clips of 10 to 60 seconds per site, stratified across dawn, day, dusk and night, habitats, weather and noise.
* Include negatives on purpose: silence, wind, rain, traffic, other taxa.
* Two independent annotators where possible. Resolve disagreements and report agreement (Cohen's kappa per species).
* Record the recorder model, gain and placement.
* Hold out by site and date, never by random clip, so the benchmark sees conditions the thresholds were not tuned on.

## 3. Annotation format

One CSV, one row per call interval or per species present in a clip:

```
recording,scientific_name,start_seconds,end_seconds,site,annotator
dawn_01.wav,Cardinalis cardinalis,3.2,5.0,north_meadow,AB
dawn_01.wav,Turdus migratorius,,,north_meadow,AB
dawn_02.wav,,,,north_meadow,AB
```

* Empty times mean the species is present somewhere in the clip.
* An empty species means the clip was annotated and holds none of the scoped species.
* Use BirdNET's scientific names (the benchmark lists any annotated name the model cannot predict and skips it).

## 4. Run the benchmark

```bash
cd backend && source .venv/bin/activate && cd ..
python ml/eval/gold_benchmark.py --audio-dir pilot/clips --annotations pilot/gold.csv \
  --out ml/reports/pilot_north_meadow --lat 42.44 --lon -76.50 --date 2026-05-14 \
  --exclude-unlikely --target-precision 0.9
```

It writes `benchmark.md`, `results.json` and `thresholds.csv`:

* **Recording level, per species**: average precision with bootstrap 95% intervals (over sites when there are at least five, otherwise over recordings), and precision, recall and F1 at fixed thresholds.
* **Event level** for rows with times: share of predicted events that overlap an annotated call, and share of annotated calls that were found, using the product's own consolidation rule.
* **Site threshold table**: for each species, the lowest threshold that reaches the target precision. The precision and recall next to it are cross-fitted (thresholds chosen on one half of the sites, scored on the other), so they are honest estimates of what the threshold will do on new recordings.
* **Detections outside the annotation scope**: never counted as errors, listed so someone can listen to them.
* Every run records the annotations hash, model hash and settings.

## 5. Corroborate in the field

* Concurrent point counts by a trained observer for a subset of mornings.
* Two recorders 10 to 20 m apart on some days to see how much placement matters.
* Remember what acoustics misses: quiet species, species that call rarely, and everything beyond detection range.

## 6. Publish the evidence package

For each pilot: the protocol, `benchmark.md`, the threshold table, the model cards, a reproducibility log (code commit, model hash, annotations hash), a gallery of false positives and misses, the QA checklist, and the limits (which species and conditions are not covered). Thicket's defaults only change after this package exists.

## Why these rules

The historical Thicket evaluation went wrong in ways this protocol blocks: a model parameter sent in the wrong place silently tested BirdNET instead of the frog model, the frog model was scored on bird classes it could not predict, timestamps came from energy peaks rather than experts, and a single F1 was reported without its configuration. `gold_benchmark.py` checks the label set, records model identity and settings, and only scores species inside the annotation scope.
