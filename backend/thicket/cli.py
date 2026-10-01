"""Command line using the same services as the API (no server).

Examples::

    python -m thicket.cli analyze recording.wav --threshold 0.6 \\
        --lat 42.44 --lon -76.50 --date 2026-05-14T06:30:00 --timezone America/New_York \\
        --json out.json --csv out.csv

    python -m thicket.cli ingest /media/SD_CARD --site "North pasture" \\
        --recorder "AudioMoth 1" --timezone America/New_York

    python -m thicket.cli nightly

    python -m thicket.cli adopt-local --org org_...    (or --email owner@farm.example)

``analyze`` uses a throwaway in-memory database unless ``--data-dir`` is
given. ``ingest``, ``nightly`` and ``adopt-local`` work on the configured data
dir (``THICKET_DATA_DIR`` or ``--data-dir``); ``ingest`` writes to the local
workspace unless ``--org`` names an organization. ``adopt-local`` moves
everything in the local workspace into an organization (for a server that
switches sign-in on). Exit codes: 0 success, 2 typed error (message on
stderr), 1 unexpected error.
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

    i = sub.add_parser(
        "ingest", help="Batch-ingest a folder of recordings (into the local workspace by default)"
    )
    i.add_argument("dir", type=Path, help="Folder with audio, zips and sidecar files (recursive)")
    i.add_argument(
        "--org", default=None, help="Organization id to ingest into (default: the local workspace)"
    )
    i.add_argument("--site", required=True, help="Site name (created if it does not exist)")
    i.add_argument("--recorder", default=None, help="Recorder label (created if it does not exist)")
    i.add_argument(
        "--make",
        default=None,
        choices=["audiomoth", "song_meter", "phone", "handheld", "other"],
        help="Recorder make when --recorder creates a new recorder",
    )
    i.add_argument("--timezone", default="UTC", help="IANA time zone of the recorder clock")
    i.add_argument("--models", default="birdnet", help="Comma list of model keys")
    i.add_argument("--threshold", type=float, default=None, help="Decision threshold")
    i.add_argument(
        "--data-dir", type=Path, default=None, help="Data dir (default THICKET_DATA_DIR)"
    )
    i.add_argument("--verbose", action="store_true", help="Show logs")

    n = sub.add_parser(
        "nightly", help="Run the nightly jobs once (rollups, gaps, digests, cleanup)"
    )
    n.add_argument(
        "--data-dir", type=Path, default=None, help="Data dir (default THICKET_DATA_DIR)"
    )
    n.add_argument("--verbose", action="store_true", help="Show logs")

    ad = sub.add_parser(
        "adopt-local",
        help="Move everything in the local workspace into an organization (after enabling sign-in)",
    )
    target = ad.add_mutually_exclusive_group(required=True)
    target.add_argument("--org", default=None, help="Organization id that receives the data")
    target.add_argument(
        "--email", default=None, help="Use the first organization this user owns (oldest first)"
    )
    ad.add_argument(
        "--data-dir", type=Path, default=None, help="Data dir (default THICKET_DATA_DIR)"
    )
    ad.add_argument("--verbose", action="store_true", help="Show logs")
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


def _platform_settings(args: argparse.Namespace) -> Settings | None:
    overrides: dict = {"log_format": "text", "log_level": "INFO" if args.verbose else "WARNING"}
    if args.data_dir is not None:
        overrides["thicket_data_dir"] = args.data_dir
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        first = exc.errors()[0]
        print(f"error [invalid_parameter]: {first.get('loc')}: {first.get('msg')}", file=sys.stderr)
        return None


def _table(rows: list[list[str]]) -> str:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out = []
    for n, r in enumerate(rows):
        out.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip())
        if n == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)


def ingest(args: argparse.Namespace, container: Container | None = None) -> int:
    """Batch ingestion from a folder through the same ingest service as the API."""
    from thicket.ids import LOCAL_USER_ID
    from thicket.services.ingest import stage_local_files

    own = container is None
    if container is None:
        settings = _platform_settings(args)
        if settings is None:
            return 2
        configure_logging(settings.log_level, settings.log_format)
        container = Container(settings)
    c = container
    try:
        if not args.dir.is_dir():
            raise ThicketError(ErrorCode.invalid_parameter, f"Folder not found: {args.dir}")
        if own:
            c.startup(background=False)
        org = _org_or_local(c, getattr(args, "org", None))
        site = c.platform.find_site_by_name(org, args.site)
        if site is None:
            site = c.platform.create_site(
                org, {"name": args.site.strip()[:120], "auto_created": False}
            )
        recorder_id = None
        if args.recorder:
            rec = c.platform.find_recorder(org, label=args.recorder)
            if rec is None:
                rec = c.platform.create_recorder(
                    org, {"label": args.recorder.strip()[:120], "make": args.make or "other"}
                )
            recorder_id = rec.id
        files = sorted(p for p in args.dir.rglob("*") if p.is_file() and not p.name.startswith("."))
        if len(files) > c.settings.max_batch_files:
            raise ThicketError(
                ErrorCode.invalid_parameter,
                f"The folder has {len(files)} files; the batch limit is {c.settings.max_batch_files}.",
            )
        fields = {
            "site_id": [site.id],
            "timezone": [args.timezone],
            "models": [args.models],
        }
        if recorder_id:
            fields["recorder_id"] = [recorder_id]
        if args.threshold is not None:
            fields["threshold"] = [str(args.threshold)]
        req = c.ingest.parse_request(org, fields, c.registry, LOCAL_USER_ID)
        staging = c.storage.job_tmp(new_id("job"))
        staging.mkdir(parents=True)
        staged = stage_local_files(files, staging)
        if not staged:
            raise ThicketError(
                ErrorCode.invalid_parameter,
                "No audio, zip or sidecar files were found in the folder.",
            )
        job = c.ingest.start(req, staged, staging, sync=True)
        found = c.platform.get_job(job.id)
        assert found is not None
        model = c.ingest.job_model(*found)
        rows = [["file", "status", "captured_at", "source", "species", "events", "note"]]
        for item in model.items:
            species = events = ""
            if item.recording_id:
                st = c.platform.get_recording_stats(item.recording_id)
                if st is not None:
                    species, events = str(st.richness), str(st.events)
            rows.append(
                [
                    item.filename,
                    item.status.value,
                    item.captured_at.isoformat(timespec="seconds") if item.captured_at else "",
                    item.captured_at_source.value,
                    species,
                    events,
                    (item.error_message or "")[:60],
                ]
            )
        print(_table(rows))
        print(
            f"\njob {model.id}: {model.done} completed, {model.failed} failed, "
            f"{model.skipped} skipped of {model.total}"
            + (
                f"; sidecars read: {', '.join(model.sidecars_parsed)}"
                if model.sidecars_parsed
                else ""
            )
        )
        return 0 if model.failed == 0 else 2
    except ThicketError as exc:
        print(f"error [{exc.code.value}]: {exc.message}", file=sys.stderr)
        return 2
    finally:
        if own:
            c.shutdown()


def _org_or_local(c: Container, org_id: str | None) -> str:
    from thicket.ids import LOCAL_ORG_ID, is_valid_id

    if not org_id:
        return LOCAL_ORG_ID
    if not is_valid_id(org_id, "org") or c.platform.get_org(org_id) is None:
        raise ThicketError(ErrorCode.not_found, f"No organization with id {org_id!r}.")
    return org_id


def adopt_local(args: argparse.Namespace, container: Container | None = None) -> int:
    """Move the local workspace's data into an organization and rebuild its rollups."""
    from thicket.ids import LOCAL_ORG_ID

    own = container is None
    if container is None:
        settings = _platform_settings(args)
        if settings is None:
            return 2
        configure_logging(settings.log_level, settings.log_format)
        container = Container(settings)
    c = container
    try:
        if own:
            c.startup(background=False)
        if args.org:
            target = _org_or_local(c, args.org)
            if target == LOCAL_ORG_ID:
                raise ThicketError(
                    ErrorCode.invalid_parameter,
                    "--org must name an organization, not the local one.",
                )
        else:
            user = c.platform.get_user_by_email(args.email or "")
            if user is None:
                raise ThicketError(ErrorCode.not_found, f"No user signed in as {args.email}.")
            owned = [
                o.id
                for o, role in c.platform.orgs_for_user(user.id)
                if role == "owner" and o.id != LOCAL_ORG_ID
            ]
            if not owned:
                raise ThicketError(
                    ErrorCode.not_found,
                    f"{args.email} owns no organization yet. Sign in and create one first.",
                )
            target = owned[0]
        org = c.platform.get_org(target)
        moved = c.services.adopt_local(target, c.rollups)
        print(f"Moved the local workspace into {org.name if org else target} ({target}):")
        for key, n in moved.items():
            print(f"  {key.replace('_', ' ')}: {n}")
        return 0
    except ThicketError as exc:
        print(f"error [{exc.code.value}]: {exc.message}", file=sys.stderr)
        return 2
    finally:
        if own:
            c.shutdown()


def nightly(args: argparse.Namespace, container: Container | None = None) -> int:
    own = container is None
    if container is None:
        settings = _platform_settings(args)
        if settings is None:
            return 2
        configure_logging(settings.log_level, settings.log_format)
        container = Container(settings)
    try:
        if own:
            container.startup(background=False)
        summary = container.nightly.run_once()
        for k, v in summary.items():
            print(f"{k}: {v}")
        return 1 if any(v == "failed" for v in summary.values()) else 0
    finally:
        if own:
            container.shutdown()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "analyze":
        return analyze(args)
    if args.command == "ingest":
        return ingest(args)
    if args.command == "nightly":
        return nightly(args)
    if args.command == "adopt-local":
        return adopt_local(args)
    return 1  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
