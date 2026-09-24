"""Command-line analysis using the same service as the API (no server).

Example::

    python -m thicket.cli analyze recording.wav --threshold 0.6 \\
        --lat 42.44 --lon -76.50 --date 2026-05-14T06:30:00 --timezone America/New_York \\
        --json out.json --csv out.csv

By default results live in a throwaway in-memory database and temp folder;
pass ``--data-dir`` to keep them (and see them in the API's history).
Exit codes: 0 success, 2 typed error (message on stderr), 1 unexpected error.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from pydantic import ValidationError

from thicket.api.schemas import Analysis, AnalysisStatus, ErrorCode
from thicket.config import Settings
from thicket.container import Container
from thicket.errors import ThicketError
from thicket.ids import new_id
from thicket.logging_setup import configure_logging
from thicket.services.exports import csv_text, json_export
from thicket.services.intake import intake_local_file
from thicket.services.params import parse_analysis_params


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m thicket.cli", description="Thicket command line")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyze", help="Analyze one recording")
    a.add_argument("file", type=Path)
    a.add_argument(
        "--threshold", type=float, default=None, help="Decision threshold (default 0.60)"
    )
    a.add_argument("--lat", type=float, default=None, help="Latitude, -90 to 90")
    a.add_argument("--lon", type=float, default=None, help="Longitude, -180 to 180")
    a.add_argument("--date", default=None, help="Recording date or date-time, ISO 8601")
    a.add_argument("--timezone", default=None, help="IANA time zone, e.g. America/New_York")
    a.add_argument("--site", default=None, help="Site name")
    a.add_argument("--models", default="birdnet", help="Comma list of model keys (default birdnet)")
    a.add_argument("--hop", type=float, default=None, help="Window hop in seconds (3.0 or 1.5)")
    a.add_argument("--json", type=Path, default=None, help="Write the JSON export here")
    a.add_argument("--csv", type=Path, default=None, help="Write the CSV export here")
    a.add_argument("--data-dir", type=Path, default=None, help="Persist results in this data dir")
    a.add_argument("--quiet", action="store_true", help="Only print errors")
    a.add_argument("--verbose", action="store_true", help="Show logs")
    return p


def _summary(a: Analysis) -> str:
    lines: list[str] = []
    run = ", ".join(r.model for r in a.model_runs)
    lines.append(
        f"Thicket {a.software_version} | {run} | threshold {a.settings.decision_threshold:.2f}"
    )
    if a.recording:
        r = a.recording
        lines.append(
            f"Recording: {r.filename}, {r.duration_seconds:.1f} s, {r.sample_rate_hz} Hz, "
            f"{r.channels} ch"
        )
    if a.quality:
        lines.append(f"Quality: {a.quality.status.value} (score {a.quality.score:.2f})")
        lines.extend(f"  - {w}" for w in a.quality.warnings)
    lines.append(f"Species ({len(a.species)}):")
    for s in a.species:
        lines.append(
            f"  {s.common_name} ({s.scientific_name}) [{s.taxon.value}] events {s.detection_event_count}, "
            f"max {s.max_confidence:.2f}, first at {s.first_detection_seconds:.1f} s"
        )
    if not a.species:
        lines.append("  No detections above the threshold.")
    if a.metrics:
        m = a.metrics
        lines.append(
            f"Metrics: richness {m.species_richness}, Shannon {m.shannon_index:.4f}, "
            f"Pielou {m.pielou_evenness:.4f}, Gini-Simpson {m.simpson_diversity:.4f}, "
            f"events {m.total_detection_events} ({m.events_per_minute:.2f} per minute)"
        )
    lines.extend(f"Note: {w}" for w in a.warnings)
    return "\n".join(lines)


def analyze(args: argparse.Namespace) -> int:
    overrides: dict = {"log_format": "text", "log_level": "INFO" if args.verbose else "WARNING"}
    tmp_root: Path | None = None
    if args.data_dir is None:
        tmp_root = Path(tempfile.mkdtemp(prefix="thicket-cli-"))
        overrides.update(thicket_data_dir=tmp_root, database_url="sqlite://")
    else:
        overrides["thicket_data_dir"] = args.data_dir
    if args.hop is not None:
        overrides["hop_seconds"] = args.hop
    try:
        settings = Settings(**overrides)
    except ValidationError as exc:
        first = exc.errors()[0]
        print(f"error [invalid_parameter]: {first.get('loc')}: {first.get('msg')}", file=sys.stderr)
        return 2
    configure_logging(settings.log_level, settings.log_format)
    container = Container(settings)
    try:
        if not args.file.is_file():
            raise ThicketError(ErrorCode.invalid_parameter, f"File not found: {args.file}")
        container.startup(background=False)
        fields = {
            "models": args.models,
            "threshold": "" if args.threshold is None else str(args.threshold),
            "latitude": "" if args.lat is None else str(args.lat),
            "longitude": "" if args.lon is None else str(args.lon),
            "captured_at": args.date or "",
            "timezone": args.timezone or "",
            "site_name": args.site or "",
        }
        params = parse_analysis_params(fields, settings, container.registry)
        analysis_id = new_id("ana")
        tmp = container.storage.analysis_tmp(analysis_id)
        tmp.mkdir(parents=True)
        try:
            upload = intake_local_file(args.file, tmp, settings.max_upload_bytes)
            job = container.analysis.create(analysis_id, upload, params, tmp)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        container.analysis.run_sync(job)
        result = container.analysis.view(analysis_id)
        if result.status != AnalysisStatus.failed:
            if args.json:
                args.json.write_text(
                    json.dumps(json_export(result).model_dump(mode="json"), indent=2) + "\n",
                    encoding="utf-8",
                )
            if args.csv:
                args.csv.write_text(csv_text(result), encoding="utf-8")
            if not args.quiet:
                print(_summary(result))
            return 0
        code = result.error_code.value if result.error_code else "internal_error"
        print(f"error [{code}]: {result.error_message}", file=sys.stderr)
        return 2
    except ThicketError as exc:
        print(f"error [{exc.code.value}]: {exc.message}", file=sys.stderr)
        return 2
    finally:
        container.shutdown()
        if tmp_root is not None:
            shutil.rmtree(tmp_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "analyze":
        return analyze(args)
    return 1  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
