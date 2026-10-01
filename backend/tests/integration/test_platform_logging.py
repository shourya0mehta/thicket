"""Logs carry ids, counts and codes; never emails, file names, notes or invite tokens."""

import json
import logging
import time

from tests.platform_helpers import CSRF, audiomoth_comment, create_org, dev_login, write_wav

from thicket.logging_setup import JsonFormatter

API = "/api/v1"
SECRET_NOTE = "gate code 4471 near the house"
FILENAME = "SMM99999_20240514_053000.wav"


def all_log_text(records) -> str:
    """Server-side log lines (the test client's own httpx logger is not the server)."""
    fmt = JsonFormatter()
    return "\n".join(fmt.format(r) for r in records if not r.name.startswith(("httpx", "httpcore")))


def test_logs_never_contain_personal_or_file_details(make_platform_client, tmp_path, caplog):
    client = make_platform_client(auth_mode="dev")
    with caplog.at_level(logging.DEBUG):
        dev_login(client, "owner.person@farm.example")
        org = create_org(client, "Private Farm")
        inv = client.post(
            f"{API}/orgs/{org['id']}/invites",
            json={"email": "invitee.person@farm.example", "role": "manager"},
            headers=CSRF,
        ).json()
        token = inv["accept_url"].rsplit("/", 1)[-1]
        dev_login(client, "invitee.person@farm.example")
        assert client.post(f"{API}/invites/{token}/accept", headers=CSRF).status_code == 200
        site = client.post(
            f"{API}/orgs/{org['id']}/sites", json={"name": "S", "notes": SECRET_NOTE}, headers=CSRF
        ).json()
        wav = write_wav(tmp_path / "a.wav", 3.5, 2000, comment=audiomoth_comment()).read_bytes()
        job = client.post(
            f"{API}/orgs/{org['id']}/uploads",
            data={"site_id": site["id"], "timezone": "UTC"},
            files=[
                ("files", (FILENAME, wav, "audio/wav")),
                ("files", ("broken.wav", b"RIFFxxxxWAVEjunk", "audio/wav")),
            ],
            headers=CSRF,
        ).json()
        deadline = time.time() + 60
        while time.time() < deadline:
            if client.get(f"{API}/uploads/{job['id']}").json()["status"] != "processing":
                break
            time.sleep(0.1)
        client.post(f"{API}/orgs/{org['id']}/alerts/evaluate", headers=CSRF)
    text = all_log_text(caplog.records)
    assert text, "expected some logs"
    for secret in (
        "owner.person@farm.example",
        "invitee.person@farm.example",
        token,
        SECRET_NOTE,
        FILENAME,
        "broken.wav",
        "Private Farm",
    ):
        assert secret not in text, secret
    # The access log still records the request, with the token redacted.
    paths = [
        json.loads(JsonFormatter().format(r)).get("path")
        for r in caplog.records
        if r.name == "thicket.access"
    ]
    assert "/api/v1/invites/[redacted]/accept" in paths
    assert any(getattr(r, "job_id", None) == job["id"] for r in caplog.records)
