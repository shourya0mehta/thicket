import csv
import json

import pytest
from tests.helpers import SOUNDSCAPE, post_analysis

from thicket.api.schemas import AnalysisExport
from thicket.cli import main
from thicket.services.exports import CSV_COLUMNS

pytestmark = pytest.mark.birdnet


def test_cli_analyze_writes_exports(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out_json, out_csv = tmp_path / "a.json", tmp_path / "a.csv"
    code = main(
        [
            "analyze",
            str(SOUNDSCAPE),
            "--threshold",
            "0.3",
            "--lat",
            "42.44",
            "--lon",
            "-76.5",
            "--date",
            "2026-05-15",
            "--json",
            str(out_json),
            "--csv",
            str(out_csv),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "Black-capped Chickadee" in printed and "Shannon" in printed
    export = AnalysisExport.model_validate(json.loads(out_json.read_text()))
    assert export.settings.decision_threshold == 0.3
    assert export.recording.latitude == 42.44
    rows = list(csv.reader(out_csv.open()))
    assert rows[0] == CSV_COLUMNS and len(rows) == len(export.events) + 1


def test_cli_typed_errors(tmp_path, capsys, audio):
    assert main(["analyze", str(audio["txt"])]) == 2
    assert "unsupported_file_type" in capsys.readouterr().err
    assert main(["analyze", str(SOUNDSCAPE), "--threshold", "0.01"]) == 2
    assert "ingestion floor" in capsys.readouterr().err
    assert main(["analyze", str(tmp_path / "missing.wav")]) == 2
    assert main(["analyze", str(SOUNDSCAPE), "--hop", "9"]) == 2


def strip_ids(a: dict) -> dict:
    events = [{k: v for k, v in e.items() if k not in ("id", "model_run_id")} for e in a["events"]]
    raw = [{k: v for k, v in d.items() if k != "model_run_id"} for d in a["raw_detections"]]
    species = [{k: v for k, v in s.items() if k != "model_run_ids"} for s in a["species"]]
    return {
        "events": events,
        "raw": raw,
        "species": species,
        "metrics": a["metrics"],
        "indices": a["acoustic_indices"],
        "quality": a["quality"],
    }


def test_same_file_twice_is_identical(client):
    data = {"threshold": "0.3", "latitude": "42.44", "longitude": "-76.5"}
    a = post_analysis(client, SOUNDSCAPE, data=data).json()
    b = post_analysis(client, SOUNDSCAPE, data=data).json()
    assert a["id"] != b["id"]
    assert strip_ids(a) == strip_ids(b)
    sa = client.get(a["assets"]["spectrogram_url"]).content
    sb = client.get(b["assets"]["spectrogram_url"]).content
    assert sa == sb
    # Re-reading one analysis is stable, ids included.
    assert client.get(f"/api/v1/analyses/{a['id']}?threshold=0.3").json()["events"] == a["events"]
