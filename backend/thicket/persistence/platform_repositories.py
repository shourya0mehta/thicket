"""Data access for the platform tables (accounts, tenancy, recorders, batches,
rollups, alerts, notifications, reports, files).

Same conventions as :mod:`thicket.persistence.repositories`: every method
opens and closes its own short session and returns detached rows or plain
values, so callers on any thread can use the results without a session.
Nothing here checks permissions; routes resolve the caller's role first and
pass organization ids that are already authorized.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from thicket.ids import LOCAL_ORG_ID, new_id
from thicket.persistence.db import (
    AlertRow,
    AlertRulesRow,
    AnalysisRow,
    BatchItemRow,
    BatchJobRow,
    Database,
    DeploymentRow,
    EventRefRow,
    EventReviewRow,
    InviteRow,
    MembershipRow,
    ModelRunRow,
    NotificationPrefsRow,
    NotificationRow,
    OrganizationRow,
    RawDetectionRow,
    RecorderRow,
    RecordingRow,
    RecordingStatsRow,
    ReportRow,
    RevokedSessionRow,
    SiteDayStatsRow,
    SiteRow,
    SpeciesDayStatsRow,
    UploadedFileRow,
    UserRow,
    alert_open_key,
    utcnow,
)

ROLE_ORDER = {"viewer": 0, "reviewer": 1, "manager": 2, "owner": 3}
OPEN_ALERT_STATUSES = ("open", "acknowledged", "snoozed")
INVITE_TTL = timedelta(days=7)


def role_at_least(role: str, minimum: str) -> bool:
    return ROLE_ORDER.get(role, -1) >= ROLE_ORDER.get(minimum, 99)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60] or "org"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class OpenAlertConflict(Exception):
    """Another unresolved alert already covers this alert's key."""


class LastOwner(Exception):
    """The change would leave the organization without an owner."""


@dataclass
class RecordingView:
    recording: RecordingRow
    analysis: AnalysisRow | None
    stats: RecordingStatsRow | None
    site_name: str | None


@dataclass
class OrgCounts:
    members: int
    sites: int


class PlatformRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ================================================================ users
    def get_user(self, user_id: str) -> UserRow | None:
        with self.db.session() as s:
            return s.get(UserRow, user_id)

    def get_user_by_email(self, email: str) -> UserRow | None:
        with self.db.session() as s:
            return s.execute(
                select(UserRow).where(UserRow.email == normalize_email(email))
            ).scalar_one_or_none()

    def upsert_user(
        self,
        *,
        email: str,
        name: str | None,
        picture_url: str | None = None,
        google_sub: str | None = None,
    ) -> UserRow:
        """Find by Google subject, then by email; create otherwise. Records the login."""
        email = normalize_email(email)
        with self.db.session() as s:
            row = None
            if google_sub:
                row = s.execute(
                    select(UserRow).where(UserRow.google_sub == google_sub)
                ).scalar_one_or_none()
            if row is None:
                row = s.execute(select(UserRow).where(UserRow.email == email)).scalar_one_or_none()
            if row is None:
                row = UserRow(
                    id=new_id("user"),
                    email=email,
                    name=(name or email.split("@")[0])[:200],
                    picture_url=picture_url,
                    google_sub=google_sub,
                )
                s.add(row)
            else:
                if name:
                    row.name = name[:200]
                if picture_url is not None:
                    row.picture_url = picture_url
                if google_sub and not row.google_sub:
                    row.google_sub = google_sub
                row.email = email
            row.last_login_at = utcnow()
            s.flush()
            return row

    # ================================================================= orgs
    def orgs_for_user(self, user_id: str) -> list[tuple[OrganizationRow, str]]:
        with self.db.session() as s:
            rows = s.execute(
                select(OrganizationRow, MembershipRow.role)
                .join(MembershipRow, MembershipRow.organization_id == OrganizationRow.id)
                .where(MembershipRow.user_id == user_id)
                .order_by(OrganizationRow.created_at, OrganizationRow.id)
            ).all()
            return [(o, r) for o, r in rows]

    def roles_for_user(self, user_id: str) -> dict[str, str]:
        with self.db.session() as s:
            rows = s.execute(
                select(MembershipRow.organization_id, MembershipRow.role).where(
                    MembershipRow.user_id == user_id
                )
            ).all()
            return {o: r for o, r in rows}

    def role_in_org(self, user_id: str, org_id: str) -> str | None:
        with self.db.session() as s:
            m = s.get(MembershipRow, (org_id, user_id))
            return m.role if m else None

    def get_org(self, org_id: str) -> OrganizationRow | None:
        with self.db.session() as s:
            return s.get(OrganizationRow, org_id)

    def org_counts(self, org_ids: Iterable[str]) -> dict[str, OrgCounts]:
        ids = list(org_ids)
        if not ids:
            return {}
        with self.db.session() as s:
            members = dict(
                s.execute(
                    select(MembershipRow.organization_id, func.count())
                    .where(MembershipRow.organization_id.in_(ids))
                    .group_by(MembershipRow.organization_id)
                ).all()
            )
            sites = dict(
                s.execute(
                    select(SiteRow.organization_id, func.count())
                    .where(SiteRow.organization_id.in_(ids))
                    .group_by(SiteRow.organization_id)
                ).all()
            )
        return {i: OrgCounts(int(members.get(i, 0)), int(sites.get(i, 0))) for i in ids}

    def create_org(
        self,
        owner_id: str,
        *,
        name: str,
        kind: str,
        timezone: str,
        country: str | None,
        region: str | None,
    ) -> OrganizationRow:
        with self.db.session() as s:
            base = slugify(name)
            slug = base
            n = 1
            while s.execute(select(OrganizationRow.id).where(OrganizationRow.slug == slug)).first():
                n += 1
                slug = f"{base}-{n}"
            org = OrganizationRow(
                id=new_id("org"),
                name=name,
                slug=slug,
                kind=kind,
                timezone=timezone,
                country=country,
                region=region,
            )
            s.add(org)
            s.flush()
            s.add(MembershipRow(organization_id=org.id, user_id=owner_id, role="owner"))
            s.add(AlertRulesRow(organization_id=org.id, rules={}))
            return org

    def update_org(self, org_id: str, values: dict) -> OrganizationRow | None:
        with self.db.session() as s:
            org = s.get(OrganizationRow, org_id)
            if org is None:
                return None
            for k, v in values.items():
                setattr(org, k, v)
            return org

    def delete_org(self, org_id: str) -> list[str]:
        """Delete an organization and everything in it. Returns analysis ids for asset cleanup."""
        with self.db.session() as s:
            rec_ids = list(
                s.execute(
                    select(RecordingRow.id).where(RecordingRow.organization_id == org_id)
                ).scalars()
            )
            analysis_ids: list[str] = []
            if rec_ids:
                analysis_ids = list(
                    s.execute(
                        select(AnalysisRow.id).where(AnalysisRow.recording_id.in_(rec_ids))
                    ).scalars()
                )
                for aid in analysis_ids:
                    for table in (EventRefRow, EventReviewRow, RawDetectionRow, ModelRunRow):
                        s.execute(delete(table).where(table.analysis_id == aid))
                s.execute(delete(AnalysisRow).where(AnalysisRow.recording_id.in_(rec_ids)))
                s.execute(delete(RecordingRow).where(RecordingRow.id.in_(rec_ids)))
            for table in (
                RecordingStatsRow,
                SiteDayStatsRow,
                SpeciesDayStatsRow,
                NotificationRow,
            ):
                s.execute(delete(table).where(table.organization_id == org_id))
            s.execute(delete(SiteRow).where(SiteRow.organization_id == org_id))
            job_ids = select(BatchJobRow.id).where(BatchJobRow.organization_id == org_id)
            s.execute(delete(BatchItemRow).where(BatchItemRow.job_id.in_(job_ids)))
            for table in (
                DeploymentRow,
                RecorderRow,
                BatchJobRow,
                AlertRow,
                AlertRulesRow,
                ReportRow,
                UploadedFileRow,
                InviteRow,
                MembershipRow,
            ):
                s.execute(delete(table).where(table.organization_id == org_id))
            s.execute(delete(OrganizationRow).where(OrganizationRow.id == org_id))
            return analysis_ids

    def move_org_contents(self, source_id: str, target_id: str) -> dict[str, int]:
        """Move every resource of ``source_id`` into ``target_id`` in one transaction.

        Sites, recorders, deployments, recordings (their analyses, detections and
        reviews follow the recording), batch jobs, rollup rows, alerts, reports and
        uploaded files change organization. The source's notifications and invites
        are dropped; each organization keeps its own alert rules. An unresolved
        alert whose key the target already has open is resolved into it. Returns
        the number of rows moved per kind. Rollups must be rebuilt afterwards: the
        target's time zone decides their local dates.
        """
        moved: dict[str, int] = {}
        with self.db.session() as s:
            for name, table in (
                ("sites", SiteRow),
                ("recorders", RecorderRow),
                ("deployments", DeploymentRow),
                ("recordings", RecordingRow),
                ("batch_jobs", BatchJobRow),
                ("reports", ReportRow),
                ("files", UploadedFileRow),
                ("recording_stats", RecordingStatsRow),
                ("site_days", SiteDayStatsRow),
                ("species_days", SpeciesDayStatsRow),
            ):
                res = s.execute(
                    update(table)
                    .where(table.organization_id == source_id)
                    .values(organization_id=target_id)
                )
                moved[name] = res.rowcount or 0
            analyses = s.execute(
                select(func.count())
                .select_from(AnalysisRow)
                .join(RecordingRow, RecordingRow.id == AnalysisRow.recording_id)
                .where(RecordingRow.organization_id == target_id)
            ).scalar_one()
            moved["analyses_in_target"] = int(analyses)
            taken = set(
                s.execute(
                    select(AlertRow.open_key).where(
                        AlertRow.organization_id == target_id, AlertRow.open_key.is_not(None)
                    )
                ).scalars()
            )
            alerts = list(
                s.execute(select(AlertRow).where(AlertRow.organization_id == source_id)).scalars()
            )
            for a in alerts:
                # Free the source key first: the unique index sees every flush.
                a.open_key = None
            s.flush()
            for a in alerts:
                a.organization_id = target_id
                key = alert_open_key(target_id, a.dedupe_key, a.status)
                if key is not None and key in taken:
                    a.status = "resolved"
                    a.snoozed_until = None
                    a.note = a.note or (
                        "Resolved when the local workspace was adopted: an open alert of the "
                        "organization already covers it."
                    )
                    key = None
                a.open_key = key
                if key is not None:
                    taken.add(key)
            moved["alerts"] = len(alerts)
            for table in (NotificationRow, InviteRow):
                s.execute(delete(table).where(table.organization_id == source_id))
        return moved

    # ============================================================== members
    def members(self, org_id: str) -> list[tuple[MembershipRow, UserRow]]:
        with self.db.session() as s:
            rows = s.execute(
                select(MembershipRow, UserRow)
                .join(UserRow, UserRow.id == MembershipRow.user_id)
                .where(MembershipRow.organization_id == org_id)
                .order_by(MembershipRow.joined_at, UserRow.email)
            ).all()
            return [(m, u) for m, u in rows]

    def member_user_ids(self, org_id: str) -> list[str]:
        with self.db.session() as s:
            return list(
                s.execute(
                    select(MembershipRow.user_id).where(MembershipRow.organization_id == org_id)
                ).scalars()
            )

    def add_member(self, org_id: str, user_id: str, role: str) -> MembershipRow:
        with self.db.session() as s:
            m = s.get(MembershipRow, (org_id, user_id))
            if m is None:
                m = MembershipRow(organization_id=org_id, user_id=user_id, role=role)
                s.add(m)
            elif role_at_least(role, m.role):
                m.role = role
            s.flush()
            return m

    def set_role(self, org_id: str, user_id: str, role: str) -> MembershipRow | None:
        with self.db.session() as s:
            m = s.get(MembershipRow, (org_id, user_id))
            if m is None:
                return None
            m.role = role
            return m

    def _lock_owners(self, s: Session, org_id: str) -> None:
        """Postgres: lock the organization's owner rows so concurrent demotions and
        removals serialize (a no-op on SQLite, whose single writer serializes them)."""
        s.execute(
            select(MembershipRow.user_id)
            .where(MembershipRow.organization_id == org_id, MembershipRow.role == "owner")
            .with_for_update()
        ).all()

    def _another_owner_remains(self, org_id: str):  # type: ignore[no-untyped-def]
        owners = (
            select(func.count())
            .select_from(MembershipRow)
            .where(MembershipRow.organization_id == org_id, MembershipRow.role == "owner")
            .scalar_subquery()
        )
        return or_(MembershipRow.role != "owner", owners > 1)

    def set_role_keeping_an_owner(
        self, org_id: str, user_id: str, role: str
    ) -> MembershipRow | None:
        """Change a role unless that demotes the last owner; the owner count is read
        inside the UPDATE itself, so two owners demoting each other at the same time
        cannot both succeed. None: not a member. Raises :class:`LastOwner`."""
        with self.db.session() as s:
            self._lock_owners(s, org_id)
            q = update(MembershipRow).where(
                MembershipRow.organization_id == org_id, MembershipRow.user_id == user_id
            )
            if role != "owner":
                q = q.where(self._another_owner_remains(org_id))
            res = s.execute(q.values(role=role).execution_options(synchronize_session=False))
            m = s.get(MembershipRow, (org_id, user_id), populate_existing=True)
            if (res.rowcount or 0) == 0:
                if m is None:
                    return None
                raise LastOwner(org_id)
            return m

    def remove_member_keeping_an_owner(self, org_id: str, user_id: str) -> bool:
        """Remove a member unless they are the last owner (checked in the DELETE).
        False: not a member. Raises :class:`LastOwner`."""
        with self.db.session() as s:
            self._lock_owners(s, org_id)
            res = s.execute(
                delete(MembershipRow)
                .where(
                    MembershipRow.organization_id == org_id,
                    MembershipRow.user_id == user_id,
                    self._another_owner_remains(org_id),
                )
                .execution_options(synchronize_session=False)
            )
            if (res.rowcount or 0) == 0:
                if s.get(MembershipRow, (org_id, user_id)) is None:
                    return False
                raise LastOwner(org_id)
            # Notifications carry the whole alert; a former member must not keep them.
            s.execute(
                delete(NotificationRow).where(
                    NotificationRow.organization_id == org_id, NotificationRow.user_id == user_id
                )
            )
            return True

    def owner_count(self, org_id: str) -> int:
        with self.db.session() as s:
            return int(
                s.execute(
                    select(func.count())
                    .select_from(MembershipRow)
                    .where(MembershipRow.organization_id == org_id, MembershipRow.role == "owner")
                ).scalar_one()
            )

    def remove_member(self, org_id: str, user_id: str) -> bool:
        with self.db.session() as s:
            res = s.execute(
                delete(MembershipRow).where(
                    MembershipRow.organization_id == org_id, MembershipRow.user_id == user_id
                )
            )
            # Notifications carry the whole alert (title, detail, sites); a former
            # member must neither read them in the app nor get them in a digest.
            s.execute(
                delete(NotificationRow).where(
                    NotificationRow.organization_id == org_id, NotificationRow.user_id == user_id
                )
            )
            return (res.rowcount or 0) > 0

    # ============================================================== invites
    def create_invite(
        self, org_id: str, *, email: str, role: str, invited_by: str
    ) -> tuple[InviteRow, str]:
        token = secrets.token_urlsafe(32)
        with self.db.session() as s:
            row = InviteRow(
                id=new_id("inv"),
                organization_id=org_id,
                email=normalize_email(email),
                role=role,
                token_hash=hash_token(token),
                invited_by=invited_by,
                expires_at=utcnow() + INVITE_TTL,
            )
            s.add(row)
            s.flush()
            return row, token

    def list_invites(self, org_id: str) -> list[InviteRow]:
        with self.db.session() as s:
            return list(
                s.execute(
                    select(InviteRow)
                    .where(InviteRow.organization_id == org_id)
                    .order_by(InviteRow.created_at.desc(), InviteRow.id)
                ).scalars()
            )

    def get_invite(self, invite_id: str) -> InviteRow | None:
        with self.db.session() as s:
            return s.get(InviteRow, invite_id)

    def delete_invite(self, invite_id: str) -> bool:
        """Delete an invite that nobody accepted yet (atomic with that check)."""
        with self.db.session() as s:
            res = s.execute(
                delete(InviteRow).where(InviteRow.id == invite_id, InviteRow.accepted_at.is_(None))
            )
            return (res.rowcount or 0) > 0

    def invite_by_token(self, token: str) -> InviteRow | None:
        with self.db.session() as s:
            return s.execute(
                select(InviteRow).where(InviteRow.token_hash == hash_token(token))
            ).scalar_one_or_none()

    def accept_invite(self, invite_id: str, user_id: str) -> InviteRow | None:
        with self.db.session() as s:
            row = s.get(InviteRow, invite_id)
            if row is None:
                return None
            row.accepted_at = utcnow()
            row.accepted_by = user_id
            m = s.get(MembershipRow, (row.organization_id, user_id))
            if m is None:
                s.add(
                    MembershipRow(
                        organization_id=row.organization_id, user_id=user_id, role=row.role
                    )
                )
            elif role_at_least(row.role, m.role):
                m.role = row.role
            return row

    # ============================================================= sessions
    def revoke_session(self, session_id: str, user_id: str, expires_at: datetime) -> None:
        with self.db.session() as s:
            if s.get(RevokedSessionRow, session_id) is None:
                s.add(
                    RevokedSessionRow(session_id=session_id, user_id=user_id, expires_at=expires_at)
                )

    def is_session_revoked(self, session_id: str) -> bool:
        with self.db.session() as s:
            return s.get(RevokedSessionRow, session_id) is not None

    def prune_revoked_sessions(self, now: datetime | None = None) -> int:
        now = now or utcnow()
        with self.db.session() as s:
            res = s.execute(delete(RevokedSessionRow).where(RevokedSessionRow.expires_at < now))
            return res.rowcount or 0

    # ================================================================ sites
    def list_sites(self, org_id: str) -> list[SiteRow]:
        with self.db.session() as s:
            return list(
                s.execute(
                    select(SiteRow)
                    .where(SiteRow.organization_id == org_id)
                    .order_by(SiteRow.name, SiteRow.id)
                ).scalars()
            )

    def get_site(self, site_id: str) -> SiteRow | None:
        with self.db.session() as s:
            return s.get(SiteRow, site_id)

    def get_sites(self, site_ids: Iterable[str]) -> dict[str, SiteRow]:
        ids = list(site_ids)
        if not ids:
            return {}
        with self.db.session() as s:
            return {
                r.id: r for r in s.execute(select(SiteRow).where(SiteRow.id.in_(ids))).scalars()
            }

    def create_site(self, org_id: str, values: dict) -> SiteRow:
        with self.db.session() as s:
            row = SiteRow(id=new_id("site"), organization_id=org_id, **values)
            s.add(row)
            s.flush()
            return row

    def update_site(self, site_id: str, values: dict) -> SiteRow | None:
        with self.db.session() as s:
            row = s.get(SiteRow, site_id)
            if row is None:
                return None
            for k, v in values.items():
                setattr(row, k, v)
            return row

    def site_recording_count(self, site_id: str) -> int:
        with self.db.session() as s:
            return int(
                s.execute(
                    select(func.count())
                    .select_from(RecordingRow)
                    .where(RecordingRow.site_id == site_id)
                ).scalar_one()
            )

    def delete_site(self, site_id: str) -> None:
        with self.db.session() as s:
            s.execute(delete(DeploymentRow).where(DeploymentRow.site_id == site_id))
            s.execute(delete(SiteDayStatsRow).where(SiteDayStatsRow.site_id == site_id))
            s.execute(delete(SpeciesDayStatsRow).where(SpeciesDayStatsRow.site_id == site_id))
            s.execute(delete(SiteRow).where(SiteRow.id == site_id))

    def site_stats(self, site_ids: Sequence[str]) -> dict[str, dict]:
        """recordings, minutes, first/last recording, species counted, per site."""
        if not site_ids:
            return {}
        out: dict[str, dict] = {
            sid: {
                "recordings": 0,
                "minutes_recorded": 0.0,
                "first_recording_at": None,
                "last_recording_at": None,
                "species_counted": 0,
            }
            for sid in site_ids
        }
        with self.db.session() as s:
            rows = s.execute(
                select(
                    RecordingRow.site_id,
                    func.count(),
                    func.sum(RecordingRow.duration_seconds),
                    func.min(RecordingRow.captured_at_utc),
                    func.max(RecordingRow.captured_at_utc),
                )
                .where(RecordingRow.site_id.in_(list(site_ids)))
                .group_by(RecordingRow.site_id)
            ).all()
            for sid, n, dur, first, last in rows:
                out[sid].update(
                    recordings=int(n),
                    minutes_recorded=round(float(dur or 0.0) / 60.0, 2),
                    first_recording_at=_aware(first),
                    last_recording_at=_aware(last),
                )
            sp = s.execute(
                select(
                    SpeciesDayStatsRow.site_id,
                    func.count(func.distinct(SpeciesDayStatsRow.scientific_name)),
                )
                .where(SpeciesDayStatsRow.site_id.in_(list(site_ids)))
                .group_by(SpeciesDayStatsRow.site_id)
            ).all()
            for sid, n in sp:
                out[sid]["species_counted"] = int(n)
        return out

    def find_site_by_name(self, org_id: str, name: str) -> SiteRow | None:
        with self.db.session() as s:
            return s.execute(
                select(SiteRow)
                .where(
                    SiteRow.organization_id == org_id,
                    func.lower(SiteRow.name) == name.strip().lower(),
                )
                .limit(1)
            ).scalar_one_or_none()

    # ============================================================ recorders
    def list_recorders(self, org_id: str) -> list[RecorderRow]:
        with self.db.session() as s:
            return list(
                s.execute(
                    select(RecorderRow)
                    .where(RecorderRow.organization_id == org_id)
                    .order_by(RecorderRow.label, RecorderRow.id)
                ).scalars()
            )

    def get_recorder(self, recorder_id: str) -> RecorderRow | None:
        with self.db.session() as s:
            return s.get(RecorderRow, recorder_id)

    def find_recorder(
        self, org_id: str, *, label: str | None = None, serial: str | None = None
    ) -> RecorderRow | None:
        with self.db.session() as s:
            q = select(RecorderRow).where(RecorderRow.organization_id == org_id)
            if serial:
                q = q.where(func.lower(RecorderRow.serial) == serial.strip().lower())
            elif label:
                q = q.where(func.lower(RecorderRow.label) == label.strip().lower())
            else:
                return None
            return s.execute(q.limit(1)).scalar_one_or_none()

    def create_recorder(self, org_id: str, values: dict) -> RecorderRow:
        with self.db.session() as s:
            row = RecorderRow(id=new_id("rcd"), organization_id=org_id, **values)
            s.add(row)
            s.flush()
            return row

    def update_recorder(self, recorder_id: str, values: dict) -> RecorderRow | None:
        with self.db.session() as s:
            row = s.get(RecorderRow, recorder_id)
            if row is None:
                return None
            for k, v in values.items():
                setattr(row, k, v)
            return row

    def recorder_recording_count(self, recorder_id: str) -> int:
        with self.db.session() as s:
            return int(
                s.execute(
                    select(func.count())
                    .select_from(RecordingRow)
                    .where(RecordingRow.recorder_id == recorder_id)
                ).scalar_one()
            )

    def delete_recorder(self, recorder_id: str) -> None:
        with self.db.session() as s:
            s.execute(delete(DeploymentRow).where(DeploymentRow.recorder_id == recorder_id))
            s.execute(delete(RecorderRow).where(RecorderRow.id == recorder_id))

    def recorder_last_recording(self, recorder_ids: Sequence[str]) -> dict[str, datetime]:
        if not recorder_ids:
            return {}
        with self.db.session() as s:
            rows = s.execute(
                select(RecordingRow.recorder_id, func.max(RecordingRow.captured_at_utc))
                .where(RecordingRow.recorder_id.in_(list(recorder_ids)))
                .group_by(RecordingRow.recorder_id)
            ).all()
            return {rid: _aware(ts) for rid, ts in rows if ts is not None}

    # ========================================================== deployments
    def list_deployments(
        self,
        org_id: str,
        *,
        active: bool | None = None,
        recorder_id: str | None = None,
        site_id: str | None = None,
        now: datetime | None = None,
    ) -> list[DeploymentRow]:
        now = now or utcnow()
        with self.db.session() as s:
            q = select(DeploymentRow).where(DeploymentRow.organization_id == org_id)
            if recorder_id:
                q = q.where(DeploymentRow.recorder_id == recorder_id)
            if site_id:
                q = q.where(DeploymentRow.site_id == site_id)
            if active is True:
                q = q.where(
                    DeploymentRow.started_at <= now,
                    or_(DeploymentRow.ended_at.is_(None), DeploymentRow.ended_at > now),
                )
            elif active is False:
                q = q.where(
                    or_(DeploymentRow.started_at > now, DeploymentRow.ended_at <= now),
                )
            return list(
                s.execute(q.order_by(DeploymentRow.started_at.desc(), DeploymentRow.id)).scalars()
            )

    def get_deployment(self, deployment_id: str) -> DeploymentRow | None:
        with self.db.session() as s:
            return s.get(DeploymentRow, deployment_id)

    def create_deployment(self, org_id: str, values: dict) -> DeploymentRow:
        with self.db.session() as s:
            row = DeploymentRow(id=new_id("dep"), organization_id=org_id, **values)
            s.add(row)
            s.flush()
            return row

    def update_deployment(self, deployment_id: str, values: dict) -> DeploymentRow | None:
        with self.db.session() as s:
            row = s.get(DeploymentRow, deployment_id)
            if row is None:
                return None
            for k, v in values.items():
                setattr(row, k, v)
            return row

    def delete_deployment(self, deployment_id: str) -> bool:
        with self.db.session() as s:
            s.execute(
                update(RecordingRow)
                .where(RecordingRow.deployment_id == deployment_id)
                .values(deployment_id=None)
            )
            res = s.execute(delete(DeploymentRow).where(DeploymentRow.id == deployment_id))
            return (res.rowcount or 0) > 0

    def deployment_for(
        self, recorder_id: str, at: datetime | None, site_id: str | None = None
    ) -> DeploymentRow | None:
        """The deployment of ``recorder_id`` covering ``at`` (or the latest active one)."""
        with self.db.session() as s:
            q = select(DeploymentRow).where(DeploymentRow.recorder_id == recorder_id)
            if site_id:
                q = q.where(DeploymentRow.site_id == site_id)
            if at is not None:
                q = q.where(
                    DeploymentRow.started_at <= at,
                    or_(DeploymentRow.ended_at.is_(None), DeploymentRow.ended_at >= at),
                )
            else:
                q = q.where(DeploymentRow.ended_at.is_(None))
            return s.execute(
                q.order_by(DeploymentRow.started_at.desc()).limit(1)
            ).scalar_one_or_none()

    # =========================================================== recordings
    def attach_recording(self, recording_id: str, values: dict) -> None:
        with self.db.session() as s:
            s.execute(update(RecordingRow).where(RecordingRow.id == recording_id).values(**values))

    def get_recording(self, recording_id: str) -> RecordingView | None:
        with self.db.session() as s:
            rec = s.get(RecordingRow, recording_id)
            if rec is None:
                return None
            return self._view(s, rec)

    def _view(self, s: Session, rec: RecordingRow) -> RecordingView:
        a = s.execute(
            select(AnalysisRow)
            .where(AnalysisRow.recording_id == rec.id)
            .order_by(AnalysisRow.created_at.desc(), AnalysisRow.id)
            .limit(1)
        ).scalar_one_or_none()
        stats = s.get(RecordingStatsRow, rec.id)
        site = s.get(SiteRow, rec.site_id) if rec.site_id else None
        return RecordingView(
            recording=rec,
            analysis=a,
            stats=stats,
            site_name=site.name if site else rec.site_name,
        )

    def list_recordings(
        self,
        org_id: str,
        *,
        site_id: str | None = None,
        recorder_id: str | None = None,
        deployment_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        quality: str | None = None,
        species: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[RecordingView], int]:
        with self.db.session() as s:
            q = select(RecordingRow).where(RecordingRow.organization_id == org_id)
            if site_id:
                q = q.where(RecordingRow.site_id == site_id)
            if recorder_id:
                q = q.where(RecordingRow.recorder_id == recorder_id)
            if deployment_id:
                q = q.where(RecordingRow.deployment_id == deployment_id)
            if since is not None:
                q = q.where(RecordingRow.captured_at_utc >= since)
            if until is not None:
                q = q.where(RecordingRow.captured_at_utc < until)
            if quality or species:
                q = q.join(RecordingStatsRow, RecordingStatsRow.recording_id == RecordingRow.id)
                if quality:
                    q = q.where(RecordingStatsRow.quality_status == quality)
                if species:
                    ids = self._recordings_with_species(s, org_id, species)
                    q = q.where(RecordingRow.id.in_(ids))
            total = int(s.execute(select(func.count()).select_from(q.subquery())).scalar_one())
            rows = list(
                s.execute(
                    q.order_by(
                        RecordingRow.captured_at_utc.desc().nulls_last(),
                        RecordingRow.created_at.desc(),
                        RecordingRow.id,
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).scalars()
            )
            return [self._view(s, r) for r in rows], total

    @staticmethod
    def _recordings_with_species(s: Session, org_id: str, species: str) -> list[str]:
        wanted = species.strip().lower()
        out: list[str] = []
        for rid, sp in s.execute(
            select(RecordingStatsRow.recording_id, RecordingStatsRow.species).where(
                RecordingStatsRow.organization_id == org_id
            )
        ).all():
            for sci, info in (sp or {}).items():
                if sci.lower() == wanted or (info and str(info[0]).lower() == wanted):
                    out.append(rid)
                    break
        return out

    def recordings_for_site(self, site_id: str) -> list[RecordingRow]:
        with self.db.session() as s:
            return list(
                s.execute(
                    select(RecordingRow)
                    .where(RecordingRow.site_id == site_id)
                    .order_by(
                        RecordingRow.captured_at_utc, RecordingRow.created_at, RecordingRow.id
                    )
                ).scalars()
            )

    def recordings_for_recorder(
        self, recorder_id: str, since: datetime | None = None
    ) -> list[RecordingRow]:
        with self.db.session() as s:
            q = select(RecordingRow).where(RecordingRow.recorder_id == recorder_id)
            if since is not None:
                q = q.where(RecordingRow.captured_at_utc >= since)
            return list(
                s.execute(
                    q.order_by(
                        RecordingRow.captured_at_utc, RecordingRow.created_at, RecordingRow.id
                    )
                ).scalars()
            )

    def recordings_for_deployment(self, deployment_id: str) -> list[RecordingRow]:
        with self.db.session() as s:
            return list(
                s.execute(
                    select(RecordingRow)
                    .where(RecordingRow.deployment_id == deployment_id)
                    .order_by(
                        RecordingRow.captured_at_utc, RecordingRow.created_at, RecordingRow.id
                    )
                ).scalars()
            )

    def analysis_ids_for_recording(self, recording_id: str) -> list[str]:
        with self.db.session() as s:
            return list(
                s.execute(
                    select(AnalysisRow.id).where(AnalysisRow.recording_id == recording_id)
                ).scalars()
            )

    def completed_analysis_ids(self, org_id: str | None = None) -> list[str]:
        with self.db.session() as s:
            q = select(AnalysisRow.id).where(AnalysisRow.status == "completed")
            if org_id:
                q = q.join(RecordingRow, RecordingRow.id == AnalysisRow.recording_id).where(
                    RecordingRow.organization_id == org_id
                )
            return list(s.execute(q.order_by(AnalysisRow.created_at, AnalysisRow.id)).scalars())

    def analysis_ids_for_site_day(self, site_id: str, local_date: date) -> list[str]:
        with self.db.session() as s:
            return list(
                s.execute(
                    select(RecordingStatsRow.analysis_id).where(
                        RecordingStatsRow.site_id == site_id,
                        RecordingStatsRow.local_date == local_date,
                    )
                ).scalars()
            )

    def completed_analyses_for_period(
        self,
        org_id: str,
        *,
        site_ids: Sequence[str] | None,
        start: datetime,
        end: datetime,
    ) -> list[tuple[AnalysisRow, RecordingRow]]:
        with self.db.session() as s:
            q = (
                select(AnalysisRow, RecordingRow)
                .join(RecordingRow, RecordingRow.id == AnalysisRow.recording_id)
                .where(
                    RecordingRow.organization_id == org_id,
                    AnalysisRow.status == "completed",
                    func.coalesce(RecordingRow.captured_at_utc, RecordingRow.created_at) >= start,
                    func.coalesce(RecordingRow.captured_at_utc, RecordingRow.created_at) < end,
                )
            )
            if site_ids:
                q = q.where(RecordingRow.site_id.in_(list(site_ids)))
            rows = s.execute(
                q.order_by(RecordingRow.captured_at_utc, RecordingRow.created_at, AnalysisRow.id)
            ).all()
            return [(a, r) for a, r in rows]

    # ============================================================== batches
    def create_job(
        self,
        org_id: str,
        *,
        site_id: str | None,
        deployment_id: str | None,
        recorder_id: str | None,
        settings: dict,
        filenames: Sequence[str],
        created_by: str | None,
    ) -> BatchJobRow:
        with self.db.session() as s:
            job = BatchJobRow(
                id=new_id("job"),
                organization_id=org_id,
                site_id=site_id,
                deployment_id=deployment_id,
                recorder_id=recorder_id,
                status="queued",
                total=len(filenames),
                settings=settings,
                created_by=created_by,
            )
            s.add(job)
            s.flush()
            for i, name in enumerate(filenames):
                s.add(BatchItemRow(job_id=job.id, position=i, filename=name, status="queued"))
            return job

    def get_job(self, job_id: str) -> tuple[BatchJobRow, list[BatchItemRow]] | None:
        with self.db.session() as s:
            job = s.get(BatchJobRow, job_id)
            if job is None:
                return None
            items = list(
                s.execute(
                    select(BatchItemRow)
                    .where(BatchItemRow.job_id == job_id)
                    .order_by(BatchItemRow.position)
                ).scalars()
            )
            return job, items

    def list_jobs(self, org_id: str, limit: int = 20) -> list[BatchJobRow]:
        with self.db.session() as s:
            return list(
                s.execute(
                    select(BatchJobRow)
                    .where(BatchJobRow.organization_id == org_id)
                    .order_by(BatchJobRow.created_at.desc(), BatchJobRow.id)
                    .limit(limit)
                ).scalars()
            )

    def update_item(self, job_id: str, position: int, values: dict) -> None:
        with self.db.session() as s:
            s.execute(
                update(BatchItemRow)
                .where(BatchItemRow.job_id == job_id, BatchItemRow.position == position)
                .values(**values)
            )

    def update_job(self, job_id: str, values: dict) -> None:
        with self.db.session() as s:
            s.execute(update(BatchJobRow).where(BatchJobRow.id == job_id).values(**values))

    def refresh_job_counts(self, job_id: str) -> BatchJobRow | None:
        """Recount items and settle the job status once every item is final."""
        with self.db.session() as s:
            job = s.get(BatchJobRow, job_id)
            if job is None:
                return None
            counts = dict(
                s.execute(
                    select(BatchItemRow.status, func.count())
                    .where(BatchItemRow.job_id == job_id)
                    .group_by(BatchItemRow.status)
                ).all()
            )
            done = int(counts.get("completed", 0))
            failed = int(counts.get("failed", 0))
            skipped = int(counts.get("skipped", 0))
            pending = int(counts.get("queued", 0)) + int(counts.get("processing", 0))
            job.done, job.failed, job.skipped = done, failed, skipped
            if pending == 0 and job.status not in ("failed",):
                job.status = "completed_with_errors" if failed else "completed"
                job.completed_at = job.completed_at or utcnow()
            elif job.status == "queued" and (done or failed or counts.get("processing")):
                job.status = "processing"
            return job

    def analysis_batch_item(self, analysis_id: str) -> tuple[str, int] | None:
        with self.db.session() as s:
            row = s.execute(
                select(BatchItemRow.job_id, BatchItemRow.position).where(
                    BatchItemRow.analysis_id == analysis_id
                )
            ).first()
            return (row[0], row[1]) if row else None

    def mark_interrupted_jobs(self) -> int:
        with self.db.session() as s:
            res = s.execute(
                update(BatchItemRow)
                .where(BatchItemRow.status.in_(("queued", "processing")))
                .values(
                    status="failed",
                    error_code="internal_error",
                    error_message="The upload was interrupted by a server restart.",
                )
            )
            jobs = list(
                s.execute(
                    select(BatchJobRow.id).where(BatchJobRow.status.in_(("queued", "processing")))
                ).scalars()
            )
            n = res.rowcount or 0
        for jid in jobs:
            self.refresh_job_counts(jid)
        return n

    # ============================================================== rollups
    def upsert_recording_stats(self, values: dict) -> None:
        with self.db.session() as s:
            row = s.get(RecordingStatsRow, values["recording_id"])
            if row is None:
                s.add(RecordingStatsRow(**values))
            else:
                for k, v in values.items():
                    setattr(row, k, v)
                row.updated_at = utcnow()

    def delete_recording_stats(self, recording_id: str) -> RecordingStatsRow | None:
        with self.db.session() as s:
            row = s.get(RecordingStatsRow, recording_id)
            if row is not None:
                s.delete(row)
            return row

    def get_recording_stats(self, recording_id: str) -> RecordingStatsRow | None:
        with self.db.session() as s:
            return s.get(RecordingStatsRow, recording_id)

    def stats_for_site_day(self, site_id: str, local_date: date) -> list[RecordingStatsRow]:
        with self.db.session() as s:
            return list(
                s.execute(
                    select(RecordingStatsRow)
                    .where(
                        RecordingStatsRow.site_id == site_id,
                        RecordingStatsRow.local_date == local_date,
                    )
                    .order_by(RecordingStatsRow.captured_at, RecordingStatsRow.recording_id)
                ).scalars()
            )

    def stats_query(
        self,
        org_id: str,
        *,
        site_id: str | None = None,
        site_ids: Sequence[str] | None = None,
        recorder_id: str | None = None,
        deployment_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        hour_bucket: str | None = None,
        limit: int | None = None,
        newest_first: bool = False,
    ) -> list[RecordingStatsRow]:
        with self.db.session() as s:
            q = select(RecordingStatsRow).where(RecordingStatsRow.organization_id == org_id)
            if site_id:
                q = q.where(RecordingStatsRow.site_id == site_id)
            if site_ids:
                q = q.where(RecordingStatsRow.site_id.in_(list(site_ids)))
            if recorder_id:
                q = q.where(RecordingStatsRow.recorder_id == recorder_id)
            if deployment_id:
                q = q.where(RecordingStatsRow.deployment_id == deployment_id)
            if since is not None:
                q = q.where(RecordingStatsRow.captured_at >= since)
            if until is not None:
                q = q.where(RecordingStatsRow.captured_at < until)
            if hour_bucket:
                q = q.where(RecordingStatsRow.hour_bucket == hour_bucket)
            order = (
                (RecordingStatsRow.captured_at.desc(), RecordingStatsRow.recording_id.desc())
                if newest_first
                else (RecordingStatsRow.captured_at, RecordingStatsRow.recording_id)
            )
            q = q.order_by(*order)
            if limit:
                q = q.limit(limit)
            return list(s.execute(q).scalars())

    def all_stats_sites(self, org_id: str | None = None) -> list[tuple[str, date]]:
        with self.db.session() as s:
            q = select(RecordingStatsRow.site_id, RecordingStatsRow.local_date).where(
                RecordingStatsRow.site_id.is_not(None)
            )
            if org_id:
                q = q.where(RecordingStatsRow.organization_id == org_id)
            return list({(sid, d) for sid, d in s.execute(q.distinct()).all()})

    def replace_site_day(
        self,
        site_id: str,
        local_date: date,
        org_id: str,
        day: dict | None,
        species: list[dict],
    ) -> None:
        """Replace the site-day rollup and its species rows (``day=None`` removes them)."""
        with self.db.session() as s:
            s.execute(
                delete(SpeciesDayStatsRow).where(
                    SpeciesDayStatsRow.site_id == site_id,
                    SpeciesDayStatsRow.local_date == local_date,
                )
            )
            s.execute(
                delete(SiteDayStatsRow).where(
                    SiteDayStatsRow.site_id == site_id, SiteDayStatsRow.local_date == local_date
                )
            )
            if day is None:
                return
            s.add(
                SiteDayStatsRow(
                    site_id=site_id, local_date=local_date, organization_id=org_id, **day
                )
            )
            for sp in species:
                s.add(
                    SpeciesDayStatsRow(
                        site_id=site_id, local_date=local_date, organization_id=org_id, **sp
                    )
                )

    def completed_analyses_by_site(self, org_id: str) -> dict[str | None, list[str]]:
        """Completed analysis ids of an organization grouped by their recording's site."""
        with self.db.session() as s:
            rows = s.execute(
                select(AnalysisRow.id, RecordingRow.site_id)
                .join(RecordingRow, RecordingRow.id == AnalysisRow.recording_id)
                .where(RecordingRow.organization_id == org_id, AnalysisRow.status == "completed")
                .order_by(AnalysisRow.created_at, AnalysisRow.id)
            ).all()
        out: dict[str | None, list[str]] = {}
        for aid, site_id in rows:
            out.setdefault(site_id, []).append(aid)
        return out

    def replace_site_rollups(
        self,
        org_id: str,
        site_id: str | None,
        stats: list[dict],
        days: list[tuple[date, dict, list[dict]]],
    ) -> None:
        """Swap one site's recording stats and day rollups in a single transaction
        (``site_id=None``: the organization's recordings without a site)."""
        with self.db.session() as s:
            if site_id is None:
                s.execute(
                    delete(RecordingStatsRow).where(
                        RecordingStatsRow.organization_id == org_id,
                        RecordingStatsRow.site_id.is_(None),
                    )
                )
            else:
                for table in (RecordingStatsRow, SiteDayStatsRow, SpeciesDayStatsRow):
                    s.execute(delete(table).where(table.site_id == site_id))
            s.flush()
            for values in stats:
                s.add(RecordingStatsRow(**values))
            if site_id is not None:
                for day, day_values, species in days:
                    s.add(
                        SiteDayStatsRow(
                            site_id=site_id, local_date=day, organization_id=org_id, **day_values
                        )
                    )
                    for sp in species:
                        s.add(
                            SpeciesDayStatsRow(
                                site_id=site_id, local_date=day, organization_id=org_id, **sp
                            )
                        )

    def delete_rollups_outside(self, org_id: str, keep: set[str | None]) -> None:
        """Drop an organization's rollup rows for sites that no longer have analyses."""
        sites = [k for k in keep if k is not None]
        with self.db.session() as s:
            for table in (RecordingStatsRow, SiteDayStatsRow, SpeciesDayStatsRow):
                q = delete(table).where(table.organization_id == org_id, table.site_id.is_not(None))
                if sites:
                    q = q.where(table.site_id.not_in(sites))
                s.execute(q)
            if None not in keep:
                s.execute(
                    delete(RecordingStatsRow).where(
                        RecordingStatsRow.organization_id == org_id,
                        RecordingStatsRow.site_id.is_(None),
                    )
                )

    def clear_rollups(self, org_id: str | None = None) -> None:
        with self.db.session() as s:
            for table in (SiteDayStatsRow, SpeciesDayStatsRow, RecordingStatsRow):
                q = delete(table)
                if org_id:
                    q = q.where(table.organization_id == org_id)
                s.execute(q)

    def site_days(
        self,
        org_id: str,
        *,
        start: date,
        end: date,
        site_ids: Sequence[str] | None = None,
    ) -> list[SiteDayStatsRow]:
        with self.db.session() as s:
            q = select(SiteDayStatsRow).where(
                SiteDayStatsRow.organization_id == org_id,
                SiteDayStatsRow.local_date >= start,
                SiteDayStatsRow.local_date <= end,
            )
            if site_ids:
                q = q.where(SiteDayStatsRow.site_id.in_(list(site_ids)))
            return list(
                s.execute(q.order_by(SiteDayStatsRow.local_date, SiteDayStatsRow.site_id)).scalars()
            )

    def species_days(
        self,
        org_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        site_ids: Sequence[str] | None = None,
        scientific_name: str | None = None,
    ) -> list[SpeciesDayStatsRow]:
        with self.db.session() as s:
            q = select(SpeciesDayStatsRow).where(SpeciesDayStatsRow.organization_id == org_id)
            if start is not None:
                q = q.where(SpeciesDayStatsRow.local_date >= start)
            if end is not None:
                q = q.where(SpeciesDayStatsRow.local_date <= end)
            if site_ids:
                q = q.where(SpeciesDayStatsRow.site_id.in_(list(site_ids)))
            if scientific_name:
                q = q.where(
                    func.lower(SpeciesDayStatsRow.scientific_name) == scientific_name.lower()
                )
            return list(
                s.execute(
                    q.order_by(
                        SpeciesDayStatsRow.local_date,
                        SpeciesDayStatsRow.site_id,
                        SpeciesDayStatsRow.scientific_name,
                    )
                ).scalars()
            )

    def first_date_with_data(self, org_id: str) -> date | None:
        with self.db.session() as s:
            return s.execute(
                select(func.min(SiteDayStatsRow.local_date)).where(
                    SiteDayStatsRow.organization_id == org_id
                )
            ).scalar_one()

    # =============================================================== alerts
    def alert_rules(self, org_id: str) -> dict:
        with self.db.session() as s:
            row = s.get(AlertRulesRow, org_id)
            return dict(row.rules or {}) if row else {}

    def put_alert_rules(self, org_id: str, rules: dict) -> None:
        with self.db.session() as s:
            row = s.get(AlertRulesRow, org_id)
            if row is None:
                s.add(AlertRulesRow(organization_id=org_id, rules=rules))
            else:
                row.rules = rules
                row.updated_at = utcnow()

    def get_alert(self, alert_id: str) -> AlertRow | None:
        with self.db.session() as s:
            return s.get(AlertRow, alert_id)

    def find_open_alert(self, org_id: str, dedupe_key: str) -> AlertRow | None:
        with self.db.session() as s:
            return s.execute(
                select(AlertRow)
                .where(
                    AlertRow.organization_id == org_id,
                    AlertRow.dedupe_key == dedupe_key,
                    AlertRow.status.in_(OPEN_ALERT_STATUSES),
                )
                .order_by(AlertRow.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

    def resolved_alert_covering(
        self, org_id: str, dedupe_key: str, recording_ids: Sequence[str]
    ) -> AlertRow | None:
        """A resolved alert with this key whose evidence includes every one of ``recording_ids``."""
        wanted = set(recording_ids)
        with self.db.session() as s:
            rows = s.execute(
                select(AlertRow)
                .where(
                    AlertRow.organization_id == org_id,
                    AlertRow.dedupe_key == dedupe_key,
                    AlertRow.status == "resolved",
                )
                .order_by(AlertRow.updated_at.desc())
                .limit(50)
            ).scalars()
            for row in rows:
                if wanted <= set(row.recording_ids or []):
                    return row
        return None

    def insert_alert(self, values: dict) -> AlertRow | None:
        """Insert an alert; None when another unresolved alert already holds its key
        (a concurrent insert won; the caller updates that one instead)."""
        values = dict(values)
        values["open_key"] = alert_open_key(
            values["organization_id"], values["dedupe_key"], values.get("status", "open")
        )
        try:
            with self.db.session() as s:
                row = AlertRow(id=new_id("alr"), **values)
                s.add(row)
                s.flush()
                return row
        except IntegrityError:
            return None

    def update_alert(self, alert_id: str, values: dict) -> AlertRow | None:
        """Raises :class:`OpenAlertConflict` when reopening would duplicate an open alert."""
        try:
            with self.db.session() as s:
                row = s.get(AlertRow, alert_id)
                if row is None:
                    return None
                for k, v in values.items():
                    setattr(row, k, v)
                row.open_key = alert_open_key(row.organization_id, row.dedupe_key, row.status)
                row.updated_at = utcnow()
                s.flush()
                return row
        except IntegrityError as exc:
            raise OpenAlertConflict(alert_id) from exc

    def list_alerts(
        self,
        org_id: str,
        *,
        status: str | None = None,
        category: str | None = None,
        kind: str | None = None,
        site_id: str | None = None,
        recorder_id: str | None = None,
        open_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AlertRow], int, dict[str, int], dict[str, int]]:
        with self.db.session() as s:
            base = select(AlertRow).where(AlertRow.organization_id == org_id)
            if site_id:
                base = base.where(AlertRow.site_id == site_id)
            if recorder_id:
                base = base.where(AlertRow.recorder_id == recorder_id)
            if category:
                base = base.where(AlertRow.category == category)
            if kind:
                base = base.where(AlertRow.kind == kind)
            by_status = self._counts(s, base, AlertRow.status)
            by_category = self._counts(s, base, AlertRow.category)
            q = base
            if status:
                q = q.where(AlertRow.status == status)
            elif open_only:
                q = q.where(AlertRow.status.in_(OPEN_ALERT_STATUSES))
            total = int(s.execute(select(func.count()).select_from(q.subquery())).scalar_one())
            rows = list(
                s.execute(
                    q.order_by(AlertRow.last_seen_at.desc(), AlertRow.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).scalars()
            )
            return rows, total, by_status, by_category

    @staticmethod
    def _counts(s: Session, base, column) -> dict[str, int]:  # type: ignore[no-untyped-def]
        sub = base.subquery()
        col = getattr(sub.c, column.key)
        return {
            str(k): int(v)
            for k, v in s.execute(select(col, func.count()).group_by(col)).all()
            if k is not None
        }

    def open_alert_counts(
        self, org_id: str, *, by: str = "site_id"
    ) -> dict[str | None, dict[str, int]]:
        """open alerts per site (or recorder): {id: {severity: n}}."""
        col = AlertRow.site_id if by == "site_id" else AlertRow.recorder_id
        with self.db.session() as s:
            rows = s.execute(
                select(col, AlertRow.severity, func.count())
                .where(AlertRow.organization_id == org_id, AlertRow.status.in_(OPEN_ALERT_STATUSES))
                .group_by(col, AlertRow.severity)
            ).all()
        out: dict[str | None, dict[str, int]] = {}
        for key, sev, n in rows:
            out.setdefault(key, {})[sev] = int(n)
        return out

    def open_alerts_for(
        self, org_id: str, *, site_id: str | None = None, recorder_id: str | None = None
    ) -> list[AlertRow]:
        with self.db.session() as s:
            q = select(AlertRow).where(
                AlertRow.organization_id == org_id, AlertRow.status.in_(OPEN_ALERT_STATUSES)
            )
            if site_id:
                q = q.where(AlertRow.site_id == site_id)
            if recorder_id:
                q = q.where(AlertRow.recorder_id == recorder_id)
            return list(s.execute(q.order_by(AlertRow.last_seen_at.desc())).scalars())

    def detach_recording_from_alerts(self, org_id: str, recording_id: str) -> int:
        """Drop a deleted recording from its alerts' evidence; an open alert left with
        no recording behind it is resolved (its evidence is gone). Returns alerts changed."""
        now = utcnow()
        changed = 0
        with self.db.session() as s:
            rows = s.execute(select(AlertRow).where(AlertRow.organization_id == org_id)).scalars()
            for a in rows:
                ids = list(a.recording_ids or [])
                if recording_id not in ids:
                    continue
                a.recording_ids = [i for i in ids if i != recording_id]
                if not a.recording_ids and a.status in OPEN_ALERT_STATUSES:
                    a.status = "resolved"
                    a.open_key = None
                    a.snoozed_until = None
                    a.note = a.note or (
                        "Resolved automatically: the recordings behind this alert were deleted."
                    )
                a.updated_at = now
                changed += 1
        return changed

    def unsnooze_due(self, now: datetime | None = None) -> int:
        now = now or utcnow()
        with self.db.session() as s:
            res = s.execute(
                update(AlertRow)
                .where(AlertRow.status == "snoozed", AlertRow.snoozed_until <= now)
                .values(status="open", snoozed_until=None, updated_at=now)
            )
            return res.rowcount or 0

    def all_org_ids(self) -> list[str]:
        with self.db.session() as s:
            return list(
                s.execute(select(OrganizationRow.id).order_by(OrganizationRow.created_at)).scalars()
            )

    # ======================================================== notifications
    def notification_prefs(self, user_id: str) -> dict:
        with self.db.session() as s:
            row = s.get(NotificationPrefsRow, user_id)
            return dict(row.prefs or {}) if row else {}

    def put_notification_prefs(self, user_id: str, prefs: dict) -> None:
        with self.db.session() as s:
            row = s.get(NotificationPrefsRow, user_id)
            if row is None:
                s.add(NotificationPrefsRow(user_id=user_id, prefs=prefs))
            else:
                row.prefs = prefs
                row.updated_at = utcnow()

    def prefs_for_users(self, user_ids: Sequence[str]) -> dict[str, dict]:
        if not user_ids:
            return {}
        with self.db.session() as s:
            rows = s.execute(
                select(NotificationPrefsRow).where(NotificationPrefsRow.user_id.in_(list(user_ids)))
            ).scalars()
            return {r.user_id: dict(r.prefs or {}) for r in rows}

    def add_notification(
        self,
        *,
        user_id: str,
        org_id: str,
        alert_id: str,
        channel: str,
        digest: str | None = None,
        sent_at: datetime | None = None,
    ) -> NotificationRow:
        with self.db.session() as s:
            row = NotificationRow(
                id=new_id("ntf"),
                user_id=user_id,
                organization_id=org_id,
                alert_id=alert_id,
                channel=channel,
                digest=digest,
                sent_at=sent_at,
            )
            s.add(row)
            s.flush()
            return row

    def has_notification(self, user_id: str, alert_id: str, channel: str) -> bool:
        with self.db.session() as s:
            return (
                s.execute(
                    select(NotificationRow.id).where(
                        NotificationRow.user_id == user_id,
                        NotificationRow.alert_id == alert_id,
                        NotificationRow.channel == channel,
                    )
                ).first()
                is not None
            )

    def list_notifications(
        self,
        user_id: str,
        *,
        unread_only: bool = False,
        limit: int = 100,
        org_id: str | None = None,
    ) -> list[tuple[NotificationRow, AlertRow]]:
        with self.db.session() as s:
            q = (
                select(NotificationRow, AlertRow)
                .join(AlertRow, AlertRow.id == NotificationRow.alert_id)
                .where(NotificationRow.user_id == user_id, NotificationRow.channel == "in_app")
            )
            if unread_only:
                q = q.where(NotificationRow.read_at.is_(None))
            if org_id:
                q = q.where(NotificationRow.organization_id == org_id)
            rows = s.execute(
                q.order_by(NotificationRow.created_at.desc(), NotificationRow.id).limit(limit)
            ).all()
            return [(n, a) for n, a in rows]

    def unread_count(self, user_id: str, org_id: str | None = None) -> int:
        with self.db.session() as s:
            q = (
                select(func.count())
                .select_from(NotificationRow)
                .where(
                    NotificationRow.user_id == user_id,
                    NotificationRow.channel == "in_app",
                    NotificationRow.read_at.is_(None),
                )
            )
            if org_id:
                q = q.where(NotificationRow.organization_id == org_id)
            return int(s.execute(q).scalar_one())

    def mark_read(
        self, user_id: str, ids: Sequence[str] | None, all_: bool, org_id: str | None = None
    ) -> int:
        with self.db.session() as s:
            q = (
                update(NotificationRow)
                .where(NotificationRow.user_id == user_id, NotificationRow.read_at.is_(None))
                .values(read_at=utcnow())
            )
            if org_id:
                q = q.where(NotificationRow.organization_id == org_id)
            if not all_:
                if not ids:
                    return 0
                q = q.where(NotificationRow.id.in_(list(ids)))
            return s.execute(q).rowcount or 0

    def pending_email_notifications(
        self, digest: str
    ) -> list[tuple[NotificationRow, AlertRow, UserRow]]:
        with self.db.session() as s:
            rows = s.execute(
                select(NotificationRow, AlertRow, UserRow)
                .join(AlertRow, AlertRow.id == NotificationRow.alert_id)
                .join(UserRow, UserRow.id == NotificationRow.user_id)
                .where(
                    NotificationRow.channel == "email",
                    NotificationRow.digest == digest,
                    NotificationRow.sent_at.is_(None),
                )
                .order_by(UserRow.id, NotificationRow.created_at)
            ).all()
            return [(n, a, u) for n, a, u in rows]

    def mark_sent(self, notification_ids: Sequence[str]) -> None:
        if not notification_ids:
            return
        with self.db.session() as s:
            s.execute(
                update(NotificationRow)
                .where(NotificationRow.id.in_(list(notification_ids)))
                .values(sent_at=utcnow())
            )

    # ============================================================== reports
    def create_report(self, values: dict) -> ReportRow:
        with self.db.session() as s:
            row = ReportRow(id=new_id("rpt"), **values)
            s.add(row)
            s.flush()
            return row

    def get_report(self, report_id: str) -> ReportRow | None:
        with self.db.session() as s:
            return s.get(ReportRow, report_id)

    def list_reports(self, org_id: str, limit: int = 100) -> list[ReportRow]:
        with self.db.session() as s:
            return list(
                s.execute(
                    select(ReportRow)
                    .where(ReportRow.organization_id == org_id)
                    .order_by(ReportRow.created_at.desc(), ReportRow.id)
                    .limit(limit)
                ).scalars()
            )

    def update_report(self, report_id: str, values: dict) -> ReportRow | None:
        with self.db.session() as s:
            row = s.get(ReportRow, report_id)
            if row is None:
                return None
            for k, v in values.items():
                setattr(row, k, v)
            return row

    def delete_report(self, report_id: str) -> ReportRow | None:
        with self.db.session() as s:
            row = s.get(ReportRow, report_id)
            if row is not None:
                s.delete(row)
            return row

    def mark_interrupted_reports(self) -> int:
        with self.db.session() as s:
            res = s.execute(
                update(ReportRow)
                .where(ReportRow.status.in_(("queued", "rendering")))
                .values(
                    status="failed",
                    error_message="Rendering was interrupted by a server restart. Create it again.",
                    completed_at=utcnow(),
                )
            )
            return res.rowcount or 0

    def reviews_for_analyses(self, analysis_ids: Sequence[str]) -> list[EventReviewRow]:
        if not analysis_ids:
            return []
        with self.db.session() as s:
            return list(
                s.execute(
                    select(EventReviewRow)
                    .where(EventReviewRow.analysis_id.in_(list(analysis_ids)))
                    .order_by(EventReviewRow.updated_at, EventReviewRow.event_id)
                ).scalars()
            )

    # ================================================================ files
    def create_file(self, values: dict) -> UploadedFileRow:
        with self.db.session() as s:
            row = UploadedFileRow(id=new_id("file"), **values)
            s.add(row)
            s.flush()
            return row

    def get_file(self, file_id: str) -> UploadedFileRow | None:
        with self.db.session() as s:
            return s.get(UploadedFileRow, file_id)

    # ============================================================= helpers
    def users_by_ids(self, user_ids: Iterable[str]) -> dict[str, UserRow]:
        ids = list(set(user_ids))
        if not ids:
            return {}
        with self.db.session() as s:
            return {
                u.id: u for u in s.execute(select(UserRow).where(UserRow.id.in_(ids))).scalars()
            }

    def org_of_recording(self, recording_id: str) -> str | None:
        with self.db.session() as s:
            row = s.get(RecordingRow, recording_id)
            return row.organization_id if row else None

    def recording_id_for_analysis(self, analysis_id: str) -> str | None:
        with self.db.session() as s:
            row = s.get(AnalysisRow, analysis_id)
            return row.recording_id if row else None

    def org_of_analysis(self, analysis_id: str) -> str | None:
        with self.db.session() as s:
            row = s.execute(
                select(RecordingRow.organization_id)
                .join(AnalysisRow, AnalysisRow.recording_id == RecordingRow.id)
                .where(AnalysisRow.id == analysis_id)
            ).first()
            return row[0] if row else None

    def local_org_id(self) -> str:
        return LOCAL_ORG_ID

    def set_review_author(self, event_id: str, user_id: str | None) -> None:
        if not user_id:
            return
        with self.db.session() as s:
            s.execute(
                update(EventReviewRow)
                .where(EventReviewRow.event_id == event_id)
                .values(reviewed_by=user_id)
            )

    def analysis_ids_in_org(self, org_ids: Sequence[str], limit: int) -> list[str]:
        with self.db.session() as s:
            return list(
                s.execute(
                    select(AnalysisRow.id)
                    .join(RecordingRow, RecordingRow.id == AnalysisRow.recording_id)
                    .where(RecordingRow.organization_id.in_(list(org_ids)))
                    .order_by(AnalysisRow.created_at.desc(), AnalysisRow.id)
                    .limit(limit)
                ).scalars()
            )

    def site_recording_counts(self, org_id: str) -> dict[str, int]:
        with self.db.session() as s:
            rows = s.execute(
                select(RecordingRow.site_id, func.count())
                .where(RecordingRow.organization_id == org_id, RecordingRow.site_id.is_not(None))
                .group_by(RecordingRow.site_id)
            ).all()
            return {sid: int(n) for sid, n in rows}

    def duplicate_capture_times(
        self, deployment_id: str | None, recorder_id: str | None
    ) -> list[tuple[datetime, int]]:
        """captured_at values shared by more than one recording of a recorder/deployment."""
        if not (deployment_id or recorder_id):
            return []
        with self.db.session() as s:
            q = select(RecordingRow.captured_at_utc, func.count()).where(
                RecordingRow.captured_at_utc.is_not(None)
            )
            q = (
                q.where(RecordingRow.deployment_id == deployment_id)
                if deployment_id
                else q.where(RecordingRow.recorder_id == recorder_id)
            )
            rows = s.execute(
                q.group_by(RecordingRow.captured_at_utc).having(func.count() > 1)
            ).all()
            return [(_aware(ts), int(n)) for ts, n in rows if ts is not None]


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
