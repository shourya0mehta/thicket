"""Filesystem layout under ``THICKET_DATA_DIR``.

::

    <data>/tmp/<analysis_id>/        per-analysis scratch, removed when the job ends
    <data>/previews/<preview_id>/    uploaded file + spectrogram, removed after the TTL
    <data>/spectrograms/<id>.png     analysis spectrograms (no audio)
    <data>/recordings/<id>.wav       normalized audio, only when RETAIN_AUDIO=true

Every path is built from a validated id (see :mod:`thicket.ids`) and checked
to resolve inside the data directory. Client filenames never appear in paths.
A ``storage_uri`` is ``local:<relative path>``, so a later object-store backend
can use its own scheme without a schema change.
"""

from __future__ import annotations

from pathlib import Path

from thicket.errors import analysis_not_found, not_found
from thicket.ids import is_valid_id


class Storage:
    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir).resolve()
        self.tmp = self.root / "tmp"
        self.previews = self.root / "previews"
        self.spectrograms = self.root / "spectrograms"
        self.recordings = self.root / "recordings"

    def ensure(self) -> None:
        for d in (self.root, self.tmp, self.previews, self.spectrograms, self.recordings):
            d.mkdir(parents=True, exist_ok=True)

    def _inside(self, path: Path) -> Path:
        resolved = path.resolve()
        if self.root not in resolved.parents and resolved != self.root:
            raise not_found()
        return resolved

    def analysis_tmp(self, analysis_id: str) -> Path:
        if not is_valid_id(analysis_id, "ana"):
            raise analysis_not_found()
        return self._inside(self.tmp / analysis_id)

    def preview_dir(self, preview_id: str) -> Path:
        if not is_valid_id(preview_id, "prv"):
            raise not_found("No preview with that id exists or it has expired.")
        return self._inside(self.previews / preview_id)

    def spectrogram_path(self, analysis_id: str) -> Path:
        if not is_valid_id(analysis_id, "ana"):
            raise analysis_not_found()
        return self._inside(self.spectrograms / f"{analysis_id}.png")

    def audio_path(self, analysis_id: str) -> Path:
        if not is_valid_id(analysis_id, "ana"):
            raise analysis_not_found()
        return self._inside(self.recordings / f"{analysis_id}.wav")

    def storage_uri(self, path: Path) -> str:
        return "local:" + path.resolve().relative_to(self.root).as_posix()

    def resolve_uri(self, uri: str | None) -> Path | None:
        if not uri or not uri.startswith("local:"):
            return None
        return self._inside(self.root / uri.removeprefix("local:"))
