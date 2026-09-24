"""Upload intake: stream, cap, sniff, hash.

The multipart body is parsed incrementally (``python-multipart``) straight
from the ASGI stream. File bytes go to a randomly named file in the
analysis's own temp directory, and the size cap is enforced while streaming,
so an oversized upload is rejected as soon as it crosses the limit instead of
after it has been buffered. Checks, in order:

1. Only one file part, with an allowed extension (.wav .mp3 .m4a .flac .ogg).
2. Magic bytes must match the extension (``RIFF....WAVE``, ``ID3`` or an MPEG
   frame sync, ``ftyp`` at offset 4, ``fLaC``, ``OggS``); otherwise 415.
3. Size cap (413) and a SHA-256 of exactly the bytes received.

The client filename is kept only as display metadata, after sanitizing.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import unicodedata
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from pathlib import Path

from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header

from thicket.api.schemas import ErrorCode
from thicket.errors import ThicketError, invalid_parameter

# extension -> canonical kind
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".wav": "wav",
    ".mp3": "mp3",
    ".m4a": "m4a",
    ".flac": "flac",
    ".ogg": "ogg",
}
CONTENT_TYPES: dict[str, str] = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
}
# Which sniffed signatures are acceptable for each extension kind. FLAC files
# occasionally carry an ID3v2 prefix, which libFLAC and FFmpeg both accept.
ACCEPTED_SIGNATURES: dict[str, frozenset[str]] = {
    "wav": frozenset({"wav"}),
    "mp3": frozenset({"mp3"}),
    "m4a": frozenset({"m4a"}),
    "flac": frozenset({"flac", "id3"}),
    "ogg": frozenset({"ogg"}),
}
SNIFF_BYTES = 12
CHUNK_BYTES = 256 * 1024
MAX_FIELD_BYTES = 16 * 1024
MAX_FIELDS = 32

SUPPORTED_LIST = ".wav, .mp3, .m4a, .flac or .ogg"


def sniff_signature(head: bytes) -> str | None:
    """Identify the container from its first bytes.

    Returns one of ``wav``, ``mp3``, ``id3``, ``m4a``, ``flac``, ``ogg`` or None.
    ``id3`` means an ID3v2 tag, which normally prefixes MP3 data.
    """
    if len(head) >= 12 and head[:4] in (b"RIFF", b"RF64") and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg"
    if len(head) >= 8 and head[4:8] == b"ftyp":
        return "m4a"
    if head[:3] == b"ID3":
        return "id3"
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return "mp3"
    return None


def signature_matches(kind: str, head: bytes) -> bool:
    sig = sniff_signature(head)
    if sig == "id3" and kind == "mp3":
        return True
    return sig is not None and sig in ACCEPTED_SIGNATURES.get(kind, frozenset())


def extension_kind(filename: str | None) -> tuple[str, str]:
    """Return (extension, kind) or raise unsupported_file_type."""
    ext = Path(filename or "").suffix.lower()
    kind = ALLOWED_EXTENSIONS.get(ext)
    if kind is None:
        shown = ext or "no extension"
        raise ThicketError(
            ErrorCode.unsupported_file_type,
            f"Files with {shown} are not supported. Upload a {SUPPORTED_LIST} file.",
        )
    return ext, kind


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_filename(name: str | None, fallback: str = "recording") -> str:
    """Display-only filename: basename, no control characters, bounded length."""
    if not name:
        return fallback
    name = unicodedata.normalize("NFC", name)
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _CONTROL.sub("", name).strip().lstrip(".")
    if len(name) > 200:
        stem, ext = os.path.splitext(name)
        name = stem[: 200 - len(ext)] + ext
    return name or fallback


def clean_text(value: str | None, max_len: int, field: str) -> str | None:
    """Trim, strip control characters (keeping newlines in notes) and bound the length."""
    if value is None:
        return None
    text = value.replace("\r\n", "\n").strip()
    text = re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", "", text)
    if not text:
        return None
    if len(text) > max_len:
        raise invalid_parameter(f"{field} must be at most {max_len} characters.", field=field)
    return text


@dataclass(frozen=True)
class StoredUpload:
    path: Path
    filename: str
    extension: str
    kind: str
    content_type: str
    byte_size: int
    sha256: str


class UploadSink:
    """Writes one upload to disk with a byte cap, signature check and SHA-256."""

    def __init__(self, dest_dir: Path, filename: str | None, max_bytes: int) -> None:
        self.extension, self.kind = extension_kind(filename)
        self.filename = sanitize_filename(filename)
        self.max_bytes = max_bytes
        self.path = dest_dir / f"{secrets.token_hex(8)}{self.extension}"
        self._fh = open(self.path, "xb")  # noqa: SIM115 - closed in finish/abort
        self._hash = hashlib.sha256()
        self._size = 0
        self._head = b""
        self._sniffed = False

    def write(self, data: bytes) -> None:
        if not data:
            return
        self._size += len(data)
        if self._size > self.max_bytes:
            self.abort()
            raise file_too_large(self.max_bytes)
        if not self._sniffed:
            self._head += data[: SNIFF_BYTES - len(self._head)]
            if len(self._head) >= SNIFF_BYTES:
                self._check_signature()
        self._hash.update(data)
        self._fh.write(data)

    def _check_signature(self) -> None:
        self._sniffed = True
        if not signature_matches(self.kind, self._head):
            self.abort()
            raise ThicketError(
                ErrorCode.unsupported_file_type,
                f"The file content does not look like a {self.extension} audio file. "
                f"Upload a {SUPPORTED_LIST} file.",
            )

    def finish(self) -> StoredUpload:
        if not self._sniffed:
            self._check_signature()
        self._fh.close()
        if self._size == 0:
            self.abort()
            raise ThicketError(ErrorCode.audio_decode_failed, "The uploaded file is empty.")
        return StoredUpload(
            path=self.path,
            filename=self.filename,
            extension=self.extension,
            kind=self.kind,
            content_type=CONTENT_TYPES[self.kind],
            byte_size=self._size,
            sha256=self._hash.hexdigest(),
        )

    def abort(self) -> None:
        try:
            self._fh.close()
        finally:
            self.path.unlink(missing_ok=True)


def file_too_large(max_bytes: int) -> ThicketError:
    return ThicketError(
        ErrorCode.file_too_large,
        f"The file is larger than the {max_bytes / (1024 * 1024):.0f} MB upload limit.",
        detail={"max_upload_bytes": max_bytes},
    )


def intake_local_file(
    src: Path, dest_dir: Path, max_bytes: int, filename: str | None = None
) -> StoredUpload:
    """Copy a local file through the same checks as an HTTP upload (CLI, preview reuse)."""
    sink = UploadSink(dest_dir, filename or src.name, max_bytes)
    try:
        with open(src, "rb") as fh:
            for block in iter(lambda: fh.read(CHUNK_BYTES), b""):
                sink.write(block)
        return sink.finish()
    except ThicketError:
        raise
    except BaseException:
        sink.abort()
        raise


class _StreamingForm:
    """Callback target for ``python_multipart.MultipartParser``."""

    def __init__(self, dest_dir: Path, max_bytes: int, allowed_fields: Iterable[str], charset: str):
        self.dest_dir = dest_dir
        self.max_bytes = max_bytes
        self.allowed = set(allowed_fields)
        self.charset = charset
        self.fields: dict[str, str] = {}
        self.upload: StoredUpload | None = None
        self._sink: UploadSink | None = None
        self._name = ""
        self._buf = bytearray()
        self._hname = b""
        self._hvalue = b""
        self._disposition = b""
        self._files = 0

    def on_part_begin(self) -> None:
        self._name = ""
        self._buf = bytearray()
        self._disposition = b""
        self._sink = None

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
        raw_name = options.get(b"name")
        if raw_name is None:
            raise invalid_parameter("Malformed multipart body: a part has no name.")
        self._name = raw_name.decode(self.charset, errors="replace")
        if self._name not in self.allowed:
            raise invalid_parameter(
                f"Unknown form field '{self._name[:40]}'.", field=self._name[:40]
            )
        if b"filename" in options:
            if self._name != "file":
                raise invalid_parameter("Only the 'file' field may carry a file.", field=self._name)
            self._files += 1
            if self._files > 1:
                raise invalid_parameter("Upload one file per request.", field="file")
            filename = options[b"filename"].decode(self.charset, errors="replace")
            self._sink = UploadSink(self.dest_dir, filename, self.max_bytes)
        else:
            if self._name == "file":
                raise invalid_parameter("The 'file' field must be a file upload.", field="file")
            if len(self.fields) >= MAX_FIELDS:
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
            self.upload = self._sink.finish()
            self._sink = None
        else:
            if self._name in self.fields:
                raise invalid_parameter(
                    f"Form field '{self._name}' was sent twice.", field=self._name
                )
            self.fields[self._name] = self._buf.decode(self.charset, errors="replace")

    def abort(self) -> None:
        if self._sink is not None:
            self._sink.abort()
            self._sink = None
        if self.upload is not None:
            self.upload.path.unlink(missing_ok=True)


async def parse_multipart_upload(
    content_type: str | None,
    stream: AsyncIterator[bytes],
    dest_dir: Path,
    *,
    max_bytes: int,
    allowed_fields: Iterable[str],
) -> tuple[dict[str, str], StoredUpload | None]:
    """Stream a ``multipart/form-data`` body; return (text fields, stored file or None)."""
    ctype, params = parse_options_header(content_type or "")
    if ctype != b"multipart/form-data" or b"boundary" not in params:
        raise invalid_parameter("Send the request as multipart/form-data.")
    charset = params.get(b"charset", b"utf-8").decode("latin-1")
    form = _StreamingForm(dest_dir, max_bytes, allowed_fields, charset)
    callbacks = {
        "on_part_begin": form.on_part_begin,
        "on_part_data": form.on_part_data,
        "on_part_end": form.on_part_end,
        "on_header_field": form.on_header_field,
        "on_header_value": form.on_header_value,
        "on_header_end": form.on_header_end,
        "on_headers_finished": form.on_headers_finished,
    }
    parser = MultipartParser(params[b"boundary"], callbacks)  # type: ignore[arg-type]
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
    if form._sink is not None:  # body ended inside the file part
        form.abort()
        raise invalid_parameter("Malformed multipart body: the file part is incomplete.")
    return form.fields, form.upload
