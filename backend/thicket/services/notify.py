"""Notifications: in-app rows per member and email (immediate or digests).

When an alert opens, every member of the organization whose preferences
match (category and minimum severity) gets an in-app notification. Members
with email enabled get a message right away (``immediate``) or a pending
email row that the nightly job bundles into a daily or weekly digest.

Email transport, in order of preference: SMTP with STARTTLS (``SMTP_HOST``),
Resend (``RESEND_API_KEY``), otherwise an ``.eml`` file in
``<data dir>/outbox/`` so development installs can see what would be sent.
Messages are plain text plus simple HTML. They never include audio, user
notes or other members' addresses; logs carry ids and counts only.
"""

from __future__ import annotations

import html
import logging
import smtplib
import ssl
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from urllib.parse import quote, urlencode

import httpx

from thicket.api.platform_schemas import (
    Alert,
    AlertSeverity,
    Notification,
    NotificationPage,
    NotificationPrefs,
)
from thicket.api.schemas import SpeciesRef
from thicket.config import Settings
from thicket.ids import LOCAL_USER_ID
from thicket.persistence.db import AlertRow, NotificationRow, UserRow, utcnow
from thicket.persistence.platform_repositories import PlatformRepository
from thicket.services.storage import Storage

log = logging.getLogger(__name__)

SEVERITY_RANK = {"info": 0, "watch": 1, "warning": 2}
RESEND_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "Thicket <no-reply@thicket.local>"


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str


class EmailSender:
    """Sends one message through SMTP, Resend or the outbox folder."""

    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        http: httpx.Client | None = None,
        smtp_factory: Callable[..., smtplib.SMTP] | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.http = http
        self.smtp_factory = smtp_factory or smtplib.SMTP
        self.sent: list[OutgoingEmail] = []

    @property
    def transport(self) -> str:
        if self.settings.smtp_host:
            return "smtp"
        if self.settings.resend_api_key:
            return "resend"
        return "outbox"

    def send(self, message: OutgoingEmail) -> str:
        """Deliver and return the transport used. Raises on transport failure."""
        transport = self.transport
        if transport == "smtp":
            self._send_smtp(message)
        elif transport == "resend":
            self._send_resend(message)
        else:
            self._write_outbox(message)
        self.sent.append(message)
        return transport

    def _mime(self, message: OutgoingEmail) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.settings.email_from or DEFAULT_FROM
        msg["To"] = message.to
        msg["Subject"] = message.subject
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = make_msgid(domain="thicket.local")
        msg.set_content(message.text)
        msg.add_alternative(message.html, subtype="html")
        return msg

    def _send_smtp(self, message: OutgoingEmail) -> None:
        s = self.settings
        assert s.smtp_host
        msg = self._mime(message)
        with self.smtp_factory(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            if s.smtp_port != 465:
                try:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                except smtplib.SMTPNotSupportedError:
                    if s.smtp_user:
                        raise
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password or "")
            smtp.send_message(msg)

    def _send_resend(self, message: OutgoingEmail) -> None:
        client = self.http or httpx.Client(timeout=15.0)
        r = client.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {self.settings.resend_api_key}"},
            json={
                "from": self.settings.email_from or DEFAULT_FROM,
                "to": [message.to],
                "subject": message.subject,
                "text": message.text,
                "html": message.html,
            },
        )
        if r.status_code >= 300:
            raise RuntimeError(f"Resend returned HTTP {r.status_code}")

    def _write_outbox(self, message: OutgoingEmail) -> None:
        folder = self.storage.outbox
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        path = folder / f"{stamp}_{abs(hash(message.to)) % 10_000:04d}.eml"
        path.write_bytes(self._mime(message).as_bytes())


class NotificationService:
    def __init__(
        self,
        settings: Settings,
        platform: PlatformRepository,
        storage: Storage,
        sender: EmailSender | None = None,
    ) -> None:
        self.settings = settings
        self.platform = platform
        self.storage = storage
        self.sender = sender or EmailSender(settings, storage)

    # -- preferences ----------------------------------------------------------
    def prefs(self, user_id: str) -> NotificationPrefs:
        stored = self.platform.notification_prefs(user_id)
        try:
            return NotificationPrefs.model_validate(stored) if stored else NotificationPrefs()
        except Exception:  # noqa: BLE001
            return NotificationPrefs()

    def put_prefs(self, user_id: str, prefs: NotificationPrefs) -> NotificationPrefs:
        self.platform.put_notification_prefs(user_id, prefs.model_dump(mode="json"))
        return prefs

    @staticmethod
    def matches(prefs: NotificationPrefs, alert: AlertRow) -> bool:
        if alert.category not in prefs.categories:
            return False
        return SEVERITY_RANK.get(alert.severity, 0) >= SEVERITY_RANK.get(
            prefs.min_severity.value, 0
        )

    # -- fan-out --------------------------------------------------------------
    def on_alert(self, alert: AlertRow) -> int:
        """Create notifications for a newly opened alert. Returns how many rows were written."""
        user_ids = self.platform.member_user_ids(alert.organization_id)
        if not user_ids:
            return 0
        stored = self.platform.prefs_for_users(user_ids)
        users = self.platform.users_by_ids(user_ids)
        written = 0
        for uid in user_ids:
            try:
                prefs = (
                    NotificationPrefs.model_validate(stored[uid])
                    if stored.get(uid)
                    else NotificationPrefs()
                )
            except Exception:  # noqa: BLE001
                prefs = NotificationPrefs()
            if not self.matches(prefs, alert):
                continue
            if not self.platform.has_notification(uid, alert.id, "in_app"):
                self.platform.add_notification(
                    user_id=uid, org_id=alert.organization_id, alert_id=alert.id, channel="in_app"
                )
                written += 1
            user = users.get(uid)
            if not prefs.email_enabled or prefs.email_digest == "off" or user is None:
                continue
            if uid == LOCAL_USER_ID or user.email.endswith(".invalid"):
                continue
            if self.platform.has_notification(uid, alert.id, "email"):
                continue
            if prefs.email_digest == "immediate":
                sent_at = None
                try:
                    self.sender.send(self.compose_single(user, alert))
                    sent_at = utcnow()
                except Exception:  # noqa: BLE001 - keep the in-app row, retry in the digest
                    log.warning("immediate email failed", extra={"alert_id": alert.id})
                self.platform.add_notification(
                    user_id=uid,
                    org_id=alert.organization_id,
                    alert_id=alert.id,
                    channel="email",
                    digest="immediate" if sent_at else "daily",
                    sent_at=sent_at,
                )
            else:
                self.platform.add_notification(
                    user_id=uid,
                    org_id=alert.organization_id,
                    alert_id=alert.id,
                    channel="email",
                    digest=prefs.email_digest,
                )
            written += 1
        log.info(
            "notifications written",
            extra={"alert_id": alert.id, "count": written, "org_id": alert.organization_id},
        )
        return written

    # -- digests --------------------------------------------------------------
    def send_digests(self, kind: str) -> int:
        """Send every pending ``daily`` or ``weekly`` email as one digest per user."""
        pending = self.platform.pending_email_notifications(kind)
        if not pending:
            return 0
        by_user: dict[str, list[tuple[NotificationRow, AlertRow, UserRow]]] = {}
        for n, a, u in pending:
            by_user.setdefault(u.id, []).append((n, a, u))
        sent = 0
        for uid, rows in by_user.items():
            user = rows[0][2]
            if uid == LOCAL_USER_ID or user.email.endswith(".invalid"):
                self.platform.mark_sent([n.id for n, _, _ in rows])
                continue
            alerts = [a for _, a, _ in rows]
            try:
                self.sender.send(self.compose_digest(user, alerts, kind))
            except Exception:  # noqa: BLE001 - try again next run
                log.warning("digest email failed", extra={"user_id": uid, "kind": kind})
                continue
            self.platform.mark_sent([n.id for n, _, _ in rows])
            sent += 1
        log.info("digests sent", extra={"kind": kind, "users": sent})
        return sent

    # -- composition ----------------------------------------------------------
    def alert_url(self, alert: AlertRow) -> str:
        """The organization's alert inbox with this alert expanded (the frontend's route;
        ``status=all`` so the link still works once the alert is acknowledged)."""
        query = urlencode({"status": "all", "alert": alert.id})
        return f"{self.settings.frontend_url}/#/orgs/{quote(alert.organization_id)}/alerts?{query}"

    def compose_single(self, user: UserRow, alert: AlertRow) -> OutgoingEmail:
        # Titles carry site names and recorder labels, which may hold line breaks;
        # a header with one is refused, so the email would never go out.
        subject = " ".join(f"[Thicket] {alert.severity}: {alert.title}".split())
        text = "\n".join(
            [
                f"Hello {user.name},",
                "",
                f"{alert.title}",
                f"Severity: {alert.severity}. Category: {alert.category}.",
                "",
                alert.detail,
                "",
                *([f"What to do: {alert.suggested_action}", ""] if alert.suggested_action else []),
                f"Open in Thicket: {self.alert_url(alert)}",
                "",
                "You receive this because email notifications are enabled in your Thicket "
                "preferences. Change them under Notifications.",
            ]
        )
        body = _alert_html(alert, self.alert_url(alert))
        return OutgoingEmail(to=user.email, subject=subject, text=text, html=_page(body, user.name))

    def compose_digest(self, user: UserRow, alerts: Sequence[AlertRow], kind: str) -> OutgoingEmail:
        subject = f"[Thicket] {kind.capitalize()} digest: {len(alerts)} alert{'s' if len(alerts) != 1 else ''}"
        lines = [
            f"Hello {user.name},",
            "",
            f"{len(alerts)} alert{'s' if len(alerts) != 1 else ''} since your last digest:",
            "",
        ]
        parts = []
        for a in alerts:
            lines += [f"- [{a.severity}] {a.title}", f"  {a.detail}", f"  {self.alert_url(a)}", ""]
            parts.append(_alert_html(a, self.alert_url(a)))
        lines.append("Change how often you get this under Notifications in Thicket.")
        return OutgoingEmail(
            to=user.email,
            subject=subject,
            text="\n".join(lines),
            html=_page("<hr>".join(parts), user.name),
        )

    # -- API shapes -------------------------------------------------------------
    def page(self, user_id: str, unread_only: bool) -> NotificationPage:
        rows = self.platform.list_notifications(user_id, unread_only=unread_only)
        return NotificationPage(
            items=[
                Notification(
                    id=n.id,
                    alert=alert_model(a),
                    channel=n.channel,  # type: ignore[arg-type]
                    created_at=n.created_at,
                    read_at=n.read_at,
                    sent_at=n.sent_at,
                )
                for n, a in rows
            ],
            unread=self.platform.unread_count(user_id),
        )


def alert_model(row: AlertRow) -> Alert:
    return Alert(
        id=row.id,
        organization_id=row.organization_id,
        kind=row.kind,  # type: ignore[arg-type]
        category=row.category,  # type: ignore[arg-type]
        severity=AlertSeverity(row.severity),
        status=row.status,  # type: ignore[arg-type]
        title=row.title,
        detail=row.detail,
        suggested_action=row.suggested_action,
        evidence=dict(row.evidence or {}),
        site_id=row.site_id,
        recorder_id=row.recorder_id,
        deployment_id=row.deployment_id,
        species=SpeciesRef(
            scientific_name=row.species_scientific_name,
            common_name=row.species_common_name or row.species_scientific_name,
        )
        if row.species_scientific_name
        else None,
        recording_ids=list(row.recording_ids or []),
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        occurrences=int(row.occurrences or 1),
        acknowledged_by=row.acknowledged_by,
        note=row.note,
        snoozed_until=row.snoozed_until,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _alert_html(a: AlertRow, url: str) -> str:
    action = (
        f"<p><strong>What to do:</strong> {html.escape(a.suggested_action)}</p>"
        if a.suggested_action
        else ""
    )
    return (
        f"<h2 style='margin:0 0 4px;font-size:18px'>{html.escape(a.title)}</h2>"
        f"<p style='margin:0 0 8px;color:#2f5c47'>{html.escape(a.severity)} · {html.escape(a.category)}</p>"
        f"<p>{html.escape(a.detail)}</p>{action}"
        f"<p><a href='{html.escape(url)}' style='color:#377157'>Open in Thicket</a></p>"
    )


def _page(body: str, name: str) -> str:
    return (
        "<!doctype html><html><body style='font-family:Inter,Arial,sans-serif;color:#1f2d26;"
        "background:#f6f8f4;padding:24px'>"
        "<div style='max-width:620px;margin:auto;background:#fff;border-radius:16px;padding:24px'>"
        f"<p>Hello {html.escape(name)},</p>{body}"
        "<p style='font-size:12px;color:#6b7a72'>Thicket sends this because email notifications are "
        "enabled in your preferences. Audio and notes are never included in email.</p>"
        "</div></body></html>"
    )
