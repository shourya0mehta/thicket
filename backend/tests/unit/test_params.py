from datetime import date

import pytest
from tests.helpers import make_settings

from thicket.api.schemas import ErrorCode
from thicket.errors import ThicketError
from thicket.models.registry import build_registry
from thicket.services.params import parse_analysis_params, parse_models


@pytest.fixture
def ctx(tmp_path):
    s = make_settings(tmp_path)
    return s, build_registry(s)


def test_parse_models_forms():
    assert parse_models(None) == ["birdnet"]
    assert parse_models("") == ["birdnet"]
    assert parse_models('["birdnet"]') == ["birdnet"]
    assert parse_models("BirdNET, frog_insect,birdnet") == ["birdnet", "frog_insect"]
    for bad in ("[1]", "[", '{"a": 1}', ",", " , "):
        with pytest.raises(ThicketError):
            parse_models(bad)


def test_defaults(ctx):
    s, reg = ctx
    p = parse_analysis_params({}, s, reg)
    assert p.models == ["birdnet"] and p.threshold == 0.6
    assert p.latitude is None and p.recording_date is None


def test_full_params_and_local_date(ctx):
    s, reg = ctx
    p = parse_analysis_params(
        {
            "models": "birdnet",
            "threshold": "0.35",
            "latitude": "42.44",
            "longitude": "-76.5",
            "captured_at": "2026-05-14T23:30:00-04:00",
            "timezone": "America/New_York",
            "site_name": "  Sapsucker Woods ",
        },
        s,
        reg,
    )
    assert p.threshold == 0.35 and p.site_name == "Sapsucker Woods"
    assert p.recording_date == date(2026, 5, 14)
    naive = parse_analysis_params(
        {"captured_at": "2026-05-14T06:00:00", "timezone": "Europe/Berlin"}, s, reg
    )
    assert naive.captured_at.utcoffset().total_seconds() == 7200


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"models": "perch"}, ErrorCode.unknown_model),
        ({"models": "frog_insect"}, ErrorCode.model_unavailable),
        ({"threshold": "0.05"}, ErrorCode.invalid_parameter),
        ({"threshold": "abc"}, ErrorCode.invalid_parameter),
        ({"latitude": "91", "longitude": "0"}, ErrorCode.invalid_parameter),
        ({"latitude": "10", "longitude": "181"}, ErrorCode.invalid_parameter),
        ({"latitude": "10"}, ErrorCode.invalid_parameter),
        ({"timezone": "Mars/Olympus"}, ErrorCode.invalid_parameter),
        ({"timezone": "../../etc/passwd"}, ErrorCode.invalid_parameter),
        ({"captured_at": "yesterday"}, ErrorCode.invalid_parameter),
        ({"site_name": "x" * 201}, ErrorCode.invalid_parameter),
    ],
)
def test_invalid(ctx, fields, code):
    s, reg = ctx
    with pytest.raises(ThicketError) as e:
        parse_analysis_params(fields, s, reg)
    assert e.value.code == code
