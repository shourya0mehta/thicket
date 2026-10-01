"""Device metadata from recorder files, without decoding any audio.

* :func:`read_wav_metadata` walks the RIFF chunks of a WAV file and returns
  the ``LIST/INFO`` ``ICMT`` comment (AudioMoth writes its recording summary
  there) and the ``guan`` chunk (GUANO metadata). The ``data`` chunk is
  skipped by seeking, so a 1 GB file costs a few reads.
* :func:`parse_audiomoth_comment` reads the AudioMoth sentence::

      Recorded at 05:30:00 14/05/2024 (UTC) by AudioMoth 24A1D5F3 at medium
      gain while battery was 4.0V and temperature was 12.3C.

  into a timestamp with its UTC offset, device id, gain, battery and
  temperature. Firmware variants ("battery state was", "less than 2.5V",
  "(UTC-5)", trailing amplitude threshold text) are accepted.
* :func:`parse_guano` reads ``Key: Value`` lines (Timestamp, Loc Position,
  Temperature Int, Make, Model, Serial, Firmware Version and friends).
* :func:`parse_song_meter_summary` reads a Wildlife Acoustics
  ``*_Summary.txt`` (CSV with DATE, TIME, LAT, LON, POWER(V), TEMP(C),
  header variants tolerated) into rows, and :func:`match_summary_row`
  finds the row nearest a recording's local timestamp within 60 s.
* :func:`parse_audiomoth_config` reads ``CONFIG.TXT`` (device id, firmware,
  gain, sample rate, sleep and recording durations, time zone).
"""

from __future__ import annotations

import csv
import io
import re
import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

MAX_TEXT_CHUNK = 64 * 1024
MAX_CHUNKS = 256
SUMMARY_MATCH_SECONDS = 60.0


# ------------------------------------------------------------------ RIFF


@dataclass
class WavMetadata:
    comment: str | None = None
    guano: str | None = None
    info: dict[str, str] = field(default_factory=dict)


def _read_exact(fh, n: int) -> bytes:  # type: ignore[no-untyped-def]
    data = fh.read(n)
    return data if len(data) == n else b""


def _decode_text(raw: bytes) -> str:
    raw = raw.split(b"\x00", 1)[0] if b"\x00" in raw[-2:] else raw
    raw = raw.rstrip(b"\x00")
    try:
        return raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace").strip()


def read_wav_metadata(path: Path) -> WavMetadata:
    """ICMT comment, GUANO text and other INFO fields of a RIFF/WAVE file."""
    meta = WavMetadata()
    with open(path, "rb") as fh:
        head = _read_exact(fh, 12)
        if len(head) < 12 or head[:4] not in (b"RIFF", b"RF64") or head[8:12] != b"WAVE":
            return meta
        seen = 0
        while seen < MAX_CHUNKS:
            header = fh.read(8)
            if len(header) < 8:
                break
            cid, size = header[:4], struct.unpack("<I", header[4:8])[0]
            seen += 1
            start = fh.tell()
            if cid == b"LIST":
                list_type = _read_exact(fh, 4)
                if list_type == b"INFO":
                    _read_info(fh, start + size, meta)
            elif cid == b"guan" and size <= MAX_TEXT_CHUNK * 16:
                meta.guano = _decode_text(fh.read(min(size, MAX_TEXT_CHUNK * 16)))
            # Skip to the next chunk (chunks are word aligned).
            fh.seek(start + size + (size & 1))
    return meta


def _read_info(fh, end: int, meta: WavMetadata) -> None:  # type: ignore[no-untyped-def]
    while fh.tell() + 8 <= end:
        header = fh.read(8)
        if len(header) < 8:
            return
        cid, size = header[:4], struct.unpack("<I", header[4:8])[0]
        if size > MAX_TEXT_CHUNK:
            fh.seek(size + (size & 1), 1)
            continue
        raw = fh.read(size)
        if size & 1:
            fh.read(1)
        try:
            key = cid.decode("ascii")
        except UnicodeDecodeError:
            continue
        text = _decode_text(raw)
        meta.info[key] = text
        if key == "ICMT":
            meta.comment = text


# ---------------------------------------------------------- AudioMoth


@dataclass
class AudioMothComment:
    captured_at: datetime | None  # timezone-aware
    device_id: str | None = None
    gain: str | None = None
    battery_v: float | None = None
    temperature_c: float | None = None
    battery_qualifier: str | None = None  # "less than" / "greater than"


_AM_TIME = re.compile(
    r"Recorded at (\d{2}):(\d{2}):(\d{2})\s+(\d{2})/(\d{2})/(\d{4})\s*"
    r"\(UTC(?P<off>[+-]\d{1,2}(?::?\d{2})?)?\)",
    re.IGNORECASE,
)
_AM_DEVICE = re.compile(r"by AudioMoth\s+([0-9A-Fa-f]{8,32})", re.IGNORECASE)
_AM_GAIN = re.compile(r"at (low-medium|medium-high|low|medium|high) gain", re.IGNORECASE)
_AM_BATTERY = re.compile(
    r"battery(?: state)? was (?P<q>less than |greater than )?(?P<v>\d+(?:\.\d+)?)\s*V",
    re.IGNORECASE,
)
_AM_TEMP = re.compile(r"temperature was (-?\d+(?:\.\d+)?)\s*C", re.IGNORECASE)


def _offset(text: str | None) -> timezone:
    if not text:
        return UTC
    sign = -1 if text[0] == "-" else 1
    body = text[1:].replace(":", "")
    hours = int(body[:-2]) if len(body) > 2 else int(body)
    minutes = int(body[-2:]) if len(body) > 2 else 0
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def parse_audiomoth_comment(comment: str | None) -> AudioMothComment | None:
    if not comment or "AudioMoth" not in comment:
        return None
    captured = None
    m = _AM_TIME.search(comment)
    if m:
        hh, mm, ss, dd, mo, yy = (int(x) for x in m.groups()[:6])
        try:
            captured = datetime(yy, mo, dd, hh, mm, ss, tzinfo=_offset(m["off"]))
        except ValueError:
            captured = None
    dev = _AM_DEVICE.search(comment)
    gain = _AM_GAIN.search(comment)
    bat = _AM_BATTERY.search(comment)
    temp = _AM_TEMP.search(comment)
    return AudioMothComment(
        captured_at=captured,
        device_id=dev.group(1).upper() if dev else None,
        gain=gain.group(1).lower() if gain else None,
        battery_v=float(bat["v"]) if bat else None,
        battery_qualifier=bat["q"].strip() if bat and bat["q"] else None,
        temperature_c=float(temp.group(1)) if temp else None,
    )


# ---------------------------------------------------------------- GUANO


@dataclass
class Guano:
    timestamp: datetime | None = None  # aware when the text had an offset, else naive
    latitude: float | None = None
    longitude: float | None = None
    temperature_c: float | None = None
    make: str | None = None
    model: str | None = None
    serial: str | None = None
    firmware: str | None = None
    raw: dict[str, str] = field(default_factory=dict)


def _guano_timestamp(text: str) -> datetime | None:
    t = text.strip()
    if not t:
        return None
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    for candidate in (t, t.replace(" ", "T", 1)):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def parse_guano(text: str | None) -> Guano | None:
    if not text or ":" not in text:
        return None
    g = Guano()
    for line in text.replace("\r\n", "\n").split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not key:
            continue
        g.raw[key] = value
        lk = key.lower()
        if lk == "timestamp":
            g.timestamp = _guano_timestamp(value)
        elif lk == "loc position":
            parts = value.replace(",", " ").split()
            if len(parts) >= 2:
                try:
                    g.latitude, g.longitude = float(parts[0]), float(parts[1])
                except ValueError:
                    pass
        elif lk == "temperature int":
            try:
                g.temperature_c = float(value)
            except ValueError:
                pass
        elif lk == "make":
            g.make = value or None
        elif lk == "model":
            g.model = value or None
        elif lk == "serial":
            g.serial = value or None
        elif lk == "firmware version":
            g.firmware = value or None
    if not g.raw:
        return None
    return g


# ------------------------------------------------------- Song Meter summary


@dataclass
class SummaryRow:
    timestamp: datetime  # naive, recorder local time
    latitude: float | None = None
    longitude: float | None = None
    battery_v: float | None = None
    temperature_c: float | None = None


_HEADER_ALIASES = {
    "date": "date",
    "time": "time",
    "lat": "lat",
    "latitude": "lat",
    "lon": "lon",
    "long": "lon",
    "longitude": "lon",
    "power": "power",
    "powerv": "power",
    "battery": "power",
    "batteryv": "power",
    "batt": "power",
    "voltage": "power",
    "temp": "temp",
    "tempc": "temp",
    "temperature": "temp",
    "temperaturec": "temp",
}
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


def _norm_header(name: str) -> str | None:
    key = re.sub(r"[^a-z]", "", name.lower())
    return _HEADER_ALIASES.get(key)


def _parse_date(text: str) -> tuple[int, int, int] | None:
    t = text.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            d = datetime.strptime(t, fmt)
            return d.year, d.month, d.day
        except ValueError:
            continue
    m = re.match(r"(\d{4})-([A-Za-z]{3})-(\d{1,2})", t)
    if m and m.group(2).lower() in _MONTHS:
        return int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
    return None


def _parse_time(text: str) -> tuple[int, int, int] | None:
    m = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def _parse_coord(text: str, negative_letters: str) -> float | None:
    t = text.strip().upper()
    if not t:
        return None
    sign = -1.0 if any(ch in t for ch in negative_letters) else 1.0
    digits = re.sub(r"[^0-9.\-]", "", t)
    if not digits or digits in ("-", "."):
        return None
    try:
        value = float(digits)
    except ValueError:
        return None
    return sign * abs(value) if sign < 0 else value


def _parse_float(text: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    return float(m.group(0)) if m else None


def parse_song_meter_summary(text: str) -> list[SummaryRow]:
    rows: list[SummaryRow] = []
    reader = csv.reader(io.StringIO(text.replace("\r\n", "\n")))
    header: dict[int, str] | None = None
    for raw in reader:
        if not raw or all(not c.strip() for c in raw):
            continue
        if header is None:
            mapped = {i: _norm_header(c) for i, c in enumerate(raw)}
            if "date" in mapped.values() and "time" in mapped.values():
                header = {i: k for i, k in mapped.items() if k}
            continue
        cells = {header[i]: raw[i] for i in header if i < len(raw)}
        # Classic summaries put the hemisphere letter in an unnamed column after LAT and LON.
        for i, key in header.items():
            if key in ("lat", "lon") and i + 1 < len(raw) and (i + 1) not in header:
                letter = raw[i + 1].strip().upper()
                if letter in ("N", "S", "E", "W"):
                    cells[key] = f"{cells[key]} {letter}"
        d = _parse_date(cells.get("date", ""))
        t = _parse_time(cells.get("time", ""))
        if d is None or t is None:
            continue
        try:
            ts = datetime(*d, *t)
        except ValueError:
            continue
        rows.append(
            SummaryRow(
                timestamp=ts,
                latitude=_parse_coord(cells.get("lat", ""), "S"),
                longitude=_parse_coord(cells.get("lon", ""), "W"),
                battery_v=_parse_float(cells.get("power", "")),
                temperature_c=_parse_float(cells.get("temp", "")),
            )
        )
    return rows


def match_summary_row(
    rows: list[SummaryRow], local_timestamp: datetime, tolerance_s: float = SUMMARY_MATCH_SECONDS
) -> SummaryRow | None:
    """The row nearest ``local_timestamp`` (naive local time) within the tolerance."""
    if not rows:
        return None
    target = local_timestamp.replace(tzinfo=None)
    best = min(rows, key=lambda r: abs((r.timestamp - target).total_seconds()))
    if abs((best.timestamp - target).total_seconds()) <= tolerance_s:
        return best
    return None


# ------------------------------------------------------ AudioMoth CONFIG.TXT


@dataclass
class AudioMothConfig:
    device_id: str | None = None
    firmware: str | None = None
    gain: str | None = None
    sample_rate_hz: int | None = None
    sleep_seconds: float | None = None
    record_seconds: float | None = None
    utc_offset_hours: float | None = None
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def expected_interval_minutes(self) -> float | None:
        if self.sleep_seconds is None or self.record_seconds is None:
            return None
        return round((self.sleep_seconds + self.record_seconds) / 60.0, 3)


def parse_audiomoth_config(text: str) -> AudioMothConfig | None:
    cfg = AudioMothConfig()
    for line in text.replace("\r\n", "\n").split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not key:
            continue
        cfg.raw[key] = value
        lk = key.lower()
        if lk == "device id":
            cfg.device_id = value.upper() or None
        elif lk.startswith("firmware"):
            cfg.firmware = value or None
        elif lk == "gain":
            cfg.gain = value.lower() or None
        elif lk.startswith("sample rate"):
            cfg.sample_rate_hz = int(_parse_float(value) or 0) or None
        elif lk.startswith("sleep duration"):
            cfg.sleep_seconds = _parse_float(value)
        elif lk.startswith("recording duration"):
            cfg.record_seconds = _parse_float(value)
        elif lk.startswith("time zone"):
            m = re.search(r"UTC\s*([+-]\s*\d+(?:[:.]\d+)?)?", value, re.IGNORECASE)
            if m:
                off = (m.group(1) or "0").replace(" ", "")
                if ":" in off:
                    h, mm = off.split(":")
                    cfg.utc_offset_hours = float(h) + (float(mm) / 60.0) * (
                        1 if float(h) >= 0 else -1
                    )
                else:
                    cfg.utc_offset_hours = float(off)
    return cfg if cfg.raw else None


def is_song_meter_summary_name(filename: str) -> bool:
    return filename.lower().endswith("_summary.txt")


def is_audiomoth_config_name(filename: str) -> bool:
    return Path(filename).name.upper() == "CONFIG.TXT"
