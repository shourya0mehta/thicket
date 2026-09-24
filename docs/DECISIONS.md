# Decision log

Choices made during the September 2026 rebuild. Each entry says what was chosen, why, and what would change it. Product questions from the spec (section 32) come first, with the conservative default Thicket ships with.

## Open product questions and the defaults chosen

| # | Question | Default shipped | Why | Revisit when |
|---|---|---|---|---|
| 1 | Are recordings retained? | No. Audio is deleted as soon as the analysis finishes (`RETAIN_AUDIO=false`); temp folders are removed on success and on failure, and a janitor clears anything older than an hour. A preview ("Generate spectrogram") keeps its upload for `PREVIEW_TTL_MINUTES` so an analysis can reuse it; once an analysis takes it, the preview's copy is deleted. Results, raw detections and the spectrogram image stay until the user deletes the analysis. | Field audio can capture voices. Keeping nothing by default is the only choice that needs no consent process. | A pilot agreement covers retention and access. |
| 2 | Anonymous, magic link, or invited? | Single user, local, no auth. | The first pilot runs on a laptop or a private instance. Auth is only useful once results are stored for more than one person. | Before any shared hosted instance. |
| 3 | Max file size and duration | 20 MB in the browser, 50 MB and 10 minutes on the server, 1 second minimum. | BirdNET runs about 25 windows per second on 2 vCPU, so 10 minutes is roughly 10 seconds of inference; larger files belong in batch ingestion. | Batch ingestion or a GPU host. |
| 4 | BirdNET package, version, license | BirdNET GLOBAL 6K v2.4 TFLite (sha256 `55f3e405...`), weights taken from the pinned `birdnetlib==0.18.1` wheel, run with `ai-edge-litert`. | Pip-installable, pinned by hash, no network download at runtime, runs on Linux and Apple Silicon. The weights are CC BY-NC-SA 4.0: fine for a non-commercial pilot, a license from the BirdNET team is needed for paid use. | Any commercial pilot. |
| 5 | Raw detections in the normal UI? | No. The UI shows events; raw windows are in the JSON export and the Methods tab shows the counts. | Windows are an implementation detail and invite double counting. | Reviewers ask for window-level audit in the UI. |
| 6 | Slider recompute: client or server? | Server. The API stores every window above the 0.10 floor and `GET /analyses/{id}?threshold=x` rebuilds events, species and metrics with the same code that produced the original result. | One implementation of the science, so the slider can never disagree with the export. The response always states the threshold it used. | Offline or very large analyses where round trips hurt. |
| 7 | Speech and privacy detection | BirdNET's `Human vocal` label at 0.5 or above in any window sets `speech_detected` and adds a privacy note. Human sounds never count as species. | Cheap, already computed, and errs toward warning. It is a flag, not a redaction tool. | Before recordings from public places or near homes. |
| 8 | Pilot geography and species | Northeastern and Midwestern US (Ithaca farm pilot; historical Champaign data). The frog and insect label set is 17 anurans and 20 Orthoptera and cicadas from that range. | Matches the active pilot and the species BirdNET does not cover (cicadas, leopard frogs, Blanchard's cricket frog). | A new pilot region. |
| 9 | Using audio and corrections to improve models | Not allowed by default. Nothing leaves the machine; there is no telemetry. | Requires explicit consent terms first. | A signed data agreement. |

## Science and product rules

* **Events, not individuals.** Consolidated events are the unit of every metric. Words like individuals, population and abundance do not appear in the UI or exports.
* **Merge gap 1.0 s**, configurable, recorded in every result. Windows exactly one gap apart merge.
* **Ingestion floor 0.10, default decision threshold 0.60.** The floor is the lowest threshold the slider can reach; anything lower would need a re-run, and the API says so instead of silently clamping.
* **Metrics exclude**: human, noise, engine, siren, dog and environmental labels; reviewer-rejected events; birds flagged unlikely for the place and week. All are still listed.
* **Range and season filter only for birds.** BirdNET's meta model was trained on eBird data and returns about 0.00002 for every frog and insect label (for example Spring Peeper in Ithaca in May). Applying it to non-birds would delete every frog and insect detection, so those stay `unknown`.
* **No fallback location.** Missing coordinates mean no map and no range check, and the analysis says so.
* **Combined mode** gives each adapter its own model run id and never deduplicates across runs. If two runs name the same species, the species table merges them by scientific name while each event keeps its run id.
* **Experimental models** are off by default, need an environment flag on the server and another in the frontend, and carry a badge and a warning in every result.

## Engineering choices and deviations from the spec's suggestions

* **Package name `thicket`** instead of `app`, so `ml/` scripts can import the same BirdNET runtime and audio decoder without a generic top-level name.
* **Embeddings without a second model.** The stock BirdNET TFLite graph only outputs logits, and with the XNNPACK delegate intermediate tensors cannot be read. Thicket rewrites the flatbuffer once so the graph also outputs the 1024-d `GLOBAL_AVG_POOL` tensor, caches it by source hash, and keeps XNNPACK (about 10 times faster than preserving all tensors).
* **SQLite and local disk** behind repository and storage interfaces, with Postgres-compatible types. Events are derived on read, so the database only stores raw windows, reviews and provenance.
* **Deterministic event ids** (hash of analysis, run, species, start, end) so a review sticks to an event across threshold changes when its extent does not change.
* **Tailwind v3, Vite, React 18.** One frontend root, one lockfile. Vitest 3 because Vitest 4 broke npm's installer here; Playwright pinned to the Chromium build available in CI images.
* **Hand-built SVG charts** instead of a chart library, so they theme cleanly, stay small and carry `title`/`desc` and a hidden data table for screen readers.
* **Hash routing** so the static demo works on GitHub Pages without server rewrites.
* **Spectrogram level reference from 1 kHz and up.** In many field recordings most energy is distant rumble below 200 Hz; using the whole band as the reference pushed calls into the dark end of the colormap.

## Things that happened during the build

* The build sandbox could not reach iNaturalist, Zenodo, xeno-canto or Hugging Face, and pushing to GitHub from it was not possible. The iNaturalist dataset and frog and insect training therefore live in a GitHub Actions workflow that runs once the repo is on GitHub.
* A soundscape QC head was trained instead, on ESC-50, because it is reachable, has proper source-disjoint folds, and fills a real gap in the spec (audio QC).
