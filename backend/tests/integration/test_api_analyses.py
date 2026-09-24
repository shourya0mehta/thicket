"""End-to-end API tests for analyses (BirdNET runs for real)."""

import csv
import io
import time

import pytest
from tests.helpers import SOUNDSCAPE, post_analysis

from thicket.api.schemas import BIODIVERSITY_TAXA, Analysis, AnalysisExport, ErrorResponse
from thicket.services.exports import CSV_COLUMNS

pytestmark = pytest.mark.birdnet

META = {
    "threshold": "0.3",
    "latitude": "42.44",
    "longitude": "-76.50",
    "captured_at": "2026-05-15T06:10:00",
    "timezone": "America/New_York",
    "site_name": "Sapsucker Woods",
    "recorder_type": "AudioMoth 1.2",
    "notes": "Clear morning",
}


@pytest.fixture
def completed(client):
    r = post_analysis(client, SOUNDSCAPE, data=META)
    assert r.status_code == 201, r.text
    return r.json()


def error(r):
    return ErrorResponse.model_validate(r.json())


def counted(analysis: dict) -> list[dict]:
    return [e for e in analysis["events"] if e["counted_in_metrics"]]


def assert_consistent(a: dict) -> None:
    """Species, metrics and events come from one post-threshold event set."""
    t = a["settings"]["decision_threshold"]
    assert all(e["max_confidence"] >= t - 1e-9 for e in a["events"])
    events = counted(a)
    if all(e["review_status"] == "unreviewed" for e in a["events"]):
        # Without reviews the flag is exactly the documented rule.
        assert events == [
            e
            for e in a["events"]
            if e["taxon"] in BIODIVERSITY_TAXA and e["plausibility"] != "unlikely"
        ]
    species = {e["scientific_name"] for e in events}
    m = a["metrics"]
    assert m["species_richness"] == len(species) == len(a["species"])
    assert m["total_detection_events"] == len(events)
    assert sum(s["detection_event_count"] for s in a["species"]) == len(events)
    assert m["raw_detection_count"] == sum(e["n_windows"] for e in events)
    assert f"threshold={t:g}" in a["assets"]["csv_url"]


def test_create_wait_returns_completed_analysis(client, completed):
    a = Analysis.model_validate(completed)
    assert a.status.value == "completed" and a.stage == "completed"
    assert a.settings.decision_threshold == 0.3
    assert a.settings.requested_models == ["birdnet"]
    assert a.settings.raw_threshold == 0.1 and a.settings.merge_gap_seconds == 1.0
    assert a.recording.site_name == "Sapsucker Woods" and a.recording.latitude == 42.44
    assert a.recording.captured_at.isoformat() == "2026-05-15T06:10:00-04:00"
    assert a.recording.sample_rate_hz == 48000 and a.recording.duration_seconds == 30.0
    assert len(a.recording.checksum_sha256) == 64
    assert [r.adapter for r in a.model_runs] == ["birdnet"]
    run = a.model_runs[0]
    assert run.model == "BirdNET GLOBAL 6K V2.4" and run.version == "2.4" and run.n_windows == 10
    assert run.configuration["location_filter_applied"] is True
    for stage in (
        "queued",
        "normalizing",
        "quality",
        "spectrogram",
        "model:birdnet",
        "consolidating",
        "metrics",
    ):
        assert stage in a.stage_timings_ms
    names = {s.common_name for s in a.species}
    assert {"Black-capped Chickadee", "House Finch", "Blue Jay"} <= names
    assert "Chestnut-winged Cuckoo" not in names  # unlikely in Ithaca in May
    assert any(
        e.common_name == "Chestnut-winged Cuckoo" and e.plausibility == "unlikely" for e in a.events
    )
    assert a.warnings[0] == (
        "Metrics are based on acoustic detection events and do not estimate individual abundance."
    )
    assert a.acoustic_indices is not None and -1 <= a.acoustic_indices.ndsi <= 1
    assert a.quality.status.value in ("usable", "usable_with_warnings")
    assert any(c.name == "speech" for c in a.quality.checks)
    assert a.assets.spectrogram_url and a.assets.audio_url is None
    assert_consistent(completed)


def test_no_forbidden_words(completed):
    text = str(completed).lower()
    for word in ("individuals", "population"):
        assert word not in text
    assert text.count("abundance") == 1


def test_poll_path(client):
    r = post_analysis(client, SOUNDSCAPE, wait=False, data={"models": '["birdnet"]'})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] in ("queued", "processing", "completed")
    assert r.headers["location"] == f"/api/v1/analyses/{body['id']}"
    assert body["settings"]["decision_threshold"] == 0.6
    seen = set()
    deadline = time.time() + 60
    while time.time() < deadline:
        g = client.get(f"/api/v1/analyses/{body['id']}").json()
        seen.add(g["stage"])
        if g["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert g["status"] == "completed", g
    Analysis.model_validate(g)


def test_threshold_recompute(client, completed):
    aid = completed["id"]
    low = client.get(f"/api/v1/analyses/{aid}?threshold=0.1").json()
    high = client.get(f"/api/v1/analyses/{aid}?threshold=0.6").json()
    default = client.get(f"/api/v1/analyses/{aid}").json()
    assert default["settings"]["decision_threshold"] == 0.3
    assert low["settings"]["decision_threshold"] == 0.1
    for a in (low, high, default):
        assert_consistent(a)
    assert low["metrics"]["total_detection_events"] >= default["metrics"]["total_detection_events"]
    assert default["metrics"]["total_detection_events"] >= high["metrics"]["total_detection_events"]
    assert {s["common_name"] for s in high["species"]} == {"Black-capped Chickadee", "House Finch"}
    assert low["raw_detections"] == high["raw_detections"]  # stored once, thresholded on read
    r = client.get(f"/api/v1/analyses/{aid}?threshold=0.05")
    assert r.status_code == 422 and error(r).error_code == "invalid_parameter"
    assert "ingestion floor" in error(r).message
    assert client.get(f"/api/v1/analyses/{aid}?threshold=abc").status_code == 422


def test_csv_export(client, completed):
    aid = completed["id"]
    r = client.get(f"/api/v1/analyses/{aid}/export.csv?threshold=0.3")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == CSV_COLUMNS
    assert rows[0] == [
        "analysis_id", "recording_filename", "site_name", "latitude", "longitude", "captured_at",
        "timezone", "taxon", "common_name", "scientific_name", "event_id", "start_seconds",
        "end_seconds", "max_confidence", "mean_confidence", "n_windows", "model", "model_version",
        "model_run_id", "decision_threshold", "plausibility", "review_status", "reviewed_label",
        "detected_taxon", "detected_common_name", "detected_scientific_name", "counted_in_metrics",
    ]  # fmt: skip
    body = rows[1:]
    assert len(body) == len(completed["events"])
    first = dict(zip(rows[0], body[0], strict=True))
    assert first["analysis_id"] == aid and first["site_name"] == "Sapsucker Woods"
    assert first["model"] == "BirdNET GLOBAL 6K V2.4" and first["decision_threshold"] == "0.3"
    assert first["review_status"] == "unreviewed"
    by_id = {
        e["id"]: e for e in client.get(f"/api/v1/analyses/{aid}?threshold=0.3").json()["events"]
    }
    for row in (dict(zip(rows[0], b, strict=True)) for b in body):
        assert (
            row["counted_in_metrics"] == str(by_id[row["event_id"]]["counted_in_metrics"]).lower()
        )
    assert {r[-1] for r in body} == {"true", "false"}  # the fixture has an unlikely cuckoo


def test_json_export(client, completed):
    aid = completed["id"]
    r = client.get(f"/api/v1/analyses/{aid}/export.json?threshold=0.6")
    assert r.status_code == 200
    doc = r.json()
    export = AnalysisExport.model_validate(doc)
    assert export.export_metadata.decision_threshold == 0.6
    assert "do not estimate individual abundance" in export.export_metadata.note
    meta = doc.pop("export_metadata")
    assert meta["schema_version"] == doc["schema_version"]
    Analysis.model_validate(doc)
    assert doc["settings"]["decision_threshold"] == 0.6
    assert doc["model_runs"][0]["model_sha256"]


def test_review_changes_metrics(client, completed):
    aid = completed["id"]
    before = completed["metrics"]["species_richness"]
    finch = next(e for e in completed["events"] if e["common_name"] == "House Finch")
    r = client.patch(
        f"/api/v1/events/{finch['id']}?threshold=0.3",
        json={"review_status": "rejected", "review_note": "Car alarm"},
    )
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["metrics"]["species_richness"] == before - 1
    ev = next(e for e in a["events"] if e["id"] == finch["id"])
    assert ev["review_status"] == "rejected" and ev["review_note"] == "Car alarm"
    assert a["metrics"]["total_detection_events"] == len(counted(a))
    assert not ev["counted_in_metrics"]
    # The review sticks across thresholds while the event is unchanged.
    again = client.get(f"/api/v1/analyses/{aid}?threshold=0.5").json()
    assert next(e for e in again["events"] if e["id"] == finch["id"])["review_status"] == "rejected"
    # Correct to another species: counts for that species instead.
    r = client.patch(
        f"/api/v1/events/{finch['id']}?threshold=0.3",
        json={"review_status": "corrected", "reviewed_label": "Purple Finch"},
    )
    names = {s["common_name"] for s in r.json()["species"]}
    assert "Purple Finch" in names and "House Finch" not in names
    ev = next(e for e in r.json()["events"] if e["id"] == finch["id"])
    assert (ev["common_name"], ev["scientific_name"]) == ("Purple Finch", "Haemorhous purpureus")
    assert (ev["detected_common_name"], ev["detected_scientific_name"]) == (
        "House Finch",
        "Haemorhous mexicanus",
    )
    assert ev["counted_in_metrics"] and ev["review_status"] == "corrected"
    assert_consistent(r.json())
    # The CSV names the species each row counts under, keeps the model's label
    # and the reviewer's text, and flags the counted rows, so the species table
    # can be rebuilt from the export alone.
    rows = list(csv.DictReader(io.StringIO(
        client.get(f"/api/v1/analyses/{aid}/export.csv?threshold=0.3").text
    )))  # fmt: skip
    row = next(x for x in rows if x["event_id"] == finch["id"])
    assert row["common_name"] == "Purple Finch" and row["review_status"] == "corrected"
    assert row["detected_common_name"] == "House Finch" and row["reviewed_label"] == "Purple Finch"
    rebuilt: dict[str, int] = {}
    for x in rows:
        if x["counted_in_metrics"] == "true":
            rebuilt[x["scientific_name"]] = rebuilt.get(x["scientific_name"], 0) + 1
    assert rebuilt == {
        s["scientific_name"]: s["detection_event_count"] for s in r.json()["species"]
    }
    # Clear the review.
    r = client.patch(
        f"/api/v1/events/{finch['id']}?threshold=0.3", json={"review_status": "unreviewed"}
    )
    assert r.json()["metrics"]["species_richness"] == before
    csv_text = client.get(f"/api/v1/analyses/{aid}/export.csv?threshold=0.3").text
    assert "rejected" not in csv_text


def test_review_errors(client, completed):
    r = client.patch("/api/v1/events/evt_0000000000000000", json={"review_status": "rejected"})
    assert r.status_code == 404 and error(r).error_code == "event_not_found"
    r = client.patch("/api/v1/events/../../etc", json={"review_status": "rejected"})
    assert r.status_code == 404
    ev = completed["events"][0]["id"]
    r = client.patch(f"/api/v1/events/{ev}", json={"review_status": "maybe"})
    assert r.status_code == 422 and error(r).error_code == "invalid_parameter"
    r = client.patch(f"/api/v1/events/{ev}", json={"review_status": "corrected"})
    assert r.status_code == 422 and "reviewed_label" in error(r).message
    r = client.patch(f"/api/v1/events/{ev}", json={"review_status": "accepted", "extra": 1})
    assert r.status_code == 422


def chickadee_windows(a: dict) -> list[list[str]]:
    return [
        e["contributing_detection_ids"]
        for e in counted(a)
        if e["detected_common_name"] == "Black-capped Chickadee"
    ]


def test_rejection_at_060_does_not_return_at_010(client, completed):
    """The case found in review: a chickadee rejected at 0.60 came back at 0.10."""
    aid = completed["id"]
    at60 = client.get(f"/api/v1/analyses/{aid}?threshold=0.6").json()
    chick = next(e for e in at60["events"] if e["common_name"] == "Black-capped Chickadee")
    low_before = client.get(f"/api/v1/analyses/{aid}?threshold=0.1").json()
    [merged] = chickadee_windows(low_before)
    assert set(chick["contributing_detection_ids"]) < set(merged)  # 0.10 merges weaker windows

    # Reviewed the way the web app does it: PATCH, then GET at the slider's threshold.
    r = client.patch(f"/api/v1/events/{chick['id']}", json={"review_status": "rejected"})
    assert r.status_code == 200, r.text
    low = client.get(f"/api/v1/analyses/{aid}?threshold=0.1").json()
    assert_consistent(low)
    listed = next(e for e in low["events"] if e["id"] == chick["id"])
    assert listed["review_status"] == "rejected" and not listed["counted_in_metrics"]
    assert listed["contributing_detection_ids"] == chick["contributing_detection_ids"]
    rest = [i for i in merged if i not in chick["contributing_detection_ids"]]
    assert chickadee_windows(low) == [rest]  # only windows nobody reviewed still count
    unreviewed = next(
        e for e in counted(low) if e["detected_common_name"] == "Black-capped Chickadee"
    )
    assert unreviewed["review_status"] == "unreviewed" and unreviewed["id"] != chick["id"]
    assert low["metrics"]["raw_detection_count"] == low_before["metrics"][
        "raw_detection_count"
    ] - len(chick["contributing_detection_ids"])
    # Undoing the review from the 0.10 view releases the windows again.
    r = client.patch(
        f"/api/v1/events/{chick['id']}?threshold=0.1", json={"review_status": "unreviewed"}
    )
    assert chickadee_windows(r.json()) == [merged]


def test_reviewing_an_event_served_before_schema_2(client, completed):
    """event_refs rows without window ids: the windows are found by re-deriving."""
    from sqlalchemy import update

    from thicket.persistence.db import EventRefRow, EventReviewRow

    aid = completed["id"]
    c = client.app.state.container
    at60 = client.get(f"/api/v1/analyses/{aid}?threshold=0.6").json()
    chick = next(e for e in at60["events"] if e["common_name"] == "Black-capped Chickadee")
    with c.db.session() as s:
        s.execute(update(EventRefRow).values(detection_ids=None))
    r = client.patch(
        f"/api/v1/events/{chick['id']}?threshold=0.6", json={"review_status": "rejected"}
    )
    assert r.status_code == 200, r.text
    with c.db.session() as s:
        stored = s.get(EventReviewRow, chick["id"]).detection_ids
    assert stored == chick["contributing_detection_ids"]
    low = client.get(f"/api/v1/analyses/{aid}?threshold=0.1").json()
    assert all(
        i not in ids for ids in chickadee_windows(low) for i in chick["contributing_detection_ids"]
    )


def test_accepting_an_unlikely_event_counts_it(client, completed):
    aid = completed["id"]
    low = client.get(f"/api/v1/analyses/{aid}?threshold=0.1").json()
    cuckoo = next(e for e in low["events"] if e["common_name"] == "Chestnut-winged Cuckoo")
    assert cuckoo["plausibility"] == "unlikely" and not cuckoo["counted_in_metrics"]
    r = client.patch(
        f"/api/v1/events/{cuckoo['id']}?threshold=0.1", json={"review_status": "accepted"}
    )
    a = r.json()
    ev = next(e for e in a["events"] if e["id"] == cuckoo["id"])
    assert ev["counted_in_metrics"] and ev["plausibility"] == "unlikely"
    assert "Chestnut-winged Cuckoo" in {s["common_name"] for s in a["species"]}
    assert a["metrics"]["species_richness"] == low["metrics"]["species_richness"] + 1
    assert_consistent(a)
    rows = csv.DictReader(
        io.StringIO(client.get(f"/api/v1/analyses/{aid}/export.csv?threshold=0.1").text)
    )
    row = next(x for x in rows if x["event_id"] == cuckoo["id"])
    assert (row["plausibility"], row["review_status"], row["counted_in_metrics"]) == (
        "unlikely",
        "accepted",
        "true",
    )


def test_delete_removes_orphan_site_only(client, completed):
    c = client.app.state.container
    other = post_analysis(client, SOUNDSCAPE, data=META).json()
    site_id = c.repo.load_bundle(completed["id"]).recording.site_id
    assert site_id and c.repo.load_bundle(other["id"]).recording.site_id == site_id
    assert client.delete(f"/api/v1/analyses/{completed['id']}").status_code == 204
    assert c.repo.get_site(site_id) is not None  # still used by the other recording
    assert client.delete(f"/api/v1/analyses/{other['id']}").status_code == 204
    assert c.repo.get_site(site_id) is None  # name and coordinates are gone too


def test_list_recent(client, completed):
    items = client.get("/api/v1/analyses").json()["items"]
    assert items[0]["id"] == completed["id"]
    assert items[0]["species_richness"] == completed["metrics"]["species_richness"]
    assert items[0]["top_species"][0] == completed["species"][0]["common_name"]
    assert client.get("/api/v1/analyses?limit=0").status_code == 422


def test_delete_removes_rows_and_assets(client, completed):
    aid = completed["id"]
    c = client.app.state.container
    png = c.storage.spectrogram_path(aid)
    assert png.is_file()
    assert (
        client.get(f"/api/v1/analyses/{aid}/spectrogram.png").headers["content-type"] == "image/png"
    )
    ev = completed["events"][0]["id"]
    assert client.delete(f"/api/v1/analyses/{aid}").status_code == 204
    assert not png.exists()
    r = client.get(f"/api/v1/analyses/{aid}")
    assert r.status_code == 404 and error(r).error_code == "analysis_not_found"
    assert (
        client.patch(f"/api/v1/events/{ev}", json={"review_status": "accepted"}).status_code == 404
    )
    assert client.delete(f"/api/v1/analyses/{aid}").status_code == 404
    assert client.get(f"/api/v1/analyses/{aid}/export.csv").status_code == 404
    assert client.get("/api/v1/analyses").json()["items"] == []


def test_audio_not_retained_by_default(client, completed):
    r = client.get(f"/api/v1/analyses/{completed['id']}/audio")
    assert r.status_code == 404 and error(r).error_code == "not_found"


def test_audio_retained_when_enabled(make_client):
    client = make_client(retain_audio=True)
    a = post_analysis(client, SOUNDSCAPE).json()
    assert a["assets"]["audio_url"] == f"/api/v1/analyses/{a['id']}/audio"
    r = client.get(a["assets"]["audio_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"
    path = client.app.state.container.storage.audio_path(a["id"])
    assert path.is_file()
    client.delete(f"/api/v1/analyses/{a['id']}")
    assert not path.exists()


@pytest.mark.parametrize(
    "key",
    [
        "soundscape_mp3",
        "soundscape_m4a",
        "soundscape_ogg",
        "soundscape_wav",
        "soundscape_flac_transcode",
    ],
)
def test_formats(client, audio, key):
    r = post_analysis(client, audio[key], data={"threshold": "0.3"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert "Black-capped Chickadee" in {s["common_name"] for s in a["species"]}
    assert a["recording"]["format"].startswith(audio[key].suffix.lstrip("."))


def test_low_sample_rate_warns_but_completes(client, audio):
    r = post_analysis(client, audio["rate_22k"])
    assert r.status_code == 201, r.text
    check = next(c for c in r.json()["quality"]["checks"] if c["name"] == "sample_rate")
    assert check["status"] == "warn"


def test_no_detections_is_valid(client, audio):
    r = post_analysis(client, audio["tone_4k"], data={"threshold": "0.9"})
    assert r.status_code == 201
    a = r.json()
    assert a["species"] == [] and a["metrics"]["species_richness"] == 0
    assert a["metrics"]["shannon_index"] == 0 and a["metrics"]["dominant_species"] is None
