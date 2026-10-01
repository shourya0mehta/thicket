"""Batch ingestion: many files (and zips) in, one Recording and Analysis each.

Flow
----
1. :func:`parse_multipart_batch` streams the multipart body into a job
   staging folder with the same caps as single uploads (per-file size), plus
   ``MAX_BATCH_FILES`` and ``MAX_BATCH_BYTES`` for the whole batch.
2. Zips are expanded by :func:`expand_zip` with no path traversal, the same
   count and byte caps (checked against the declared size and again while
   streaming, so a zip bomb stops at the cap), and only audio or sidecar
   names (``*_Summary.txt``, ``CONFIG.TXT``). There is no compression-ratio
   rule: silent field recordings legitimately compress a thousandfold.
3. :meth:`IngestService.start` records a ``BatchJob`` with one item per audio
   file and hands the rest to the worker pool's batch lane, so the HTTP
   request returns at once with 202.
4. :meth:`IngestService.run_job` parses sidecars, then for each audio file
   (natural name order) resolves the timestamp, telemetry, recorder and
   deployment, copies the file through the normal intake checks and creates
   the analysis with the *existing* :class:`AnalysisService` (batch lane).
5. When each analysis finishes, :meth:`on_analysis_finished` updates the
   item and the job counters; once the job settles the clock checks run.

Timestamp order: file name pattern, then file metadata (AudioMoth WAV
comment or GUANO), then the browser's ``last_modified``, then
``captured_at_override``. ``captured_at_source`` records which one won.
File-name clocks: AudioMoth names are UTC, Song Meter names are the
recorder's local clock (the batch ``timezone``); a recorder registered as one
make or the other overrides the pattern's guess.
"""

from __future__ import annotations

import codecs
import csv
import logging
import secrets
import shutil
import threading
import zipfile
import zlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header

from thicket.api.platform_schemas import BatchItem, BatchJob, Telemetry
from thicket.api.schemas import ErrorCode
from thicket.config import Settings
from thicket.errors import ThicketError, invalid_parameter
from thicket.ids import new_id
from thicket.persistence.db import BatchItemRow, BatchJobRow, DeploymentRow, RecorderRow, SiteRow
from thicket.persistence.platform_repositories import PlatformRepository
from thicket.persistence.repositories import Repository
from thicket.services.analysis import AnalysisService
from thicket.services.filenames import filename_sort_key, parse_filename_timestamp
from thicket.services.intake import (
    ALLOWED_EXTENSIONS,
    MAX_FIELD_BYTES,
    MAX_FIELDS,
    file_too_large,
    intake_local_file,
    sanitize_filename,
)
from thicket.services.params import AnalysisParams, parse_captured_at, parse_models, parse_timezone
from thicket.services.results import validate_threshold
from thicket.services.storage import Storage
from thicket.services.telemetry import (
    AudioMothConfig,
    SummaryRow,
    is_audiomoth_config_name,
    is_song_meter_summary_name,
    match_summary_row,
    parse_audiomoth_comment,
    parse_audiomoth_config,
    parse_guano,
    parse_song_meter_summary,
    read_wav_metadata,
)

log = logging.getLogger(__name__)

BATCH_FIELDS = frozenset(
    {
        "files",
        "files[]",
        "file",
        "site_id",
        "deployment_id",
        "recorder_id",
        "timezone",
        "models",
        "threshold",
        "last_modified",
        "last_modified[]",
        "captured_at_override",
    }
)
SIDECAR_EXTENSIONS = {".txt"}
ZIP_EXTENSIONS = {".zip"}
CHUNK = 256 * 1024
ZIP_SKIP_PREFIXES = ("__MACOSX/",)


@dataclass
class StagedFile:
    path: Path
    filename: str
    byte_size: int
    last_modified_ms: int | None = None
    from_zip: str | None = None

    @property
    def extension(self) -> str:
        return Path(self.filename).suffix.lower()

    @property
    def kind(self) -> str:
        ext = self.extension
        if ext in ALLOWED_EXTENSIONS:
            return "audio"
        if ext in ZIP_EXTENSIONS:
            return "zip"
        if is_song_meter_summary_name(self.filename):
            return "summary"
        if is_audiomoth_config_name(self.filename):
            return "config"
        return "other"


@dataclass
class BatchRequest:
    organization_id: str
    site_id: str | None
    deployment_id: str | None
    recorder_id: str | None
    timezone: str
    models: list[str]
    threshold: float
    captured_at_override: datetime | None
    created_by: str | None = None

    def settings(self) -> dict:
        return {
            "models": list(self.models),
            "threshold": self.threshold,
            "timezone": self.timezone,
            "site_id": self.site_id,
            "deployment_id": self.deployment_id,
            "recorder_id": self.recorder_id,
            "captured_at_override": self.captured_at_override.isoformat()
            if self.captured_at_override
            else None,
            "timestamp_order": [
                "filename",
                "file_metadata",
                "browser_last_modified",
                "captured_at_override",
            ],
        }


# ------------------------------------------------------------ multipart


def _accepts(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    if ext in ALLOWED_EXTENSIONS or ext in ZIP_EXTENSIONS:
        return True
    return is_song_meter_summary_name(filename) or is_audiomoth_config_name(filename)


class _Budget:
    def __init__(self, max_total: int, max_files: int) -> None:
        self.max_total = max_total
        self.max_files = max_files
        self.total = 0
        self.files = 0

    def add_file(self) -> None:
        self.files += 1
        if self.files > self.max_files:
            raise invalid_parameter(
                f"A batch may contain at most {self.max_files} files (zip contents included).",
                field="files",
            )

    def add_bytes(self, n: int) -> None:
        self.total += n
        if self.total > self.max_total:
            raise ThicketError(
                ErrorCode.file_too_large,
                f"The batch is larger than the {self.max_total / (1024**3):.1f} GiB limit.",
                detail={"max_batch_bytes": self.max_total},
            )


class _Sink:
    def __init__(self, dest_dir: Path, filename: str, per_file_max: int, budget: _Budget) -> None:
        self.filename = sanitize_filename(filename)
        if not _accepts(self.filename):
            raise ThicketError(
                ErrorCode.unsupported_file_type,
                f"'{self.filename[:60]}' is not an audio file, a zip, a Song Meter *_Summary.txt "
                "or an AudioMoth CONFIG.TXT.",
            )
        ext = Path(self.filename).suffix.lower()
        self.per_file_max = per_file_max if ext in ALLOWED_EXTENSIONS else budget.max_total
        self.budget = budget
        self.path = dest_dir / f"{secrets.token_hex(8)}{ext}"
        self._fh = open(self.path, "xb")  # noqa: SIM115
        self.size = 0

    def write(self, data: bytes) -> None:
        if not data:
            return
        self.size += len(data)
        if self.size > self.per_file_max:
            self.abort()
            raise file_too_large(self.per_file_max)
        self.budget.add_bytes(len(data))
        self._fh.write(data)

    def finish(self) -> StagedFile:
        self._fh.close()
        return StagedFile(path=self.path, filename=self.filename, byte_size=self.size)

    def abort(self) -> None:
        try:
            self._fh.close()
        finally:
            self.path.unlink(missing_ok=True)


class _BatchForm:
    def __init__(self, dest_dir: Path, per_file_max: int, budget: _Budget, charset: str) -> None:
        self.dest_dir = dest_dir
        self.per_file_max = per_file_max
        self.budget = budget
        self.charset = charset
        self.fields: dict[str, list[str]] = {}
        self.files: list[StagedFile] = []
        self._sink: _Sink | None = None
        self._name = ""
        self._buf = bytearray()
        self._hname = b""
        self._hvalue = b""
        self._disposition = b""

    def on_part_begin(self) -> None:
        self._name, self._buf, self._disposition, self._sink = "", bytearray(), b"", None

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._hname += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._hvalue += data[start:end]

    def on_header_end(self) -> None:
        if self._hname.lower() == b"content-disposition":
            self._disposition = self._hvalue
        self._hname = b""
        self._hvalue = b""

    def on_headers_finished(self) -> None:
        _, options = parse_options_header(self._disposition)
        raw = options.get(b"name")
        if raw is None:
            raise invalid_parameter("Malformed multipart body: a part has no name.")
        self._name = raw.decode(self.charset, errors="replace")
        if self._name not in BATCH_FIELDS:
            raise invalid_parameter(
                f"Unknown form field '{self._name[:40]}'.", field=self._name[:40]
            )
        if b"filename" in options:
            if self._name not in ("files", "files[]", "file"):
                raise invalid_parameter("Only the 'files' field may carry files.", field=self._name)
            self.budget.add_file()
            filename = options[b"filename"].decode(self.charset, errors="replace")
            self._sink = _Sink(self.dest_dir, filename, self.per_file_max, self.budget)
        else:
            if self._name in ("files", "files[]", "file"):
                raise invalid_parameter("The 'files' field must carry files.", field="files")
            if sum(len(v) for v in self.fields.values()) >= MAX_FIELDS * 8:
                raise invalid_parameter("Too many form fields.")

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        if self._sink is not None:
            self._sink.write(chunk)
        else:
            if len(self._buf) + len(chunk) > MAX_FIELD_BYTES:
                raise invalid_parameter(f"Form field '{self._name}' is too long.", field=self._name)
            self._buf.extend(chunk)

    def on_part_end(self) -> None:
        if self._sink is not None:
            self.files.append(self._sink.finish())
            self._sink = None
        else:
            key = self._name.removesuffix("[]")
            self.fields.setdefault(key, []).append(self._buf.decode(self.charset, errors="replace"))

    def abort(self) -> None:
        if self._sink is not None:
            self._sink.abort()
            self._sink = None
        for f in self.files:
            f.path.unlink(missing_ok=True)


async def parse_multipart_batch(
    content_type: str | None,
    stream: AsyncIterator[bytes],
    dest_dir: Path,
    *,
    per_file_max: int,
    max_total_bytes: int,
    max_files: int,
) -> tuple[dict[str, list[str]], list[StagedFile]]:
    ctype, params = parse_options_header(content_type or "")
    if ctype != b"multipart/form-data" or b"boundary" not in params:
        raise invalid_parameter("Send the request as multipart/form-data.")
    charset = params.get(b"charset", b"utf-8").decode("latin-1")
    try:
        codecs.lookup(charset)
    except LookupError as exc:
        raise invalid_parameter("Unsupported charset in the Content-Type header.") from exc
    form = _BatchForm(dest_dir, per_file_max, _Budget(max_total_bytes, max_files), charset)
    parser = MultipartParser(
        params[b"boundary"],  # type: ignore[arg-type]
        {
            "on_part_begin": form.on_part_begin,
            "on_part_data": form.on_part_data,
            "on_part_end": form.on_part_end,
            "on_header_field": form.on_header_field,
            "on_header_value": form.on_header_value,
            "on_header_end": form.on_header_end,
            "on_headers_finished": form.on_headers_finished,
        },
    )
    try:
        async for chunk in stream:
            if chunk:
                parser.write(chunk)
        parser.finalize()
    except FormParserError as exc:
        form.abort()
        raise invalid_parameter("Malformed multipart body.") from exc
    except BaseException:
        form.abort()
        raise
    if form._sink is not None:
        form.abort()
        raise invalid_parameter("Malformed multipart body: a file part is incomplete.")
    stamps = form.fields.get("last_modified", [])
    if stamps and len(stamps) == len(form.files):
        for f, raw in zip(form.files, stamps, strict=True):
            try:
                ms = int(float(raw))
                if 0 < ms < 4_102_444_800_000:
                    f.last_modified_ms = ms
            except ValueError:
                continue
    return form.fields, form.files


# ------------------------------------------------------------------- zips


def expand_zip(
    staged: StagedFile,
    dest_dir: Path,
    *,
    per_file_max: int,
    max_total_bytes: int,
    max_files: int,
    already_files: int,
    already_bytes: int,
) -> tuple[list[StagedFile], list[str]]:
    """Extract audio and sidecar members safely. Returns (files, skipped names)."""
    out: list[StagedFile] = []
    skipped: list[str] = []
    files = already_files
    total = already_bytes
    try:
        zf = zipfile.ZipFile(staged.path)
    except zipfile.BadZipFile as exc:
        raise ThicketError(
            ErrorCode.unsupported_file_type, f"'{staged.filename}' is not a valid zip file."
        ) from exc
    with zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or name.endswith("/"):
                continue
            pure = PurePosixPath(name)
            if (
                pure.is_absolute()
                or ".." in pure.parts
                or name.startswith(ZIP_SKIP_PREFIXES)
                or pure.name.startswith(".")
            ):
                skipped.append(name[:120])
                continue
            display = sanitize_filename(pure.name)
            if not _accepts(display) or Path(display).suffix.lower() in ZIP_EXTENSIONS:
                skipped.append(name[:120])
                continue
            ext = Path(display).suffix.lower()
            cap = per_file_max if ext in ALLOWED_EXTENSIONS else max_total_bytes
            if info.file_size > cap:
                raise file_too_large(cap)
            files += 1
            if files > max_files:
                raise invalid_parameter(
                    f"A batch may contain at most {max_files} files (zip contents included).",
                    field="files",
                )
            path = dest_dir / f"{secrets.token_hex(8)}{ext}"
            written = 0
            try:
                with zf.open(info) as src, open(path, "xb") as dst:
                    while True:
                        block = src.read(CHUNK)
                        if not block:
                            break
                        written += len(block)
                        total += len(block)
                        if written > cap:
                            raise file_too_large(cap)
                        if total > max_total_bytes:
                            raise ThicketError(
                                ErrorCode.file_too_large,
                                f"The batch is larger than the {max_total_bytes / (1024**3):.1f} GiB limit.",
                                detail={"max_batch_bytes": max_total_bytes},
                            )
                        dst.write(block)
            except ThicketError:
                path.unlink(missing_ok=True)
                raise
            except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError):
                # Corrupt, encrypted or truncated member (zipfile also refuses to read
                # past the declared size): leave it out and say so.
                path.unlink(missing_ok=True)
                files -= 1
                total -= written
                skipped.append(name[:120])
                continue
            mtime_ms = None
            try:
                mtime_ms = int(datetime(*info.date_time, tzinfo=UTC).timestamp() * 1000)
            except (ValueError, TypeError):
                mtime_ms = None
            out.append(
                StagedFile(
                    path=path,
                    filename=display,
                    byte_size=written,
                    last_modified_ms=mtime_ms,
                    from_zip=staged.filename,
                )
            )
    return out, skipped


# -------------------------------------------------------------- resolution


@dataclass
class Resolved:
    captured_at: datetime | None
    source: str
    telemetry: dict
    latitude: float | None = None
    longitude: float | None = None
    device_id: str | None = None
    device_make: str | None = None
    notes: list[str] = field(default_factory=list)


def _localize(naive: datetime, tz: ZoneInfo) -> datetime:
    return naive.replace(tzinfo=tz)


def resolve_timestamp(
    staged: StagedFile,
    *,
    tz_name: str,
    recorder_make: str | None,
    summary_rows: Sequence[SummaryRow],
    config: AudioMothConfig | None,
    override: datetime | None,
) -> Resolved:
    """Apply the documented timestamp order and collect telemetry for one file."""
    tz = ZoneInfo(tz_name)
    captured: datetime | None = None
    source = "unknown"
    telemetry: dict = {"source": "none"}
    lat = lon = None
    device_id = None
    device_make = None

    parsed = parse_filename_timestamp(staged.filename)
    if parsed is not None:
        clock = parsed.clock
        if recorder_make == "song_meter":
            clock = "local"
        elif recorder_make == "audiomoth":
            clock = "utc"
        if clock == "utc" and config is not None and config.utc_offset_hours:
            # The recorder was configured with a fixed offset (CONFIG.TXT "Time zone: UTC-5").
            from datetime import timedelta, timezone

            captured = parsed.naive.replace(
                tzinfo=timezone(timedelta(hours=config.utc_offset_hours))
            )
        elif clock == "utc":
            captured = parsed.naive.replace(tzinfo=UTC)
        else:
            captured = _localize(parsed.naive, tz)
        source = "filename"
        if parsed.pattern == "song_meter":
            device_make = "song_meter"
            device_id = (parsed.prefix or "").upper() or None
        elif parsed.pattern == "audiomoth" and parsed.prefix:
            if (
                all(c in "0123456789ABCDEFabcdef" for c in parsed.prefix)
                and len(parsed.prefix) >= 8
            ):
                device_id = parsed.prefix.upper()
                device_make = "audiomoth"

    if staged.extension == ".wav":
        try:
            meta = read_wav_metadata(staged.path)
        except OSError:
            meta = None
        if meta is not None:
            am = parse_audiomoth_comment(meta.comment)
            if am is not None:
                if captured is None and am.captured_at is not None:
                    captured, source = am.captured_at, "file_metadata"
                telemetry = {
                    "battery_v": am.battery_v,
                    "temperature_c": am.temperature_c,
                    "gain": am.gain,
                    "device_id": am.device_id,
                    "source": "audiomoth_comment",
                }
                device_id = am.device_id or device_id
                device_make = "audiomoth"
            g = parse_guano(meta.guano)
            if g is not None:
                if captured is None and g.timestamp is not None:
                    ts = g.timestamp
                    captured = ts if ts.tzinfo else _localize(ts, tz)
                    source = "file_metadata"
                if g.latitude is not None and g.longitude is not None:
                    lat, lon = g.latitude, g.longitude
                if telemetry.get("source") == "none":
                    telemetry = {
                        "battery_v": None,
                        "temperature_c": g.temperature_c,
                        "gain": None,
                        "device_id": g.serial,
                        "source": "guano",
                    }
                elif telemetry.get("temperature_c") is None and g.temperature_c is not None:
                    telemetry["temperature_c"] = g.temperature_c
                device_id = device_id or g.serial
                if g.make and "audiomoth" in (g.model or g.make).lower():
                    device_make = device_make or "audiomoth"
                elif g.make and "wildlife" in g.make.lower():
                    device_make = device_make or "song_meter"

    if captured is None and staged.last_modified_ms:
        captured = datetime.fromtimestamp(staged.last_modified_ms / 1000.0, UTC)
        source = "browser_last_modified"
    if captured is None and override is not None:
        captured = override if override.tzinfo else _localize(override, tz)
        source = "user"

    if summary_rows and captured is not None:
        local_naive = captured.astimezone(tz).replace(tzinfo=None)
        row = match_summary_row(list(summary_rows), local_naive)
        if row is not None:
            if telemetry.get("source") == "none" or telemetry.get("battery_v") is None:
                telemetry = {
                    "battery_v": row.battery_v,
                    "temperature_c": row.temperature_c
                    if row.temperature_c is not None
                    else telemetry.get("temperature_c"),
                    "gain": telemetry.get("gain"),
                    "device_id": telemetry.get("device_id") or device_id,
                    "source": "song_meter_summary",
                }
            if lat is None and row.latitude is not None and row.longitude is not None:
                lat, lon = row.latitude, row.longitude
            device_make = device_make or "song_meter"

    if config is not None and telemetry.get("device_id") is None and config.device_id:
        telemetry["device_id"] = config.device_id
        if telemetry.get("gain") is None:
            telemetry["gain"] = config.gain
        device_id = device_id or config.device_id
        device_make = device_make or "audiomoth"

    return Resolved(
        captured_at=captured,
        source=source,
        telemetry=telemetry,
        latitude=lat,
        longitude=lon,
        device_id=device_id,
        device_make=device_make,
    )


# ------------------------------------------------------------------ service


class IngestService:
    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        repo: Repository,
        platform: PlatformRepository,
        analysis: AnalysisService,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.repo = repo
        self.platform = platform
        self.analysis = analysis
        self.alerts = None  # set by the container
        self._lock = threading.Lock()

    # -- request parsing ------------------------------------------------------
    def parse_request(
        self, org_id: str, fields: dict[str, list[str]], registry, created_by: str | None
    ) -> BatchRequest:  # type: ignore[no-untyped-def]
        def one(name: str) -> str | None:
            values = fields.get(name) or []
            return values[-1] if values else None

        models = parse_models(one("models"), registry.default_models())
        for key in models:
            registry.get(key)
        from thicket.services.params import _float, _ref

        threshold = validate_threshold(
            _float(one("threshold"), "threshold"),
            self.settings.raw_threshold,
            self.settings.default_decision_threshold,
        )
        tz = parse_timezone(one("timezone"))
        if tz is None:
            raise invalid_parameter(
                "timezone is required for batch uploads (the recorder's local time zone).",
                field="timezone",
            )

        site_id = _ref(one("site_id"), "site", "site_id")
        deployment_id = _ref(one("deployment_id"), "dep", "deployment_id")
        recorder_id = _ref(one("recorder_id"), "rcd", "recorder_id")
        site = self.platform.get_site(site_id) if site_id else None
        if site_id and (site is None or site.organization_id != org_id):
            raise invalid_parameter(
                "site_id does not belong to this organization.", field="site_id"
            )
        if deployment_id:
            dep = self.platform.get_deployment(deployment_id)
            if dep is None or dep.organization_id != org_id:
                raise invalid_parameter(
                    "deployment_id does not belong to this organization.", field="deployment_id"
                )
            site_id = site_id or dep.site_id
            recorder_id = recorder_id or dep.recorder_id
            if site_id != dep.site_id:
                raise invalid_parameter(
                    "deployment_id belongs to a different site than site_id.", field="deployment_id"
                )
        if recorder_id:
            rec = self.platform.get_recorder(recorder_id)
            if rec is None or rec.organization_id != org_id:
                raise invalid_parameter(
                    "recorder_id does not belong to this organization.", field="recorder_id"
                )
        if not site_id:
            raise invalid_parameter("site_id is required for batch uploads.", field="site_id")
        override = parse_captured_at(one("captured_at_override"), tz)
        return BatchRequest(
            organization_id=org_id,
            site_id=site_id,
            deployment_id=deployment_id,
            recorder_id=recorder_id,
            timezone=tz,
            models=models,
            threshold=threshold,
            captured_at_override=override,
            created_by=created_by,
        )

    # -- job lifecycle ----------------------------------------------------------
    def start(
        self,
        request: BatchRequest,
        staged: list[StagedFile],
        staging_dir: Path,
        *,
        sync: bool = False,
    ) -> BatchJobRow:
        """Expand zips, record the job and schedule (or run) the ingestion."""
        files, skipped = self._expand_all(staged, staging_dir)
        audio = sorted(
            (f for f in files if f.kind == "audio"), key=lambda f: filename_sort_key(f.filename)
        )
        sidecars = [f for f in files if f.kind in ("summary", "config")]
        settings = request.settings()
        settings["skipped_entries"] = skipped[:50]
        settings["zips"] = sorted({f.from_zip for f in files if f.from_zip})
        job = self.platform.create_job(
            request.organization_id,
            site_id=request.site_id,
            deployment_id=request.deployment_id,
            recorder_id=request.recorder_id,
            settings=settings,
            filenames=[f.filename for f in audio],
            created_by=request.created_by,
        )
        log.info(
            "batch job created",
            extra={
                "job_id": job.id,
                "org_id": request.organization_id,
                "files": len(audio),
                "sidecars": len(sidecars),
                "skipped": len(skipped),
            },
        )
        if not audio:
            self.platform.update_job(
                job.id, {"status": "completed", "completed_at": datetime.now(UTC)}
            )
            shutil.rmtree(staging_dir, ignore_errors=True)
            return job
        if sync:
            self.run_job(job.id, request, audio, sidecars, staging_dir, sync=True)
        else:
            self.analysis.submit_task(
                lambda: self.run_job(job.id, request, audio, sidecars, staging_dir), batch=True
            )
        return job

    def _expand_all(
        self, staged: list[StagedFile], staging_dir: Path
    ) -> tuple[list[StagedFile], list[str]]:
        files: list[StagedFile] = []
        skipped: list[str] = []
        total_bytes = sum(f.byte_size for f in staged if f.kind != "zip")
        for f in staged:
            if f.kind != "zip":
                files.append(f)
                continue
            inner, skip = expand_zip(
                f,
                staging_dir,
                per_file_max=self.settings.max_upload_bytes,
                max_total_bytes=self.settings.max_batch_bytes,
                max_files=self.settings.max_batch_files,
                already_files=len(files)
                + sum(1 for s in staged if s.kind != "zip" and s not in files),
                already_bytes=total_bytes,
            )
            total_bytes += sum(x.byte_size for x in inner)
            files.extend(inner)
            skipped.extend(skip)
            f.path.unlink(missing_ok=True)
        if len(files) > self.settings.max_batch_files:
            raise invalid_parameter(
                f"A batch may contain at most {self.settings.max_batch_files} files.", field="files"
            )
        return files, skipped

    def run_job(
        self,
        job_id: str,
        request: BatchRequest,
        audio: list[StagedFile],
        sidecars: list[StagedFile],
        staging_dir: Path,
        *,
        sync: bool = False,
    ) -> None:
        try:
            self.platform.update_job(job_id, {"status": "processing"})
            summary_rows, config, parsed_names = self._parse_sidecars(sidecars)
            self.platform.update_job(job_id, {"sidecars_parsed": parsed_names})
            site = self.platform.get_site(request.site_id) if request.site_id else None
            recorder = (
                self.platform.get_recorder(request.recorder_id) if request.recorder_id else None
            )
            recorder_cache: dict[str, RecorderRow] = {}
            deployment_cache: dict[tuple[str, str], DeploymentRow | None] = {}
            for position, f in enumerate(audio):
                self._ingest_one(
                    job_id,
                    position,
                    f,
                    request,
                    site,
                    recorder,
                    summary_rows,
                    config,
                    recorder_cache,
                    deployment_cache,
                    sync=sync,
                )
            self.platform.refresh_job_counts(job_id)
            self._settle_if_done(job_id)
        except Exception:  # noqa: BLE001 - mark the job, never crash the worker
            log.exception("batch job failed", extra={"job_id": job_id})
            self.platform.update_job(
                job_id, {"status": "failed", "completed_at": datetime.now(UTC)}
            )
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _parse_sidecars(
        self, sidecars: list[StagedFile]
    ) -> tuple[list[SummaryRow], AudioMothConfig | None, list[str]]:
        rows: list[SummaryRow] = []
        config: AudioMothConfig | None = None
        names: list[str] = []
        for f in sidecars:
            try:
                text = f.path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                if f.kind == "summary":
                    parsed = parse_song_meter_summary(text)
                    if parsed:
                        rows.extend(parsed)
                        names.append(f.filename)
                elif f.kind == "config":
                    cfg = parse_audiomoth_config(text)
                    if cfg is not None:
                        config = cfg
                        names.append(f.filename)
            except (csv.Error, ValueError, OverflowError):
                # An unreadable sidecar is left out; it must not fail the whole batch.
                log.warning("sidecar could not be parsed", extra={"kind": f.kind})
                continue
        return rows, config, names

    def _ingest_one(
        self,
        job_id: str,
        position: int,
        f: StagedFile,
        request: BatchRequest,
        site: SiteRow | None,
        recorder: RecorderRow | None,
        summary_rows: list[SummaryRow],
        config: AudioMothConfig | None,
        recorder_cache: dict[str, RecorderRow],
        deployment_cache: dict[tuple[str, str], DeploymentRow | None],
        *,
        sync: bool,
    ) -> None:
        self.platform.update_item(job_id, position, {"status": "processing"})
        try:
            resolved = resolve_timestamp(
                f,
                tz_name=request.timezone,
                recorder_make=recorder.make if recorder else None,
                summary_rows=summary_rows,
                config=config,
                override=request.captured_at_override,
            )
            rec = recorder or self._recorder_for_device(
                request.organization_id, resolved, recorder_cache, config
            )
            deployment_id = request.deployment_id
            if deployment_id is None and rec is not None and site is not None:
                deployment_id = self._deployment_for(
                    request.organization_id,
                    rec,
                    site,
                    resolved.captured_at,
                    deployment_cache,
                    config,
                )
            lat = (
                resolved.latitude
                if resolved.latitude is not None
                else (site.latitude if site else None)
            )
            lon = (
                resolved.longitude
                if resolved.longitude is not None
                else (site.longitude if site else None)
            )
            if (lat is None) != (lon is None):
                lat = lon = None
            telemetry = Telemetry.model_validate(resolved.telemetry).model_dump(mode="json")
            params = AnalysisParams(
                models=list(request.models),
                threshold=request.threshold,
                latitude=lat,
                longitude=lon,
                captured_at=resolved.captured_at,
                timezone=request.timezone,
                site_name=site.name if site else None,
                recorder_type=_recorder_type(rec, resolved),
                organization_id=request.organization_id,
                site_id=site.id if site else None,
                deployment_id=deployment_id,
                recorder_id=rec.id if rec else None,
                captured_at_source=resolved.source,
                telemetry=telemetry,
                source_filename=f.filename,
                batch_job_id=job_id,
            )
            analysis_id = new_id("ana")
            tmp = self.storage.analysis_tmp(analysis_id)
            tmp.mkdir(parents=True)
            try:
                upload = intake_local_file(f.path, tmp, self.settings.max_upload_bytes, f.filename)
                job = self.analysis.create(analysis_id, upload, params, tmp, batch=True)
            except BaseException:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
            self.platform.update_item(
                job_id,
                position,
                {
                    "status": "processing",
                    "analysis_id": analysis_id,
                    "recording_id": self.platform.recording_id_for_analysis(analysis_id),
                    "captured_at": resolved.captured_at,
                    "captured_at_source": resolved.source,
                    "telemetry": telemetry,
                },
            )
            f.path.unlink(missing_ok=True)
            if sync:
                self.analysis.run_sync(job)
            else:
                self.analysis.submit(job)
        except ThicketError as exc:
            f.path.unlink(missing_ok=True)
            self.platform.update_item(
                job_id,
                position,
                {"status": "failed", "error_code": exc.code.value, "error_message": exc.message},
            )
        except Exception:  # noqa: BLE001
            log.exception("batch item failed", extra={"job_id": job_id, "position": position})
            f.path.unlink(missing_ok=True)
            self.platform.update_item(
                job_id,
                position,
                {
                    "status": "failed",
                    "error_code": "internal_error",
                    "error_message": "This file could not be ingested because of an internal error.",
                },
            )

    def _recorder_for_device(
        self,
        org_id: str,
        resolved: Resolved,
        cache: dict[str, RecorderRow],
        config: AudioMothConfig | None,
    ) -> RecorderRow | None:
        device = resolved.device_id or (resolved.telemetry or {}).get("device_id")
        if not device:
            return None
        if device in cache:
            return cache[device]
        found = self.platform.find_recorder(org_id, serial=device)
        if found is None:
            make = resolved.device_make or "other"
            label = {"audiomoth": "AudioMoth", "song_meter": "Song Meter"}.get(make, "Recorder")
            found = self.platform.create_recorder(
                org_id,
                {
                    "label": f"{label} {device}"[:120],
                    "make": make,
                    "model": "AudioMoth" if make == "audiomoth" else None,
                    "serial": device,
                    "firmware": config.firmware if config else None,
                    "notes": "Created automatically from a batch upload.",
                },
            )
            log.info(
                "recorder created from device id", extra={"recorder_id": found.id, "org_id": org_id}
            )
        cache[device] = found
        return found

    def _deployment_for(
        self,
        org_id: str,
        recorder: RecorderRow,
        site: SiteRow,
        at: datetime | None,
        cache: dict[tuple[str, str], DeploymentRow | None],
        config: AudioMothConfig | None,
    ) -> str | None:
        key = (recorder.id, site.id)
        dep = self.platform.deployment_for(recorder.id, at, site_id=site.id)
        if dep is None and key in cache and cache[key] is not None:
            dep = cache[key]
        if dep is None:
            dep = self.platform.create_deployment(
                org_id,
                {
                    "recorder_id": recorder.id,
                    "site_id": site.id,
                    "started_at": at or datetime.now(UTC),
                    "expected_interval_minutes": config.expected_interval_minutes
                    if config
                    else None,
                    "expected_clip_seconds": config.record_seconds if config else None,
                    "gain_setting": config.gain if config else None,
                    "notes": "Created automatically from a batch upload.",
                },
            )
        elif at is not None and dep.started_at > at:
            self.platform.update_deployment(dep.id, {"started_at": at})
        cache[key] = dep
        return dep.id

    # -- completion ---------------------------------------------------------
    def on_analysis_finished(self, analysis_id: str) -> None:
        found = self.platform.analysis_batch_item(analysis_id)
        if found is None:
            return
        job_id, position = found
        row = self.repo.get_analysis(analysis_id)
        if row is None:
            return
        if row.status == "completed":
            self.platform.update_item(job_id, position, {"status": "completed"})
        elif row.status == "failed":
            self.platform.update_item(
                job_id,
                position,
                {
                    "status": "failed",
                    "error_code": row.error_code,
                    "error_message": row.error_message,
                },
            )
        else:
            return
        self.platform.refresh_job_counts(job_id)
        self._settle_if_done(job_id)

    def _settle_if_done(self, job_id: str) -> None:
        found = self.platform.get_job(job_id)
        if found is None:
            return
        job, _ = found
        if job.status in ("completed", "completed_with_errors") and self.alerts is not None:
            with self._lock:
                marker = (job.settings or {}).get("clock_checked")
                if marker:
                    return
                settings = dict(job.settings or {})
                settings["clock_checked"] = True
                self.platform.update_job(job_id, {"settings": settings})
            try:
                self.alerts.evaluate_batch(job_id)
            except Exception:  # noqa: BLE001
                log.exception("batch clock check failed", extra={"job_id": job_id})

    # -- API shapes ------------------------------------------------------------
    def job_model(self, job: BatchJobRow, items: Sequence[BatchItemRow] | None) -> BatchJob:
        return BatchJob(
            id=job.id,
            organization_id=job.organization_id,
            site_id=job.site_id,
            deployment_id=job.deployment_id,
            status=job.status,  # type: ignore[arg-type]
            total=job.total,
            done=job.done,
            failed=job.failed,
            skipped=job.skipped,
            items=[
                BatchItem(
                    filename=i.filename,
                    status=i.status,  # type: ignore[arg-type]
                    recording_id=i.recording_id,
                    analysis_id=i.analysis_id,
                    captured_at=i.captured_at,
                    captured_at_source=i.captured_at_source or "unknown",  # type: ignore[arg-type]
                    telemetry=Telemetry.model_validate(i.telemetry) if i.telemetry else None,
                    error_code=i.error_code,
                    error_message=i.error_message,
                )
                for i in (items or [])
            ],
            settings={k: v for k, v in (job.settings or {}).items() if k != "clock_checked"},
            created_at=job.created_at,
            completed_at=job.completed_at,
            sidecars_parsed=list(job.sidecars_parsed or []),
        )


def _recorder_type(rec: RecorderRow | None, resolved: Resolved) -> str | None:
    if rec is not None:
        parts = [rec.label]
        if rec.model and rec.model.lower() not in rec.label.lower():
            parts.append(rec.model)
        return " ".join(parts)[:200]
    if resolved.device_make == "audiomoth":
        return "AudioMoth"
    if resolved.device_make == "song_meter":
        return "Song Meter"
    return None


def stage_local_files(paths: Sequence[Path], staging_dir: Path) -> list[StagedFile]:
    """CLI helper: link or copy local files into a staging folder."""
    out: list[StagedFile] = []
    for p in paths:
        if not p.is_file() or not _accepts(p.name):
            continue
        dst = staging_dir / f"{secrets.token_hex(8)}{p.suffix.lower()}"
        try:
            dst.hardlink_to(p)
        except OSError:
            shutil.copyfile(p, dst)
        out.append(
            StagedFile(
                path=dst,
                filename=sanitize_filename(p.name),
                byte_size=dst.stat().st_size,
                last_modified_ms=int(p.stat().st_mtime * 1000),
            )
        )
    return out
