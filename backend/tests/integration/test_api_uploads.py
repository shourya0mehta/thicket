"""Batch uploads over HTTP: files, zips and sidecars in, recordings out."""

import argparse
import io
import time
import zipfile
from datetime import UTC, datetime

import pytest
from tests.platform_helpers import CSRF, audiomoth_comment, create_org, dev_login, write_wav

from thicket.cli import ingest as cli_ingest
from thicket.ids import LOCAL_ORG_ID

API = "/api/v1"
ORG = LOCAL_ORG_ID
NY = "America/New_York"
SUMMARY = (
    "DATE,TIME,LAT,,LON,,POWER(V),TEMP(C),#FILES\n2024-May-14,05:30:05,42.44,N,76.50,W,4.9,8.5,1\n"
)


@pytest.fixture
def client(make_platform_client):
    client = make_platform_client()
    r = client.post(
        f"{API}/orgs/{ORG}/sites",
        json={"name": "Upload site", "latitude": 42.44, "longitude": -76.5},
    )
    client.site_id = r.json()["id"]  # type: ignore[attr-defined]
    return client


def wav_bytes(tmp_path, name, **kw):
    kw.setdefault("seconds", 3.5)
    return write_wav(tmp_path / f"_{name}", **kw).read_bytes()


def upload(client, parts, **data):
    data.setdefault("site_id", client.site_id)
    data.setdefault("timezone", NY)
    files = [("files", (name, content, "application/octet-stream")) for name, content in parts]
    return client.post(f"{API}/orgs/{ORG}/uploads", data=data, files=files)


def wait(client, job_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"{API}/uploads/{job_id}").json()
        if job["status"] in ("completed", "completed_with_errors", "failed"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job did not finish: {job}")


def zipped(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_batch_end_to_end(client, tmp_path):
    clip_ms = int(datetime(2024, 5, 14, 11, 0, tzinfo=UTC).timestamp() * 1000)
    parts = [
        ("20240514_053000.WAV", wav_bytes(tmp_path, "a", freq=2000, comment=audiomoth_comment())),
        ("SMM01234_20240514_053000.wav", wav_bytes(tmp_path, "b", freq=4000)),
        ("SMM01234_Summary.txt", SUMMARY.encode()),
        (
            "New Recording 7.wav",
            wav_bytes(
                tmp_path,
                "c",
                freq=6000,
                comment=audiomoth_comment(when="06:00:00 14/05/2024", battery="3.3"),
            ),
        ),
        ("clip.wav", wav_bytes(tmp_path, "d", freq=1000)),
        (
            "card.zip",
            zipped(
                {
                    "DATA/20240515_060000.WAV": wav_bytes(
                        tmp_path,
                        "e",
                        freq=2000,
                        comment=audiomoth_comment(when="06:00:00 15/05/2024"),
                    ),
                    "../evil.wav": b"RIFF",
                    "DATA/notes.md": b"x",
                }
            ),
        ),
    ]
    stamps = ["0", "0", "0", "0", str(clip_ms), "0"]
    r = upload(client, parts, last_modified=stamps)
    assert r.status_code == 202, r.text
    job = r.json()
    assert r.headers["location"] == f"/api/v1/uploads/{job['id']}"
    assert job["total"] == 5 and job["settings"]["timezone"] == NY
    assert (
        job["settings"]["zips"] == ["card.zip"]
        and "../evil.wav" in job["settings"]["skipped_entries"]
    )
    job = wait(client, job["id"])
    assert job["status"] == "completed", job
    assert (job["done"], job["failed"], job["skipped"]) == (5, 0, 0)
    assert job["sidecars_parsed"] == ["SMM01234_Summary.txt"]
    items = {i["filename"]: i for i in job["items"]}
    assert [i["filename"] for i in job["items"]] == [
        "20240514_053000.WAV",
        "20240515_060000.WAV",
        "clip.wav",
        "New Recording 7.wav",
        "SMM01234_20240514_053000.wav",
    ]
    a = items["20240514_053000.WAV"]
    assert a["captured_at_source"] == "filename" and a["captured_at"].startswith(
        "2024-05-14T05:30:00"
    )
    assert a["telemetry"]["source"] == "audiomoth_comment" and a["telemetry"]["battery_v"] == 4.0
    sm = items["SMM01234_20240514_053000.wav"]
    assert sm["captured_at"].startswith("2024-05-14T09:30:00")  # 05:30 New York time
    assert sm["telemetry"]["source"] == "song_meter_summary" and sm["telemetry"]["battery_v"] == 4.9
    nr = items["New Recording 7.wav"]
    assert nr["captured_at_source"] == "file_metadata" and nr["captured_at"].startswith(
        "2024-05-14T06:00:00"
    )
    assert items["clip.wav"]["captured_at_source"] == "browser_last_modified"
    assert items["20240515_060000.WAV"]["captured_at_source"] == "filename"
    for item in job["items"]:
        assert item["status"] == "completed" and item["analysis_id"] and item["recording_id"]

    recs = client.get(f"{API}/orgs/{ORG}/recordings?page_size=10").json()
    assert recs["total"] == 5
    by_name = {x["filename"]: x for x in recs["items"]}
    assert by_name["20240514_053000.WAV"]["species_richness"] == 1
    assert by_name["clip.wav"]["species_richness"] == 0
    assert by_name["SMM01234_20240514_053000.wav"]["latitude"] == 42.44
    recorders = {r["label"]: r for r in client.get(f"{API}/orgs/{ORG}/recorders").json()}
    assert set(recorders) == {"AudioMoth 24A1D5F3A1B2C3D4", "Song Meter SMM01234"}
    assert recorders["Song Meter SMM01234"]["make"] == "song_meter"
    deployments = client.get(f"{API}/orgs/{ORG}/deployments").json()
    assert {d["recorder_id"] for d in deployments} == {r["id"] for r in recorders.values()}
    assert by_name["20240514_053000.WAV"]["deployment_id"] in {d["id"] for d in deployments}
    # Battery 3.3 V on the AudioMoth opened an alert after its analysis completed.
    kinds = {a["kind"] for a in client.get(f"{API}/orgs/{ORG}/alerts").json()["items"]}
    assert "battery_low" in kinds
    # The AudioMoth files arrive in order, so no clock alert for it.
    assert "clock_suspect" not in kinds
    listed = client.get(f"{API}/orgs/{ORG}/uploads").json()
    assert listed[0]["id"] == job["id"] and listed[0]["items"] == []


def test_config_sidecar_shapes_the_deployment(client, tmp_path):
    cfg = (
        "Device ID : 24E144085F256D6A\nFirmware : AudioMoth-Firmware-Basic (1.8.1)\n"
        "Gain : Medium\nSleep duration (s) : 240\nRecording duration (s) : 60\n"
    )
    parts = [
        ("CONFIG.TXT", cfg.encode()),
        ("20240514_053000.WAV", wav_bytes(tmp_path, "a")),
        ("20240514_053500.WAV", wav_bytes(tmp_path, "b")),
    ]
    job = wait(client, upload(client, parts).json()["id"])
    assert job["status"] == "completed" and job["sidecars_parsed"] == ["CONFIG.TXT"]
    (rec,) = client.get(f"{API}/orgs/{ORG}/recorders").json()
    assert (
        rec["serial"] == "24E144085F256D6A"
        and rec["firmware"] == "AudioMoth-Firmware-Basic (1.8.1)"
    )
    (dep,) = client.get(f"{API}/orgs/{ORG}/deployments").json()
    assert dep["expected_interval_minutes"] == 5.0 and dep["expected_clip_seconds"] == 60.0
    assert dep["gain_setting"] == "medium" and dep["started_at"].startswith("2024-05-14T05:30:00")
    assert all(i["telemetry"]["device_id"] == "24E144085F256D6A" for i in job["items"])


def test_explicit_recorder_and_override(client, tmp_path):
    rec = client.post(
        f"{API}/orgs/{ORG}/recorders", json={"label": "SM-1", "make": "song_meter"}
    ).json()
    parts = [
        ("20240514_053000.wav", wav_bytes(tmp_path, "a")),
        ("untimed.wav", wav_bytes(tmp_path, "b")),
    ]
    r = upload(client, parts, recorder_id=rec["id"], captured_at_override="2024-05-20T07:00:00")
    job = wait(client, r.json()["id"])
    items = {i["filename"]: i for i in job["items"]}
    # A Song Meter's clock is local even for an AudioMoth-style name.
    assert items["20240514_053000.wav"]["captured_at"].startswith("2024-05-14T09:30:00")
    assert items["untimed.wav"]["captured_at_source"] == "user"
    assert items["untimed.wav"]["captured_at"].startswith("2024-05-20T11:00:00")
    assert len(client.get(f"{API}/orgs/{ORG}/recorders").json()) == 1


def test_failed_items_do_not_fail_the_job(client, tmp_path):
    parts = [
        ("20240514_053000.WAV", wav_bytes(tmp_path, "a")),
        ("broken.wav", b"RIFF\x24\x10\x00\x00WAVEjunk" + bytes(range(256)) * 8),
        ("short.wav", wav_bytes(tmp_path, "s", seconds=0.3)),
    ]
    job = wait(client, upload(client, parts).json()["id"])
    assert job["status"] == "completed_with_errors"
    assert (job["done"], job["failed"]) == (1, 2)
    items = {i["filename"]: i for i in job["items"]}
    assert items["broken.wav"]["error_code"] == "audio_decode_failed"
    assert items["short.wav"]["error_code"] == "audio_too_short"
    assert client.get(f"{API}/orgs/{ORG}/recordings").json()["total"] == 1


@pytest.mark.parametrize(
    "data, status, code",
    [
        ({"timezone": ""}, 422, "invalid_parameter"),
        ({"timezone": "Mars/Base"}, 422, "invalid_parameter"),
        ({"site_id": ""}, 422, "invalid_parameter"),
        ({"site_id": "site_" + "9" * 24}, 422, "invalid_parameter"),
        ({"models": "nope"}, 422, "unknown_model"),
        ({"threshold": "0.01"}, 422, "invalid_parameter"),
        ({"surprise": "1"}, 422, "invalid_parameter"),
    ],
)
def test_upload_validation(client, tmp_path, data, status, code):
    r = upload(client, [("20240514_053000.WAV", wav_bytes(tmp_path, "a"))], **data)
    assert r.status_code == status and r.json()["error_code"] == code, r.text
    assert list(client.app.state.container.storage.tmp.iterdir()) == []


def test_upload_rejects_other_files_and_empty_batches(client, tmp_path):
    r = upload(client, [("notes.txt", b"hello")])
    assert r.status_code == 415 and r.json()["error_code"] == "unsupported_file_type"
    r = client.post(f"{API}/orgs/{ORG}/uploads", data={"site_id": client.site_id, "timezone": NY})
    assert r.status_code == 422


def test_batch_caps(make_platform_client, tmp_path):
    client = make_platform_client(max_batch_files=2, max_batch_bytes=1024 * 1024)
    sid = client.post(f"{API}/orgs/{ORG}/sites", json={"name": "Caps"}).json()["id"]
    small = wav_bytes(tmp_path, "a", seconds=1.0)
    r = client.post(
        f"{API}/orgs/{ORG}/uploads",
        data={"site_id": sid, "timezone": NY},
        files=[("files", (f"{i}.wav", small, "audio/wav")) for i in range(3)],
    )
    assert r.status_code == 422 and "at most 2" in r.json()["message"]
    big = wav_bytes(tmp_path, "big", seconds=12.0)  # about 1.1 MB
    r = client.post(
        f"{API}/orgs/{ORG}/uploads",
        data={"site_id": sid, "timezone": NY},
        files=[("files", ("big.wav", big, "audio/wav"))],
    )
    assert r.status_code == 413 and r.json()["error_code"] == "file_too_large"
    r = client.post(
        f"{API}/orgs/{ORG}/uploads",
        data={"site_id": sid, "timezone": NY},
        files=[
            ("files", ("z.zip", zipped({f"{i}.wav": small for i in range(3)}), "application/zip"))
        ],
    )
    assert r.status_code == 422
    assert list(client.app.state.container.storage.tmp.iterdir()) == []


def test_uploads_need_the_manager_role(make_platform_client, tmp_path):
    client = make_platform_client(auth_mode="dev")
    dev_login(client, "owner@example.org")
    org = create_org(client)
    sid = client.post(f"{API}/orgs/{org['id']}/sites", json={"name": "S"}, headers=CSRF).json()[
        "id"
    ]
    token = (
        client.post(
            f"{API}/orgs/{org['id']}/invites",
            json={"email": "rev@example.org", "role": "reviewer"},
            headers=CSRF,
        )
        .json()["accept_url"]
        .rsplit("/", 1)[-1]
    )
    dev_login(client, "rev@example.org")
    client.post(f"{API}/invites/{token}/accept", headers=CSRF)
    r = client.post(
        f"{API}/orgs/{org['id']}/uploads",
        data={"site_id": sid, "timezone": NY},
        files=[("files", ("a.wav", wav_bytes(tmp_path, "a"), "audio/wav"))],
        headers=CSRF,
    )
    assert r.status_code == 403


def test_cli_ingest_uses_the_same_service(container, tmp_path, capsys):
    folder = tmp_path / "sd"
    (folder / "DATA").mkdir(parents=True)
    write_wav(folder / "DATA" / "20240514_053000.WAV", 3.5, 2000, comment=audiomoth_comment())
    write_wav(folder / "DATA" / "20240514_054000.WAV", 3.5, 4000)
    (folder / "readme.md").write_text("ignored")
    args = argparse.Namespace(
        dir=folder,
        site="CLI site",
        recorder="AM-CLI",
        make="audiomoth",
        timezone=NY,
        models="birdnet",
        threshold=None,
        data_dir=None,
        verbose=False,
    )
    rc = cli_ingest(args, container=container)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "20240514_053000.WAV  completed" in out and "2 completed, 0 failed" in out
    org = container.platform.local_org_id()
    site = container.platform.find_site_by_name(org, "CLI site")
    assert site is not None and container.platform.site_recording_count(site.id) == 2
    rec = container.platform.find_recorder(org, label="AM-CLI")
    assert rec.make == "audiomoth" and container.platform.recorder_recording_count(rec.id) == 2
    args.dir = tmp_path / "missing"
    assert cli_ingest(args, container=container) == 2
