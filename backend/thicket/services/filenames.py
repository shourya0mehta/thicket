"""Recording timestamps from file names.

Recorders encode the start time in the file name, each in its own way.
:func:`parse_filename_timestamp` recognizes the patterns listed in
``docs/PLATFORM_API.md`` and says which clock the time is on:

================================  ===========================  ========
Example                           Pattern                      Clock
================================  ===========================  ========
``20240514_053000.WAV``           AudioMoth                    UTC
``24A1D5F3_20240514_053000.WAV``  AudioMoth with a prefix      UTC
``north_pasture_20240514_0530``   prefix, seconds missing      UTC
``SMA12345_20240514_053000.wav``  Song Meter (SM4, S4A)        local
``SMM01234_20240514_053000.wav``  Song Meter Mini / Micro      local
``2024-05-14T05-30-00.m4a``       ISO date and time            local
``2024-05-14 05.30.00.wav``       ISO date, dotted time        local
``20240514T053000.flac``          compact ISO                  local
``New Recording 7.m4a``           Voice Memos                  none
================================  ===========================  ========

"local" means the recorder's own clock, which the uploader declares with the
batch ``timezone``. AudioMoth clocks run in UTC unless the firmware was told
otherwise, so the plain and prefixed ``YYYYMMDD_HHMMSS`` form is read as UTC;
the ingest service lets the recorder's make override that (a Song Meter
registered as such is always local, an AudioMoth always UTC).

Everything is case-insensitive and only the base name without extension is
inspected. Impossible dates (month 13, hour 25) do not match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

Clock = Literal["utc", "local"]

SONG_METER_PREFIX = re.compile(
    r"\A(SMA|SMM|SMU|S4A|S4U|SM[234])[-_]?\d{3,}[A-Z0-9-]*\Z", re.IGNORECASE
)

# <prefix_>YYYYMMDD[_T]HHMMSS or HHMM, optionally followed by _suffix.
_COMPACT = re.compile(
    r"\A(?P<prefix>(?:.*?)_)?(?P<y>\d{4})(?P<mo>\d{2})(?P<d>\d{2})"
    r"(?P<sep>[_T])(?P<h>\d{2})(?P<mi>\d{2})(?P<s>\d{2})?(?P<rest>(?:[_-].*)?)\Z",
    re.IGNORECASE,
)
# YYYY-MM-DD[T _]HH[-.:_]MM[[-.:_]SS]
_ISO = re.compile(
    r"(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})[T _](?P<h>\d{2})[-.:_]?(?P<mi>\d{2})"
    r"(?:[-.:_]?(?P<s>\d{2}))?(?![\d])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedTimestamp:
    naive: datetime
    clock: Clock
    pattern: str
    prefix: str | None = None
    seconds_known: bool = True


def _stem(filename: str) -> str:
    name = filename.replace("\\", "/")
    base = PurePosixPath(name).name
    stem = PurePosixPath(base).stem
    return stem.strip()


def _build(y: str, mo: str, d: str, h: str, mi: str, s: str | None) -> datetime | None:
    try:
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    except ValueError:
        return None
    if not 2000 <= dt.year <= 2100:
        return None
    return dt


def is_song_meter_prefix(prefix: str | None) -> bool:
    if not prefix:
        return False
    return bool(SONG_METER_PREFIX.match(prefix.rstrip("_")))


def parse_filename_timestamp(filename: str) -> ParsedTimestamp | None:
    """Timestamp and clock from a recorder-style file name, or None."""
    stem = _stem(filename)
    if not stem:
        return None
    m = _COMPACT.match(stem)
    if m:
        dt = _build(m["y"], m["mo"], m["d"], m["h"], m["mi"], m["s"])
        if dt is not None:
            prefix = (m["prefix"] or "").strip("_- ") or None
            if is_song_meter_prefix(prefix):
                return ParsedTimestamp(
                    dt, "local", "song_meter", prefix, seconds_known=m["s"] is not None
                )
            if m["sep"].upper() == "T":
                return ParsedTimestamp(dt, "local", "iso_compact", prefix, m["s"] is not None)
            return ParsedTimestamp(dt, "utc", "audiomoth", prefix, seconds_known=m["s"] is not None)
    m = _ISO.search(stem)
    if m:
        dt = _build(m["y"], m["mo"], m["d"], m["h"], m["mi"], m["s"])
        if dt is not None:
            prefix = stem[: m.start()].rstrip("_- ") or None
            return ParsedTimestamp(dt, "local", "iso", prefix, seconds_known=m["s"] is not None)
    return None


def filename_sort_key(filename: str) -> tuple:
    """Natural sort so ``file_9`` comes before ``file_10``."""
    parts = re.split(r"(\d+)", filename.lower())
    return tuple(int(p) if p.isdigit() else p for p in parts)
