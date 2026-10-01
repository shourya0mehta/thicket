"""Organizations, members, invites, sites, recorders, deployments and
recordings: validation and the conversion from rows to API models.

Routes resolve permissions first (see :mod:`thicket.api.deps`) and then call
these methods with organization ids that are already authorized. Health
summaries on sites and recorders come from open alerts: ``attention`` when
any open alert is a warning, ``watch`` when any is a watch, ``good`` when the
resource has recordings and no open alerts, ``unknown`` without recordings.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime

from thicket.api.platform_schemas import (
    AuthMode,
    Deployment,
    DeploymentCreate,
    DeploymentUpdate,
    Invite,
    Me,
    Membership,
    Organization,
    OrganizationCreate,
    OrganizationUpdate,
    Recorder,
    RecorderCreate,
    RecorderUpdate,
    RecordingPage,
    RecordingSummary,
    Role,
    Site,
    SiteCreate,
    SiteStats,
    SiteUpdate,
    Telemetry,
    User,
)
from thicket.api.schemas import AnalysisStatus, QualityStatus
from thicket.config import Settings
from thicket.errors import conflict, invalid_parameter, not_found
from thicket.ids import is_valid_id
from thicket.persistence.db import (
    DeploymentRow,
    InviteRow,
    OrganizationRow,
    RecorderRow,
    SiteRow,
    UserRow,
    as_utc,
)
from thicket.persistence.platform_repositories import PlatformRepository, RecordingView
from thicket.persistence.repositories import Repository
from thicket.services.analysis import AnalysisService
from thicket.services.auth import Principal
from thicket.services.intake import clean_text
from thicket.services.params import parse_timezone

log = logging.getLogger(__name__)


def health_from_counts(counts: dict[str, int] | None, has_recordings: bool) -> str:
    """Open warning alerts mean attention, open watch alerts mean watch; info does not count."""
    if counts and counts.get("warning"):
        return "attention"
    if counts and counts.get("watch"):
        return "watch"
    return "good" if has_recordings else "unknown"


def user_model(u: UserRow) -> User:
    return User(
        id=u.id,
        email=u.email,
        name=u.name,
        picture_url=u.picture_url,
        created_at=u.created_at,
        last_login_at=u.last_login_at,
    )


def _clean(values: dict, limits: dict[str, int]) -> dict:
    out = {}
    for k, v in values.items():
        out[k] = clean_text(v, limits[k], k) if k in limits and isinstance(v, str) else v
    return out


SITE_TEXT = {"name": 120, "fsa_field_number": 80, "paddock_id": 80, "notes": 4000}
RECORDER_TEXT = {"label": 120, "model": 120, "serial": 120, "firmware": 80, "notes": 4000}
DEPLOYMENT_TEXT = {
    "orientation": 120,
    "gain_setting": 80,
    "schedule_description": 300,
    "notes": 4000,
}


class PlatformService:
    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        platform: PlatformRepository,
        analysis: AnalysisService,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.platform = platform
        self.analysis = analysis

    # ------------------------------------------------------------ orgs
    def org_model(self, org: OrganizationRow, counts=None) -> Organization:  # type: ignore[no-untyped-def]
        if counts is None:
            counts = self.platform.org_counts([org.id]).get(org.id)
        return Organization(
            id=org.id,
            name=org.name,
            slug=org.slug,
            kind=org.kind,  # type: ignore[arg-type]
            timezone=org.timezone,
            country=org.country,
            region=org.region,
            created_at=org.created_at,
            member_count=counts.members if counts else 0,
            site_count=counts.sites if counts else 0,
        )

    def orgs_for(self, p: Principal) -> list[Organization]:
        rows = self.platform.orgs_for_user(p.user_id)
        counts = self.platform.org_counts([o.id for o, _ in rows])
        return [self.org_model(o, counts.get(o.id)) for o, _ in rows]

    def me(self, p: Principal, auth_mode: str, unread: int) -> Me:
        orgs = self.orgs_for(p)
        return Me(
            user=user_model(p.user),
            organizations=orgs,
            roles={k: Role(v) for k, v in p.roles.items() if k in {o.id for o in orgs}},
            auth_mode=AuthMode(auth_mode),
            unread_notifications=unread,
        )

    def create_org(self, p: Principal, body: OrganizationCreate) -> Organization:
        tz = parse_timezone(body.timezone) or "UTC"
        name = clean_text(body.name, 120, "name")
        if not name:
            raise invalid_parameter("name is required.", field="name")
        org = self.platform.create_org(
            p.user_id,
            name=name,
            kind=body.kind.value,
            timezone=tz,
            country=clean_text(body.country, 80, "country"),
            region=clean_text(body.region, 80, "region"),
        )
        p.roles[org.id] = "owner"
        log.info("organization created", extra={"org_id": org.id, "user_id": p.user_id})
        return self.org_model(org)

    def update_org(self, org_id: str, body: OrganizationUpdate) -> Organization:
        values = body.model_dump(exclude_unset=True)
        if "timezone" in values:
            values["timezone"] = parse_timezone(values["timezone"]) or "UTC"
        if "kind" in values and values["kind"] is not None:
            values["kind"] = body.kind.value  # type: ignore[union-attr]
        if "name" in values:
            name = clean_text(values["name"], 120, "name")
            if not name:
                raise invalid_parameter("name must not be empty.", field="name")
            values["name"] = name
        for k in ("country", "region"):
            if k in values:
                values[k] = clean_text(values[k], 80, k)
        org = self.platform.update_org(org_id, values)
        if org is None:
            raise not_found("No organization with that id exists.")
        return self.org_model(org)

    def delete_org(self, org_id: str, storage) -> None:  # type: ignore[no-untyped-def]
        analysis_ids = self.platform.delete_org(org_id)
        for aid in analysis_ids:
            storage.spectrogram_path(aid).unlink(missing_ok=True)
            storage.audio_path(aid).unlink(missing_ok=True)
            shutil.rmtree(storage.analysis_tmp(aid), ignore_errors=True)
        log.info("organization deleted", extra={"org_id": org_id, "analyses": len(analysis_ids)})

    # --------------------------------------------------------- members
    def members(self, org_id: str) -> list[Membership]:
        return [
            Membership(user=user_model(u), role=Role(m.role), joined_at=m.joined_at)
            for m, u in self.platform.members(org_id)
        ]

    def set_role(self, org_id: str, user_id: str, role: Role) -> Membership:
        current = self.platform.role_in_org(user_id, org_id)
        if current is None:
            raise not_found("That user is not a member of this organization.")
        if current == "owner" and role != Role.owner and self.platform.owner_count(org_id) <= 1:
            raise conflict("An organization needs at least one owner.")
        self.platform.set_role(org_id, user_id, role.value)
        for m, u in self.platform.members(org_id):
            if u.id == user_id:
                return Membership(user=user_model(u), role=Role(m.role), joined_at=m.joined_at)
        raise not_found("That user is not a member of this organization.")

    def remove_member(self, org_id: str, user_id: str) -> None:
        current = self.platform.role_in_org(user_id, org_id)
        if current is None:
            raise not_found("That user is not a member of this organization.")
        if current == "owner" and self.platform.owner_count(org_id) <= 1:
            raise conflict("The last owner cannot leave. Make someone else an owner first.")
        self.platform.remove_member(org_id, user_id)

    # --------------------------------------------------------- invites
    def invite_model(self, row: InviteRow, accept_url: str | None = None) -> Invite:
        return Invite(
            id=row.id,
            organization_id=row.organization_id,
            email=row.email,
            role=Role(row.role),
            invited_by=row.invited_by,
            expires_at=row.expires_at,
            accepted_at=row.accepted_at,
            accept_url=accept_url,
        )

    def create_invite(self, org_id: str, inviter: Principal, email: str, role: Role) -> Invite:
        email = (email or "").strip().lower()
        if "@" not in email or len(email) > 320 or " " in email:
            raise invalid_parameter("Enter a valid email address.", field="email")
        if role == Role.owner and not inviter.has_role(org_id, "owner"):
            raise invalid_parameter("Only an owner can invite another owner.", field="role")
        row, token = self.platform.create_invite(
            org_id, email=email, role=role.value, invited_by=inviter.user_id
        )
        log.info("invite created", extra={"invite_id": row.id, "org_id": org_id})
        return self.invite_model(row, f"{self.settings.frontend_url}/#/invite/{token}")

    def accept_invite(self, token: str, p: Principal) -> Organization:
        if not token or len(token) > 200:
            raise not_found("This invite link is not valid.")
        row = self.platform.invite_by_token(token)
        if row is None:
            raise not_found("This invite link is not valid.")
        now = datetime.now(UTC)
        if row.accepted_at is not None:
            raise conflict("This invite was already used.")
        if row.expires_at < now:
            raise conflict("This invite has expired. Ask for a new one.")
        if row.email != p.user.email.lower():
            raise invalid_parameter(
                "This invite was sent to a different email address. Sign in with that address."
            )
        self.platform.accept_invite(row.id, p.user_id)
        p.roles[row.organization_id] = max(
            (p.roles.get(row.organization_id, "viewer"), row.role),
            key=lambda r: ["viewer", "reviewer", "manager", "owner"].index(r),
        )
        org = self.platform.get_org(row.organization_id)
        if org is None:
            raise not_found("The organization no longer exists.")
        return self.org_model(org)

    # ------------------------------------------------------------ sites
    def site_models(self, org_id: str, rows: Sequence[SiteRow]) -> list[Site]:
        stats = self.platform.site_stats([r.id for r in rows])
        alerts = self.platform.open_alert_counts(org_id, by="site_id")
        out = []
        for r in rows:
            st = stats.get(r.id, {})
            counts = alerts.get(r.id)
            out.append(
                Site(
                    id=r.id,
                    organization_id=r.organization_id or org_id,
                    name=r.name,
                    latitude=r.latitude,
                    longitude=r.longitude,
                    habitat_type=r.habitat_type,  # type: ignore[arg-type]
                    area_hectares=r.area_hectares,
                    fsa_field_number=r.fsa_field_number,
                    paddock_id=r.paddock_id,
                    notes=r.notes,
                    created_at=r.created_at,
                    stats=SiteStats(
                        recordings=int(st.get("recordings", 0)),
                        minutes_recorded=float(st.get("minutes_recorded", 0.0)),
                        first_recording_at=st.get("first_recording_at"),
                        last_recording_at=st.get("last_recording_at"),
                        species_counted=int(st.get("species_counted", 0)),
                        open_alerts=int(sum((counts or {}).values())),
                        health=health_from_counts(counts, int(st.get("recordings", 0)) > 0),  # type: ignore[arg-type]
                    ),
                )
            )
        return out

    def site_model(self, row: SiteRow) -> Site:
        return self.site_models(row.organization_id or "", [row])[0]

    def list_sites(self, org_id: str) -> list[Site]:
        return self.site_models(org_id, self.platform.list_sites(org_id))

    def create_site(self, org_id: str, body: SiteCreate) -> Site:
        values = _clean(body.model_dump(), SITE_TEXT)
        if values.get("habitat_type") is not None:
            values["habitat_type"] = body.habitat_type.value  # type: ignore[union-attr]
        if not values.get("name"):
            raise invalid_parameter("name is required.", field="name")
        if (values.get("latitude") is None) != (values.get("longitude") is None):
            raise invalid_parameter("Provide both latitude and longitude, or neither.")
        values["auto_created"] = False
        return self.site_model(self.platform.create_site(org_id, values))

    def update_site(self, site: SiteRow, body: SiteUpdate) -> Site:
        values = _clean(body.model_dump(exclude_unset=True), SITE_TEXT)
        if "habitat_type" in values and values["habitat_type"] is not None:
            values["habitat_type"] = body.habitat_type.value  # type: ignore[union-attr]
        if "name" in values and not values["name"]:
            raise invalid_parameter("name must not be empty.", field="name")
        lat = values.get("latitude", site.latitude)
        lon = values.get("longitude", site.longitude)
        if (lat is None) != (lon is None):
            raise invalid_parameter("Provide both latitude and longitude, or neither.")
        values["auto_created"] = False
        row = self.platform.update_site(site.id, values)
        assert row is not None
        return self.site_model(row)

    def delete_site(self, site: SiteRow) -> None:
        n = self.platform.site_recording_count(site.id)
        if n:
            raise conflict(
                f"This site has {n} recording{'s' if n != 1 else ''}. Delete them first, or end its "
                "deployments to archive it.",
                detail={"recordings": n},
            )
        self.platform.delete_site(site.id)

    # -------------------------------------------------------- recorders
    def recorder_models(self, org_id: str, rows: Sequence[RecorderRow]) -> list[Recorder]:
        alerts = self.platform.open_alert_counts(org_id, by="recorder_id")
        last = self.platform.recorder_last_recording([r.id for r in rows])
        active = {
            d.recorder_id: d.id
            for d in sorted(
                self.platform.list_deployments(org_id, active=True), key=lambda d: d.started_at
            )
        }
        out = []
        for r in rows:
            counts = alerts.get(r.id)
            out.append(
                Recorder(
                    id=r.id,
                    organization_id=r.organization_id,
                    label=r.label,
                    make=r.make,  # type: ignore[arg-type]
                    model=r.model,
                    serial=r.serial,
                    firmware=r.firmware,
                    notes=r.notes,
                    created_at=r.created_at,
                    active_deployment_id=active.get(r.id),
                    health=health_from_counts(counts, r.id in last),  # type: ignore[arg-type]
                    last_recording_at=last.get(r.id),
                )
            )
        return out

    def recorder_model(self, row: RecorderRow) -> Recorder:
        return self.recorder_models(row.organization_id, [row])[0]

    def create_recorder(self, org_id: str, body: RecorderCreate) -> Recorder:
        values = _clean(body.model_dump(), RECORDER_TEXT)
        values["make"] = body.make.value
        if not values.get("label"):
            raise invalid_parameter("label is required.", field="label")
        return self.recorder_model(self.platform.create_recorder(org_id, values))

    def update_recorder(self, row: RecorderRow, body: RecorderUpdate) -> Recorder:
        values = _clean(body.model_dump(exclude_unset=True), RECORDER_TEXT)
        if "make" in values and values["make"] is not None:
            values["make"] = body.make.value  # type: ignore[union-attr]
        if "label" in values and not values["label"]:
            raise invalid_parameter("label must not be empty.", field="label")
        updated = self.platform.update_recorder(row.id, values)
        assert updated is not None
        return self.recorder_model(updated)

    def delete_recorder(self, row: RecorderRow) -> None:
        n = self.platform.recorder_recording_count(row.id)
        if n:
            raise conflict(
                f"This recorder has {n} recording{'s' if n != 1 else ''}. Delete them first, or end "
                "its deployments to archive it.",
                detail={"recordings": n},
            )
        self.platform.delete_recorder(row.id)

    # ------------------------------------------------------ deployments
    @staticmethod
    def deployment_model(d: DeploymentRow) -> Deployment:
        return Deployment(
            id=d.id,
            organization_id=d.organization_id,
            recorder_id=d.recorder_id,
            site_id=d.site_id,
            started_at=d.started_at,
            ended_at=d.ended_at,
            mount_height_m=d.mount_height_m,
            orientation=d.orientation,
            gain_setting=d.gain_setting,
            schedule_description=d.schedule_description,
            expected_interval_minutes=d.expected_interval_minutes,
            expected_clip_seconds=d.expected_clip_seconds,
            notes=d.notes,
            created_at=d.created_at,
        )

    def create_deployment(self, org_id: str, body: DeploymentCreate) -> Deployment:
        rec = (
            self.platform.get_recorder(body.recorder_id)
            if is_valid_id(body.recorder_id, "rcd")
            else None
        )
        if rec is None or rec.organization_id != org_id:
            raise invalid_parameter(
                "recorder_id is not a recorder of this organization.", field="recorder_id"
            )
        site = self.platform.get_site(body.site_id) if is_valid_id(body.site_id, "site") else None
        if site is None or site.organization_id != org_id:
            raise invalid_parameter("site_id is not a site of this organization.", field="site_id")
        values = _clean(body.model_dump(), DEPLOYMENT_TEXT)
        # Naive times are UTC (as stored); mixing naive and aware must not 500.
        values["started_at"] = as_utc(values["started_at"])
        values["ended_at"] = as_utc(values.get("ended_at"))
        if values["ended_at"] is not None and values["ended_at"] <= values["started_at"]:
            raise invalid_parameter("ended_at must be after started_at.", field="ended_at")
        return self.deployment_model(self.platform.create_deployment(org_id, values))

    def update_deployment(self, row: DeploymentRow, body: DeploymentUpdate) -> Deployment:
        values = _clean(body.model_dump(exclude_unset=True), DEPLOYMENT_TEXT)
        if "ended_at" in values:
            values["ended_at"] = as_utc(values["ended_at"])
        ended = as_utc(values.get("ended_at", row.ended_at))
        if ended is not None and ended <= as_utc(row.started_at):  # type: ignore[operator]
            raise invalid_parameter("ended_at must be after started_at.", field="ended_at")
        updated = self.platform.update_deployment(row.id, values)
        assert updated is not None
        return self.deployment_model(updated)

    # ------------------------------------------------------- recordings
    def recording_model(self, view: RecordingView) -> RecordingSummary:
        rec, a, st = view.recording, view.analysis, view.stats
        captured = rec.captured_at_utc
        if captured is None and rec.captured_at:
            try:
                captured = datetime.fromisoformat(rec.captured_at)
            except ValueError:
                captured = None
        quality = None
        if a is not None and a.quality and a.quality.get("status"):
            try:
                quality = QualityStatus(a.quality["status"])
            except ValueError:
                quality = None
        return RecordingSummary(
            id=rec.id,
            organization_id=rec.organization_id or "",
            site_id=rec.site_id,
            site_name=view.site_name,
            deployment_id=rec.deployment_id,
            recorder_id=rec.recorder_id,
            filename=rec.filename,
            duration_seconds=rec.duration_seconds,
            captured_at=captured,
            captured_at_source=rec.captured_at_source or ("user" if rec.captured_at else "unknown"),  # type: ignore[arg-type]
            timezone=rec.timezone,
            latitude=rec.latitude,
            longitude=rec.longitude,
            telemetry=Telemetry.model_validate(rec.telemetry) if rec.telemetry else Telemetry(),
            analysis_id=a.id if a else None,
            analysis_status=AnalysisStatus(a.status) if a else None,
            quality_status=quality,
            species_richness=st.richness if st else None,
            total_detection_events=st.events if st else None,
            decision_threshold=a.decision_threshold if a else None,
            created_at=rec.created_at,
        )

    def recordings_page(
        self,
        org_id: str,
        *,
        site_id: str | None,
        since: datetime | None,
        until: datetime | None,
        page: int,
        page_size: int,
        quality: str | None,
        species: str | None,
        recorder_id: str | None = None,
        deployment_id: str | None = None,
    ) -> RecordingPage:
        views, total = self.platform.list_recordings(
            org_id,
            site_id=site_id,
            recorder_id=recorder_id,
            deployment_id=deployment_id,
            since=since,
            until=until,
            quality=quality,
            species=species,
            page=page,
            page_size=page_size,
        )
        return RecordingPage(
            items=[self.recording_model(v) for v in views],
            total=total,
            page=page,
            page_size=page_size,
        )

    def delete_recording(self, view: RecordingView, rollups) -> None:  # type: ignore[no-untyped-def]
        for aid in self.platform.analysis_ids_for_recording(view.recording.id):
            self.analysis.delete(aid)
        rollups.remove_recording(view.recording.id)
        if view.recording.organization_id:
            self.platform.detach_recording_from_alerts(
                view.recording.organization_id, view.recording.id
            )
        log.info("recording deleted", extra={"recording_id": view.recording.id})
