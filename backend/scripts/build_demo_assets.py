"""Build the static demo used by the GitHub Pages / artifact build of the frontend.

Runs real analyses through the same API code path (FastAPI TestClient, no
network server), then writes one Analysis JSON per decision threshold from
0.10 to 0.95, the spectrogram PNG and an MP3 preview into
``frontend/public/demo/<id>/`` plus ``frontend/public/demo/index.json``.

Usage::

    python backend/scripts/build_demo_assets.py \
        --soundscape /path/to/BirdNET-Analyzer/birdnet_analyzer/example/soundscape.wav \
        --esc50 /path/to/ESC-50   # optional: repo checkout with audio/ and meta/

Only openly licensed inputs are used, and no location is invented: demos
without real coordinates have none, so the Map tab stays hidden.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from thicket.config import Settings
from thicket.main import create_app

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "frontend" / "public" / "demo"
THRESHOLDS = [round(0.10 + 0.05 * i, 2) for i in range(18)]


def _mp3(src: Path, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-b:a", "96k", str(dst)],
        check=True,
    )


def _analyze(client: TestClient, audio: Path, demo_id: str, form: dict[str, str]) -> None:
    out = OUT / demo_id
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with open(audio, "rb") as f:
        r = client.post(
            "/api/v1/analyses?wait=true",
            files={"file": (audio.name, f, "audio/wav")},
            data={"models": '["birdnet"]', "threshold": "0.60", **form},
        )
    r.raise_for_status()
    analysis = r.json()
    aid = analysis["id"]
    for t in THRESHOLDS:
        a = client.get(f"/api/v1/analyses/{aid}", params={"threshold": f"{t:.2f}"})
        a.raise_for_status()
        (out / f"threshold-{t:.2f}.json").write_text(json.dumps(a.json(), indent=1))
    png = client.get(f"/api/v1/analyses/{aid}/spectrogram.png")
    png.raise_for_status()
    (out / "spectrogram.png").write_bytes(png.content)
    _mp3(audio, out / "audio.mp3")
    at60 = json.loads((out / "threshold-0.60.json").read_text())
    print(
        f"[demo] {demo_id}: {len(at60['events'])} events, richness "
        f"{at60['metrics']['species_richness']}, quality {at60['quality']['status']}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--soundscape", type=Path, required=True)
    ap.add_argument("--esc50", type=Path, default=None)
    args = ap.parse_args()

    entries = []
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            thicket_data_dir=Path(tmp) / "data",
            environment="test",
            rate_limit_per_minute=10_000,
            log_level="WARNING",
        )
        with TestClient(create_app(settings)) as client:
            # Wait for BirdNET to finish loading in the background.
            for _ in range(600):
                if client.get("/api/v1/models").json()["models"][0]["status"] == "ready":
                    break
                import time

                time.sleep(0.2)

            _analyze(client, args.soundscape, "birdnet-example-soundscape",
                     {"site_name": "BirdNET example soundscape"})
            entries.append({
                "id": "birdnet-example-soundscape",
                "title": "Two-minute soundscape",
                "description": (
                    "The example recording shipped with BirdNET-Analyzer: a two-minute "
                    "morning soundscape with several songbirds. No location or date is "
                    "attached, so the range and season check and the map are skipped."
                ),
                "attribution": "Example soundscape from BirdNET-Analyzer (github.com/birdnet-team/BirdNET-Analyzer).",
                "license": "Distributed with the MIT-licensed BirdNET-Analyzer repository",
            })

            if args.esc50:
                meta = list(csv.DictReader(open(args.esc50 / "meta" / "esc50.csv")))
                picks = [r for r in meta if r["category"] == "rain"][:3] + [
                    r for r in meta if r["category"] == "wind"][:3]
                stitched = Path(tmp) / "rain_wind.wav"
                listing = Path(tmp) / "list.txt"
                listing.write_text("".join(f"file '{args.esc50 / 'audio' / r['filename']}'\n" for r in picks))
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i",
                                str(listing), "-ac", "1", "-ar", "48000", str(stitched)], check=True)
                _analyze(client, stitched, "esc50-rain-and-wind", {"site_name": "Stitched test clip"})
                sources = ", ".join(f"freesound.org/s/{r['src_file']}" for r in picks)
                entries.append({
                    "id": "esc50-rain-and-wind",
                    "title": "Rain and wind (test clip)",
                    "description": (
                        "Thirty seconds stitched from six ESC-50 clips, three of rain and three "
                        "of wind, in file order. It is not a field recording. It shows the "
                        "audio quality checks and what a result with no species looks like."
                    ),
                    "attribution": f"ESC-50 (Piczak 2015), clips from {sources}.",
                    "license": "CC BY-NC 3.0",
                })

    (OUT / "index.json").write_text(json.dumps({"analyses": entries}, indent=1))
    print(f"[demo] wrote {OUT / 'index.json'}")


if __name__ == "__main__":
    main()
