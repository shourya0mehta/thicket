"""Notifications: in-app fan-out by preferences, email via outbox, SMTP and
Resend, daily and weekly digests."""

import email
import email.policy
import json

import httpx
import pytest

from thicket.api.platform_schemas import AlertKind, AlertSeverity, NotificationPrefs
from thicket.services.alerts import Candidate
from thicket.services.notify import EmailSender, NotificationService, OutgoingEmail


@pytest.fixture
def org(container):
    c = container
    owner = c.platform.upsert_user(email="owner@example.org", name="Owner")
    org = c.platform.create_org(
        owner.id, name="Notify Farm", kind="farm", timezone="UTC", country=None, region=None
    )
    users = {"owner": owner}
    for key, email_ in (("eco", "eco@example.org"), ("warn", "warn@example.org")):
        u = c.platform.upsert_user(email=email_, name=key)
        c.platform.add_member(org.id, u.id, "viewer")
        users[key] = u
    c.notify.put_prefs(users["eco"].id, NotificationPrefs(categories=["ecology"]))
    c.notify.put_prefs(users["warn"].id, NotificationPrefs(min_severity=AlertSeverity.warning))
    return c, org, users


def raise_(c, org_id, kind=AlertKind.battery_low, severity=AlertSeverity.warning, key="1"):
    return c.alerts.raise_alert(
        org_id,
        Candidate(
            kind=kind,
            severity=severity,
            title=f"Test alert {key}",
            detail="Observed 3.1 V; baseline 3.6 V; n = 1 recording.",
            evidence={"observed": 3.1, "baseline": 3.6, "n": 1},
            recorder_id=f"rcd_{key * 24}"[:28],
        ),
    )


def inbox(c, user_id):
    return c.notify.page(user_id, unread_only=False)


def test_in_app_fan_out_follows_preferences(org):
    c, o, users = org
    raise_(c, o.id)  # recorder, warning
    assert len(inbox(c, users["owner"].id).items) == 1
    assert len(inbox(c, users["warn"].id).items) == 1
    assert inbox(c, users["eco"].id).items == []
    raise_(c, o.id, kind=AlertKind.richness_drop, severity=AlertSeverity.watch, key="2")
    assert len(inbox(c, users["owner"].id).items) == 2
    assert len(inbox(c, users["eco"].id).items) == 1
    assert len(inbox(c, users["warn"].id).items) == 1  # watch is below warning


def test_info_alerts_skip_default_preferences(org):
    c, o, users = org
    raise_(c, o.id, kind=AlertKind.speech_detected, severity=AlertSeverity.info)
    assert inbox(c, users["owner"].id).items == []


def test_repeat_of_an_open_alert_does_not_notify_again(org):
    c, o, users = org
    raise_(c, o.id)
    raise_(c, o.id)
    page = inbox(c, users["owner"].id)
    assert len(page.items) == 1 and page.items[0].alert.occurrences == 2


def test_mark_read(org):
    c, o, users = org
    raise_(c, o.id, key="1")
    raise_(c, o.id, key="2")
    uid = users["owner"].id
    page = inbox(c, uid)
    assert page.unread == 2
    c.platform.mark_read(uid, [page.items[0].id], False)
    assert c.notify.page(uid, unread_only=True).unread == 1
    assert len(c.notify.page(uid, unread_only=True).items) == 1
    c.platform.mark_read(uid, None, True)
    assert inbox(c, uid).unread == 0


def test_immediate_email_goes_to_the_outbox(org):
    c, o, users = org
    c.notify.put_prefs(
        users["owner"].id, NotificationPrefs(email_enabled=True, email_digest="immediate")
    )
    raise_(c, o.id)
    files = list(c.storage.outbox.glob("*.eml"))
    assert len(files) == 1
    msg = email.message_from_bytes(files[0].read_bytes(), policy=email.policy.default)
    assert msg["To"] == "owner@example.org" and "Test alert 1" in msg["Subject"]
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Observed 3.1 V" in body and "#/alerts/" in body
    assert msg.get_body(preferencelist=("html",)) is not None
    assert not any(p.get_content_maintype() == "audio" for p in msg.walk())
    # Other members' addresses never appear.
    raw = files[0].read_text(errors="replace")
    assert "warn@example.org" not in raw and "eco@example.org" not in raw


def test_daily_and_weekly_digests(org):
    c, o, users = org
    c.notify.put_prefs(
        users["owner"].id, NotificationPrefs(email_enabled=True, email_digest="daily")
    )
    c.notify.put_prefs(
        users["warn"].id,
        NotificationPrefs(
            email_enabled=True, email_digest="weekly", min_severity=AlertSeverity.warning
        ),
    )
    raise_(c, o.id, key="1")
    raise_(c, o.id, key="2")
    assert list(c.storage.outbox.glob("*.eml")) == []
    assert c.notify.send_digests("daily") == 1
    files = list(c.storage.outbox.glob("*.eml"))
    msg = email.message_from_bytes(files[0].read_bytes(), policy=email.policy.default)
    assert msg["To"] == "owner@example.org" and "Daily digest: 2 alerts" in msg["Subject"]
    assert c.notify.send_digests("daily") == 0
    assert c.notify.send_digests("weekly") == 1
    assert len(list(c.storage.outbox.glob("*.eml"))) == 2


def test_local_user_is_never_emailed(container):
    c = container
    from thicket.ids import LOCAL_USER_ID

    c.notify.put_prefs(
        LOCAL_USER_ID, NotificationPrefs(email_enabled=True, email_digest="immediate")
    )
    raise_(c, c.platform.local_org_id())
    assert list(c.storage.outbox.glob("*.eml")) == []
    assert len(inbox(c, LOCAL_USER_ID).items) == 1


class FakeSMTP:
    calls: list = []

    def __init__(self, host, port, timeout=None):
        FakeSMTP.calls.append(("connect", host, port))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        FakeSMTP.calls.append(("quit",))

    def ehlo(self):
        FakeSMTP.calls.append(("ehlo",))

    def starttls(self, context=None):
        FakeSMTP.calls.append(("starttls",))

    def login(self, user, password):
        FakeSMTP.calls.append(("login", user, password))

    def send_message(self, msg):
        FakeSMTP.calls.append(("send", msg["To"], msg["From"]))


MSG = OutgoingEmail(to="a@example.org", subject="s", text="t", html="<p>t</p>")


def test_smtp_transport_uses_starttls_and_login(tmp_path):
    from tests.helpers import make_settings

    from thicket.services.storage import Storage

    s = make_settings(
        tmp_path,
        smtp_host="smtp.example.org",
        smtp_user="u",
        smtp_password="p",
        email_from="Thicket <t@example.org>",
    )
    FakeSMTP.calls = []
    sender = EmailSender(s, Storage(s.data_dir), smtp_factory=FakeSMTP)
    assert sender.send(MSG) == "smtp"
    assert FakeSMTP.calls == [
        ("connect", "smtp.example.org", 587),
        ("ehlo",),
        ("starttls",),
        ("ehlo",),
        ("login", "u", "p"),
        ("send", "a@example.org", "Thicket <t@example.org>"),
        ("quit",),
    ]


def test_resend_transport(tmp_path):
    from tests.helpers import make_settings

    from thicket.services.storage import Storage

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "e1"})

    s = make_settings(tmp_path, resend_api_key="re_test")
    sender = EmailSender(
        s, Storage(s.data_dir), http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert sender.send(MSG) == "resend"
    req = seen[0]
    assert str(req.url) == "https://api.resend.com/emails"
    assert req.headers["authorization"] == "Bearer re_test"
    body = json.loads(req.content)
    assert body["to"] == ["a@example.org"] and body["html"] == "<p>t</p>"


def test_failed_immediate_email_falls_back_to_the_daily_digest(org):
    c, o, users = org

    class Broken(EmailSender):
        def send(self, message):
            raise RuntimeError("smtp down")

    c.notify.sender = Broken(c.settings, c.storage)
    c.notify.put_prefs(
        users["owner"].id, NotificationPrefs(email_enabled=True, email_digest="immediate")
    )
    raise_(c, o.id)
    pending = c.platform.pending_email_notifications("daily")
    assert [n.user_id for n, _, _ in pending] == [users["owner"].id]
    c.notify.sender = EmailSender(c.settings, c.storage)
    assert c.notify.send_digests("daily") == 1


def test_matches_helper():
    from thicket.persistence.db import AlertRow

    a = AlertRow(category="quality", severity="watch")
    assert NotificationService.matches(NotificationPrefs(), a)
    assert not NotificationService.matches(NotificationPrefs(categories=["ecology"]), a)
    assert not NotificationService.matches(NotificationPrefs(min_severity=AlertSeverity.warning), a)
