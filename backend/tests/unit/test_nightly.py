"""Nightly scheduler: next run time, one pass, failure isolation, the loop, the CLI."""

import argparse
import threading
from datetime import UTC, datetime, timedelta

from tests.platform_helpers import insert_analysis

from thicket.api.platform_schemas import NotificationPrefs
from thicket.cli import nightly as cli_nightly


def test_next_run(container):
    n = container.nightly
    assert n.settings.nightly_jobs_hour_utc == 6
    assert n.next_run(datetime(2026, 5, 14, 5, 0, tzinfo=UTC)) == datetime(
        2026, 5, 14, 6, tzinfo=UTC
    )
    assert n.next_run(datetime(2026, 5, 14, 6, 0, tzinfo=UTC)) == datetime(
        2026, 5, 15, 6, tzinfo=UTC
    )
    assert n.next_run(datetime(2026, 5, 14, 23, 0, tzinfo=UTC)) == datetime(
        2026, 5, 15, 6, tzinfo=UTC
    )


def test_run_once_does_every_step(container):
    c = container
    org = c.platform.local_org_id()
    site = c.platform.create_site(org, {"name": "Night"})
    rec = c.platform.create_recorder(org, {"label": "N-1", "make": "audiomoth"})
    dep = c.platform.create_deployment(
        org,
        {
            "recorder_id": rec.id,
            "site_id": site.id,
            "started_at": datetime.now(UTC) - timedelta(days=5),
        },
    )
    old = datetime.now(UTC) - timedelta(days=2)
    for i in range(5):
        insert_analysis(
            c,
            site_id=site.id,
            recorder_id=rec.id,
            deployment_id=dep.id,
            captured_at=old + timedelta(minutes=10 * i),
        )
    from thicket.ids import LOCAL_USER_ID

    c.notify.put_prefs(LOCAL_USER_ID, NotificationPrefs(email_enabled=True, email_digest="daily"))
    monday = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
    summary = c.nightly.run_once(monday)
    assert summary["rollups"] == {"recordings": 5, "site_days": 1}
    assert summary["gaps_and_species"] == 1  # the deployment went quiet two days ago
    assert summary["digest_daily"] == 0 and summary["digest_weekly"] == 0  # local user has no inbox
    assert isinstance(summary["janitor"], dict) and summary["sessions_pruned"] == 0
    assert c.nightly.last_run is summary
    kinds = [a.kind for a in c.platform.list_alerts(org)[0]]
    assert kinds == ["recording_gap"]


def test_failing_step_does_not_stop_the_rest(container, monkeypatch):
    c = container

    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(c.rollups, "rebuild", boom)
    summary = c.nightly.run_once(datetime(2026, 9, 29, 6, tzinfo=UTC))  # a Tuesday
    assert summary["rollups"] == "failed"
    assert summary["digest_daily"] == 0 and summary["digest_weekly"] == 0
    assert "janitor" in summary and "finished_at" in summary


def test_loop_runs_and_stops(container, monkeypatch):
    n = container.nightly
    ran = threading.Event()
    base = datetime(2026, 5, 14, 5, 59, 59, 500000, tzinfo=UTC)
    n.clock = lambda: base
    monkeypatch.setattr(n, "run_once", lambda now=None: ran.set())
    n.start()
    try:
        assert ran.wait(5.0)
    finally:
        n.stop()
    assert n._thread is None


def test_loop_runs_once_per_night_when_the_timer_wakes_early(container, monkeypatch):
    """A wake-up just before the target hour used to run the whole pass again a second later."""
    import time

    n = container.nightly
    runs = []
    base = datetime(2026, 5, 14, 5, 59, 59, 500000, tzinfo=UTC)
    n.clock = lambda: base  # the wall clock never reaches 06:00 (an early wake every time)
    monkeypatch.setattr(n, "run_once", lambda now=None: runs.append(1))
    n.start()
    try:
        time.sleep(2.6)
    finally:
        n.stop()
    assert runs == [1]


def test_cli_nightly_prints_a_summary(container, capsys):
    rc = cli_nightly(argparse.Namespace(data_dir=None, verbose=False), container=container)
    out = capsys.readouterr().out
    assert rc == 0 and "rollups:" in out and "janitor:" in out
