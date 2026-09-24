"""Previews: decode, file facts, signal QC and spectrogram, without a model.

A preview keeps the uploaded file for ``PREVIEW_TTL_MINUTES`` so the user
can start an analysis from it (``preview_id``) without uploading again. The
janitor deletes expired previews. Layout::

    <data>/previews/<prv_id>/<random>.<ext>   the uploaded bytes
    <data>/previews/<prv_id>/spectrogram.png
    <data>/previews/<prv_id>/meta.json        facts, QC, expiry (no audio)
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from thicket.api.schemas import Preview, QualityReport, RecordingInfo
from thicket.config import Settings
from thicket.domain.quality import assess_quality
from thicket.errors import ThicketError, not_found
from thicket.ids import is_valid_id, new_id
from thicket.services.analysis import (
    TARGET_SR,
    audio_too_long,
    decode_failed,
    format_label,
    probe_upload,
)
from thicket.services.audio_io import AudioDecodeError, decode
from thicket.services.audio_stats import native_level_stats
from thicket.services.intake import StoredUpload
from thicket.services.results import API_PREFIX
from thicket.services.spectrogram import MAX_HZ, MIN_HZ, write_png
from thicket.services.storage import Storage

log = logging.getLogger(__name__)
META = "meta.json"
SPECTROGRAM = "spectrogram.png"


def _expired() -> Exception:
    return not_found("No preview with that id exists or it has expired. Upload the file again.")


class PreviewService:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.storage = storage

    def new_dir(self) -> tuple[str, Path]:
        pid = new_id("prv")
        d = self.storage.preview_dir(pid)
        d.mkdir(parents=True)
        return pid, d

    def create(self, preview_id: str, upload: StoredUpload) -> Preview:
        d = self.storage.preview_dir(preview_id)
        try:
            pr = probe_upload(upload.path)
            if pr.sample_rate_hz <= 0 or pr.channels <= 0:
                raise decode_failed()
            if pr.duration_seconds > self.settings.max_audio_duration_seconds:
                raise audio_too_long(pr.duration_seconds, self.settings)
            max_s = self.settings.max_audio_duration_seconds
            try:
                mono, sr = decode(
                    upload.path, target_sr=TARGET_SR, mono=True, max_seconds=max_s + 1.0
                )
                duration = mono.size / float(sr)
                # Before the uncapped native-rate pass: a header that understates
                # the length must not buy a full decode of an over-long file.
                if duration > max_s + 0.05:
                    raise audio_too_long(duration, self.settings)
                levels = native_level_stats(upload.path, pr.channels)
            except AudioDecodeError as exc:
                raise decode_failed() from exc
            quality = assess_quality(
                duration_seconds=duration,
                sample_rate_hz=pr.sample_rate_hz,
                levels=levels,
                mono=mono,
                mono_sample_rate=sr,
                min_duration_seconds=self.settings.min_audio_duration_seconds,
                max_duration_seconds=max_s,
            )
            write_png(mono, d / SPECTROGRAM)
            now = datetime.now(UTC)
            recording = RecordingInfo(
                id=new_id("rec"),
                filename=upload.filename,
                content_type=upload.content_type,
                byte_size=upload.byte_size,
                checksum_sha256=upload.sha256,
                format=format_label(upload, pr),
                duration_seconds=round(duration, 3),
                sample_rate_hz=pr.sample_rate_hz,
                channels=pr.channels,
                bit_depth=pr.bit_depth,
            )
            preview = Preview(
                id=preview_id,
                recording=recording,
                quality=quality,
                spectrogram_url=f"{API_PREFIX}/previews/{preview_id}/spectrogram.png",
                spectrogram_min_hz=MIN_HZ,
                spectrogram_max_hz=MAX_HZ,
                expires_at=now + timedelta(minutes=self.settings.preview_ttl_minutes),
            )
            meta = {
                "preview": preview.model_dump(mode="json"),
                "stored_name": upload.path.name,
                "extension": upload.extension,
                "kind": upload.kind,
            }
            tmp = d / (META + ".tmp")
            tmp.write_text(json.dumps(meta), encoding="utf-8")
            tmp.replace(d / META)
            log.info(
                "preview created",
                extra={
                    "preview_id": preview_id,
                    "byte_size": upload.byte_size,
                    "quality": quality.status.value,
                },
            )
            return preview
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise

    def _meta(self, preview_id: str) -> dict:
        if not is_valid_id(preview_id, "prv"):
            raise _expired()
        path = self.storage.preview_dir(preview_id) / META
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise _expired() from exc
        expires = datetime.fromisoformat(meta["preview"]["expires_at"])
        if expires <= datetime.now(UTC):
            raise _expired()
        return meta

    def get(self, preview_id: str) -> Preview:
        return Preview.model_validate(self._meta(preview_id)["preview"])

    def spectrogram_path(self, preview_id: str) -> Path:
        self._meta(preview_id)
        path = self.storage.preview_dir(preview_id) / SPECTROGRAM
        if not path.is_file():
            raise _expired()
        return path

    def quality(self, preview_id: str) -> QualityReport:
        return self.get(preview_id).quality

    def materialize(self, preview_id: str, dest_dir: Path) -> StoredUpload:
        """Copy the preview's file into ``dest_dir`` for an analysis."""
        meta = self._meta(preview_id)
        src = self.storage.preview_dir(preview_id) / meta["stored_name"]
        if not src.is_file() or src.parent != self.storage.preview_dir(preview_id):
            raise _expired()
        rec = meta["preview"]["recording"]
        dst = dest_dir / f"{secrets.token_hex(8)}{meta['extension']}"
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
        return StoredUpload(
            path=dst,
            filename=rec["filename"],
            extension=meta["extension"],
            kind=meta["kind"],
            content_type=rec["content_type"],
            byte_size=int(rec["byte_size"]),
            sha256=rec["checksum_sha256"],
        )

    def release_audio(self, preview_id: str) -> None:
        """Delete the preview's uploaded audio once an analysis has taken its own copy.

        Used when ``RETAIN_AUDIO`` is false so the upload does not outlive the
        analysis (or its deletion) for the rest of the preview TTL. The facts and
        spectrogram stay until expiry; reusing the preview for another analysis
        then returns ``not_found`` and clients upload the file again.
        """
        try:
            meta = self._meta(preview_id)
        except ThicketError:
            return
        d = self.storage.preview_dir(preview_id)
        src = d / str(meta.get("stored_name", ""))
        if src.parent == d and src.name and src.name not in (META, SPECTROGRAM):
            src.unlink(missing_ok=True)

    def delete(self, preview_id: str) -> None:
        """Delete a preview now: uploaded audio, spectrogram and facts."""
        d = self.storage.preview_dir(preview_id)  # validates the id
        if not d.is_dir():
            raise _expired()
        shutil.rmtree(d, ignore_errors=True)
        log.info("preview deleted", extra={"preview_id": preview_id})

    def purge_expired(self, now: datetime | None = None) -> int:
        """Delete expired or broken previews. Returns how many were removed."""
        now = now or datetime.now(UTC)
        removed = 0
        if not self.storage.previews.is_dir():
            return 0
        grace = timedelta(minutes=self.settings.preview_ttl_minutes)
        for d in self.storage.previews.iterdir():
            if not d.is_dir() or not is_valid_id(d.name, "prv"):
                continue
            expired = False
            try:
                meta = json.loads((d / META).read_text(encoding="utf-8"))
                expired = datetime.fromisoformat(meta["preview"]["expires_at"]) <= now
            except (OSError, ValueError, KeyError):
                # No meta yet (upload in progress) or broken: expire by age.
                mtime = datetime.fromtimestamp(d.stat().st_mtime, UTC)
                expired = mtime + grace <= now
            if expired:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        return removed
