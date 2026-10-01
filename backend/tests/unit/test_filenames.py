"""Recorder file-name timestamps: every documented pattern plus the tricky cases."""

from datetime import datetime

import pytest

from thicket.services.filenames import (
    filename_sort_key,
    is_song_meter_prefix,
    parse_filename_timestamp,
)

T = datetime(2024, 5, 14, 5, 30, 0)


@pytest.mark.parametrize(
    "name, clock, pattern, prefix",
    [
        ("20240514_053000.WAV", "utc", "audiomoth", None),
        ("20240514_053000.wav", "utc", "audiomoth", None),
        ("24A1D5F3_20240514_053000.WAV", "utc", "audiomoth", "24A1D5F3"),
        ("north_pasture_20240514_053000.wav", "utc", "audiomoth", "north_pasture"),
        ("__x__20240514_053000.wav", "utc", "audiomoth", "x"),
        ("SMA12345_20240514_053000.wav", "local", "song_meter", "SMA12345"),
        ("SMM01234_20240514_053000.wav", "local", "song_meter", "SMM01234"),
        ("smm01234_20240514_053000.WAV", "local", "song_meter", "smm01234"),
        ("S4A09876_20240514_053000_1.wav", "local", "song_meter", "S4A09876"),
        ("2024-05-14T05-30-00.m4a", "local", "iso", None),
        ("2024-05-14 05.30.00.wav", "local", "iso", None),
        ("20240514T053000.flac", "local", "iso_compact", None),
        ("20240514t053000.flac", "local", "iso_compact", None),
    ],
)
def test_patterns(name, clock, pattern, prefix):
    p = parse_filename_timestamp(name)
    assert p is not None, name
    assert p.naive == T
    assert (p.clock, p.pattern, p.prefix) == (clock, pattern, prefix)
    assert p.seconds_known


@pytest.mark.parametrize(
    "name",
    ["north_pasture_20240514_0530.wav", "2024-05-14_05-30.wav", "20240514T0530.wav"],
)
def test_seconds_missing(name):
    p = parse_filename_timestamp(name)
    assert p is not None and p.naive == T and not p.seconds_known


@pytest.mark.parametrize(
    "name",
    [
        "New Recording 7.m4a",
        "recording.wav",
        "20241399_053000.wav",  # month 13
        "20240514_253000.wav",  # hour 25
        "19990514_053000.wav",  # out of range year
        "",
    ],
)
def test_no_timestamp(name):
    assert parse_filename_timestamp(name) is None


def test_only_basename_is_inspected():
    p = parse_filename_timestamp("SD/2023-01-01T00-00-00/20240514_053000.WAV")
    assert p is not None and p.naive == T and p.pattern == "audiomoth"
    assert parse_filename_timestamp("C:\\cards\\20240514_053000.WAV").naive == T


def test_song_meter_prefix_detection():
    assert is_song_meter_prefix("SMA12345") and is_song_meter_prefix("S4U00001")
    assert is_song_meter_prefix("SM3-00123")
    assert not is_song_meter_prefix("24A1D5F3") and not is_song_meter_prefix(None)
    assert not is_song_meter_prefix("SMALLFARM")


def test_natural_sort():
    names = ["file_10.wav", "file_9.wav", "File_1.wav"]
    assert sorted(names, key=filename_sort_key) == ["File_1.wav", "file_9.wav", "file_10.wav"]
