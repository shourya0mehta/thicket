"""Handing the local workspace to an organization once sign-in is switched on
(``python -m thicket.cli adopt-local``), and ``ingest --org``."""

import argparse
from datetime import UTC, date, datetime

from tests.platform_helpers import audiomoth_comment, insert_analysis, write_wav

from thicket.cli import adopt_local as cli_adopt
from thicket.cli import ingest as cli_ingest
from thicket.ids import LOCAL_ORG_ID
from thicket.services.dashboard import build_dashboard

A = "Turdus migratorius"


def adopt_args(**kw):
    return argparse.Namespace(
        org=kw.get("org"), email=kw.get("email"), data_dir=None, verbose=False
    )


def local_data(c):
    """A site, recorder, deployment, two analyses, an alert, a report and a file."""
    site = c.platform.create_site(LOCAL_ORG_ID, {"name": "Laptop pasture"})
    rec = c.platform.create_recorder(LOCAL_ORG_ID, {"label": "AM-L", "make": "audiomoth"})
    dep = c.platform.create_deployment(
        LOCAL_ORG_ID,
        {"recorder_id": rec.id, "site_id": site.id, "started_at": datetime(2026, 5, 1, tzinfo=UTC)},
    )
    ids = [
        insert_analysis(
            c,
            site_id=site.id,
            recorder_id=rec.id,
            deployment_id=dep.id,
            # 01:30 UTC: still 14 May in New York, already 15 May in UTC.
            captured_at=datetime(2026, 5, 15, 1, 30, tzinfo=UTC),
            species={A: 2},
            telemetry={"battery_v": 3.0, "source": "audiomoth_comment"},
        )
    ]
    ids.append(
        insert_analysis(c, captured_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC), species={A: 1})
    )
    c.alerts.evaluate_org(LOCAL_ORG_ID)
    report = c.platform.create_report(
        {
            "organization_id": LOCAL_ORG_ID,
            "template": "evidence",
            "title": "Old report",
            "status": "ready",
            "created_by": "user_" + "0" * 24,
            "period_start": date(2026, 5, 1),
            "period_end": date(2026, 5, 31),
        }
    )
    f = c.platform.create_file(
        {
            "organization_id": LOCAL_ORG_ID,
            "filename": "map.png",
            "content_type": "image/png",
            "byte_size": 3,
            "checksum_sha256": "0" * 64,
            "storage_uri": "local:files/x.png",
        }
    )
    return site, rec, dep, ids, report, f


def test_adopt_local_moves_everything_and_rebuilds_rollups(container, capsys):
    c = container
    site, rec, dep, ids, report, f = local_data(c)
    owner = c.platform.upsert_user(email="owner@farm.example", name="Owner")
    target = c.platform.create_org(
        owner.id,
        name="Hilltop Farm",
        kind="farm",
        timezone="America/New_York",
        country=None,
        region=None,
    )
    assert cli_adopt(adopt_args(org=target.id), container=c) == 0
    out = capsys.readouterr().out
    assert "Hilltop Farm" in out and "recordings: 2" in out
    for row in (
        c.platform.get_site(site.id),
        c.platform.get_recorder(rec.id),
        c.platform.get_deployment(dep.id),
        c.platform.get_report(report.id),
        c.platform.get_file(f.id),
    ):
        assert row.organization_id == target.id
    for aid, rid in ids:
        assert c.platform.org_of_analysis(aid) == target.id
        assert c.platform.get_recording_stats(rid).organization_id == target.id
    alerts, total, *_ = c.platform.list_alerts(target.id)
    assert total >= 1 and {a.kind for a in alerts} >= {"battery_low"}
    assert all(a.open_key and a.open_key.startswith(target.id) for a in alerts)
    assert c.platform.list_alerts(LOCAL_ORG_ID)[1] == 0
    views, n = c.platform.list_recordings(LOCAL_ORG_ID)
    assert n == 0 and c.platform.list_sites(LOCAL_ORG_ID) == []
    # Rollups were rebuilt on the target's clock: 01:30 UTC is 14 May in New York.
    d = build_dashboard(
        c.platform, target.id, start=date(2026, 5, 1), end=date(2026, 5, 31), site_id=None
    )
    assert d.recordings == 1 and [p.date for p in d.richness_by_day] == [date(2026, 5, 14)]
    # Nothing left to adopt; a second run moves nothing and succeeds.
    assert cli_adopt(adopt_args(org=target.id), container=c) == 0


def test_adopt_local_by_email_uses_the_first_owned_org(container, capsys):
    c = container
    local_data(c)
    owner = c.platform.upsert_user(email="owner@farm.example", name="Owner")
    first = c.platform.create_org(
        owner.id, name="First", kind="farm", timezone="UTC", country=None, region=None
    )
    other = c.platform.upsert_user(email="other@farm.example", name="Other")
    theirs = c.platform.create_org(
        other.id, name="Theirs", kind="farm", timezone="UTC", country=None, region=None
    )
    c.platform.add_member(theirs.id, owner.id, "manager")  # not owned: never chosen
    c.platform.create_org(
        owner.id, name="Second", kind="farm", timezone="UTC", country=None, region=None
    )
    assert cli_adopt(adopt_args(email="Owner@Farm.example"), container=c) == 0
    assert c.platform.list_recordings(first.id)[1] == 2
    assert cli_adopt(adopt_args(email="nobody@farm.example"), container=c) == 2
    viewer = c.platform.upsert_user(email="viewer@farm.example", name="V")
    assert cli_adopt(adopt_args(email=viewer.email), container=c) == 2
    assert cli_adopt(adopt_args(org=LOCAL_ORG_ID), container=c) == 2
    assert cli_adopt(adopt_args(org="org_" + "9" * 24), container=c) == 2
    err = capsys.readouterr().err
    assert "owns no organization" in err and "not the local one" in err


def test_adopted_alert_that_the_target_already_has_open_is_resolved(container):
    c = container
    insert_analysis(c, captured_at=datetime.now(UTC), speech=True)  # no site, no recorder
    c.alerts.evaluate_org(LOCAL_ORG_ID)
    owner = c.platform.upsert_user(email="owner@farm.example", name="Owner")
    target = c.platform.create_org(
        owner.id, name="T", kind="farm", timezone="UTC", country=None, region=None
    )
    insert_analysis(c, org_id=target.id, captured_at=datetime.now(UTC), speech=True)
    c.alerts.evaluate_org(target.id)
    moved = c.services.adopt_local(target.id, c.rollups)
    assert moved["alerts"] == 1
    _, total, by_status, _ = c.platform.list_alerts(target.id)
    assert total == 2 and by_status == {"open": 1, "resolved": 1}


def test_cli_ingest_into_an_organization(container, tmp_path, capsys):
    c = container
    owner = c.platform.upsert_user(email="owner@farm.example", name="Owner")
    target = c.platform.create_org(
        owner.id, name="Ingest Farm", kind="farm", timezone="UTC", country=None, region=None
    )
    folder = tmp_path / "sd"
    folder.mkdir()
    write_wav(folder / "20240514_053000.WAV", 3.5, 2000, comment=audiomoth_comment())
    args = argparse.Namespace(
        dir=folder,
        site="Org site",
        recorder=None,
        make=None,
        timezone="UTC",
        models="birdnet",
        threshold=None,
        data_dir=None,
        verbose=False,
        org=target.id,
    )
    assert cli_ingest(args, container=c) == 0, capsys.readouterr()
    site = c.platform.find_site_by_name(target.id, "Org site")
    assert site is not None and c.platform.site_recording_count(site.id) == 1
    assert c.platform.find_site_by_name(LOCAL_ORG_ID, "Org site") is None
    args.org = "org_" + "8" * 24
    assert cli_ingest(args, container=c) == 2
    assert "No organization" in capsys.readouterr().err
