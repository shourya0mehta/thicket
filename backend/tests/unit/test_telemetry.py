"""RIFF chunk walker, AudioMoth comments, GUANO, Song Meter summaries, CONFIG.TXT."""

import struct
from datetime import UTC, datetime, timedelta, timezone

import pytest
import soundfile as sf
from tests.platform_helpers import audiomoth_comment, write_wav

from thicket.services.telemetry import (
    is_audiomoth_config_name,
    is_song_meter_summary_name,
    match_summary_row,
    parse_audiomoth_comment,
    parse_audiomoth_config,
    parse_guano,
    parse_song_meter_summary,
    read_wav_metadata,
)

GUANO = (
    "GUANO|Version:1.0\n"
    "Timestamp:2024-05-14T05:30:00-04:00\n"
    "Loc Position:42.44 -76.50\n"
    "Temperature Int:12.5\n"
    "Make:Wildlife Acoustics\n"
    "Model:Song Meter Mini\n"
    "Serial:SMM01234\n"
    "Firmware Version:2.4.1\n"
)


def test_wav_comment_and_guano_are_read_without_decoding(tmp_path):
    p = write_wav(tmp_path / "a.wav", comment=audiomoth_comment(), guano=GUANO)
    meta = read_wav_metadata(p)
    assert meta.comment.startswith("Recorded at 05:30:00 14/05/2024")
    assert meta.info["ICMT"] == meta.comment
    assert meta.guano.startswith("GUANO|Version:1.0")
    # The synthetic file is still valid audio.
    assert sf.info(str(p)).duration == pytest.approx(4.0)


def test_wav_without_metadata(tmp_path):
    p = write_wav(tmp_path / "plain.wav")
    meta = read_wav_metadata(p)
    assert meta.comment is None and meta.guano is None and meta.info == {}


def test_non_riff_and_truncated_files(tmp_path):
    junk = tmp_path / "junk.wav"
    junk.write_bytes(b"not a wav at all")
    assert read_wav_metadata(junk).comment is None
    good = write_wav(tmp_path / "t.wav", comment=audiomoth_comment())
    data = good.read_bytes()
    cut = tmp_path / "cut.wav"
    cut.write_bytes(data[:60])  # header and part of the LIST chunk
    meta = read_wav_metadata(cut)
    assert meta.guano is None  # no crash on a chunk that runs past EOF


def test_odd_sized_chunks_are_padded(tmp_path):
    p = write_wav(tmp_path / "odd.wav", comment="X" * 7, guano="GUANO|Version:1.0\nMake:Odd\n")
    meta = read_wav_metadata(p)
    assert meta.comment == "X" * 7 and "Make:Odd" in meta.guano


def test_audiomoth_comment_utc():
    c = parse_audiomoth_comment(audiomoth_comment())
    assert c.captured_at == datetime(2024, 5, 14, 5, 30, tzinfo=UTC)
    assert c.device_id == "24A1D5F3A1B2C3D4"
    assert (c.gain, c.battery_v, c.temperature_c) == ("medium", 4.0, 12.3)


def test_audiomoth_comment_offset_and_battery_state_variant():
    text = (
        "Recorded at 21:00:05 01/06/2025 (UTC-5) by AudioMoth 24E144085F256D6A at "
        "medium-high gain while battery state was less than 2.5V and temperature was -3.5C. "
        "Amplitude threshold was 0.5%."
    )
    c = parse_audiomoth_comment(text)
    assert c.captured_at == datetime(2025, 6, 1, 21, 0, 5, tzinfo=timezone(timedelta(hours=-5)))
    assert c.captured_at.astimezone(UTC).hour == 2
    assert c.gain == "medium-high" and c.battery_v == 2.5 and c.battery_qualifier == "less than"
    assert c.temperature_c == -3.5


def test_audiomoth_comment_offset_with_minutes():
    c = parse_audiomoth_comment(audiomoth_comment(offset="+5:30"))
    assert c.captured_at.utcoffset() == timedelta(hours=5, minutes=30)


def test_not_an_audiomoth_comment():
    assert parse_audiomoth_comment("Recorded with my phone") is None
    assert parse_audiomoth_comment(None) is None


def test_guano_fields():
    g = parse_guano(GUANO)
    assert g.timestamp == datetime(2024, 5, 14, 5, 30, tzinfo=timezone(timedelta(hours=-4)))
    assert (g.latitude, g.longitude, g.temperature_c) == (42.44, -76.5, 12.5)
    assert (g.make, g.model, g.serial, g.firmware) == (
        "Wildlife Acoustics",
        "Song Meter Mini",
        "SMM01234",
        "2.4.1",
    )


def test_guano_naive_timestamp_and_zulu():
    assert parse_guano("Timestamp:2024-05-14 05:30:00\n").timestamp.tzinfo is None
    assert parse_guano("Timestamp:2024-05-14T05:30:00Z\n").timestamp.tzinfo is not None
    assert parse_guano("") is None and parse_guano(None) is None


SUMMARY = (
    "DATE,TIME,LAT,,LON,,POWER(V),TEMP(C),#FILES,MIC0 TYPE\n"
    "2024-May-14,05:29:58,42.44,N,76.50,W,5.9,12.5,1,U2\n"
    "2024-May-14,05:40:00,42.44,N,76.50,W,5.8,12.7,1,U2\n"
)


def test_song_meter_summary_classic_header():
    rows = parse_song_meter_summary(SUMMARY)
    assert len(rows) == 2
    assert rows[0].timestamp == datetime(2024, 5, 14, 5, 29, 58)
    assert (rows[0].battery_v, rows[0].temperature_c) == (5.9, 12.5)
    assert (rows[0].latitude, rows[0].longitude) == (42.44, -76.5)


@pytest.mark.parametrize(
    "text",
    [
        "Date,Time,Latitude,Longitude,Battery (V),Temperature (C)\n2024-05-14,05:30,42.44N,76.50W,4.9,-1.0\n",
        "DATE,TIME,LAT,LON,POWER(V),TEMP(C)\n05/14/2024,05:30:00,42.44,-76.50,4.9,-1.0\n",
        "  \nDATE,TIME,LAT,LON,POWER(V),TEMP(C)\r\n2024/05/14,5:30:00,42.44 N,76.50 W,4.9V,-1.0C\r\n",
    ],
)
def test_song_meter_summary_header_variants(text):
    rows = parse_song_meter_summary(text)
    assert len(rows) == 1
    r = rows[0]
    assert r.timestamp == datetime(2024, 5, 14, 5, 30)
    assert r.battery_v == 4.9 and r.temperature_c == -1.0
    assert r.latitude == pytest.approx(42.44) and r.longitude == pytest.approx(-76.5)


def test_song_meter_summary_without_header_is_empty():
    assert parse_song_meter_summary("just,some,numbers\n1,2,3\n") == []


def test_match_summary_row_within_60_seconds():
    rows = parse_song_meter_summary(SUMMARY)
    assert match_summary_row(rows, datetime(2024, 5, 14, 5, 30, 30)).battery_v == 5.9
    assert match_summary_row(rows, datetime(2024, 5, 14, 5, 39, 1)).battery_v == 5.8
    assert match_summary_row(rows, datetime(2024, 5, 14, 5, 35, 0)) is None
    assert match_summary_row([], datetime(2024, 5, 14)) is None


def test_audiomoth_config():
    text = (
        "Device ID                       : 24A1D5F3A1B2C3D4\n"
        "Firmware                        : AudioMoth-Firmware-Basic (1.8.1)\n"
        "Time zone                       : UTC-5\n"
        "Sample rate (Hz)                : 48000\n"
        "Gain                            : Medium\n"
        "Sleep duration (s)              : 240\n"
        "Recording duration (s)          : 60\n"
    )
    cfg = parse_audiomoth_config(text)
    assert cfg.device_id == "24A1D5F3A1B2C3D4" and cfg.gain == "medium"
    assert cfg.sample_rate_hz == 48000 and cfg.utc_offset_hours == -5.0
    assert cfg.expected_interval_minutes == 5.0
    assert parse_audiomoth_config("Time zone : UTC+5:30\n").utc_offset_hours == 5.5
    assert parse_audiomoth_config("no colon lines here") is None


def test_sidecar_names():
    assert is_song_meter_summary_name("SMM01234_Summary.txt")
    assert is_song_meter_summary_name("smm01234_summary.TXT")
    assert is_audiomoth_config_name("CONFIG.TXT") and is_audiomoth_config_name("card/config.txt")
    assert not is_audiomoth_config_name("CONFIG.TXT.bak")


def test_riff_walker_skips_large_data_by_seeking(tmp_path):
    p = tmp_path / "big.wav"
    # A data chunk that claims 1 GB but the file ends early; the walker must not read it.
    body = b"fmt " + struct.pack("<I", 16) + struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16)
    body += b"data" + struct.pack("<I", 1 << 30) + b"\x00" * 16
    p.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)
    meta = read_wav_metadata(p)
    assert meta.comment is None
