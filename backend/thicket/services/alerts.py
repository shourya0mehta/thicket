"""Alert engine: ecology, data quality and recorder health.

Runs after each completed analysis (for that recording's site and
deployment), on demand (``POST /orgs/{org}/alerts/evaluate``) and nightly
(recording gaps, expected species, digests). Rules are per organization
(:class:`~thicket.api.platform_schemas.AlertRules`), conservative by default.

Baselines
---------
Ecology alerts compare a recording with *comparable* recordings: same site,
same hour bucket (dawn, day, dusk, night), same season window (ISO week
plus or minus three, across years), recorded before it. When fewer than
``min_baseline_recordings`` exist, the last eight weeks at that site and
bucket are used instead; when those are too few as well, no ecology alert
fires. Recorder checks compare within the deployment (same hour bucket when
enough recordings exist). Centers are medians and spreads are the MAD
(scaled by 1.4826), never the mean, with a small floor so a perfectly flat
baseline cannot turn a tiny change into an alert.

Deduplication
-------------
``(kind, site, recorder, species)`` identifies an alert. While one is open,
acknowledged or snoozed, a repeat updates ``last_seen_at``, ``occurrences``
and the evidence instead of creating another row (and sends no new
notification). A resolved alert can reopen as a new row.

Every ``detail`` names the observed value, the baseline and the sample size
in plain words; ``evidence`` carries the same numbers for machines.
"""

from __future__ import annotations

import logging
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from thicket.api.platform_schemas import AlertKind, AlertRules, AlertSeverity
from thicket.config import Settings
from thicket.domain.signal_profile import channel_imbalance_db, high_band_fraction
from thicket.domain.timebuckets import season_weeks
from thicket.persistence.db import (
    AlertRow,
    DeploymentRow,
    RecordingRow,
    RecordingStatsRow,
    SiteRow,
    utcnow,
)
from thicket.persistence.platform_repositories import PlatformRepository

log = logging.getLogger(__name__)

MAD_SCALE = 1.4826
MUFFLED_MAD = 3.0
LEVEL_DRIFT_DB = 6.0
LEVEL_DRIFT_WARNING_DB = 12.0
CHANNEL_IMBALANCE_DB = 12.0
DC_OFFSET_LIMIT = 0.02
CLIPPING_FLOOR = 0.001
SCHEDULE_TOLERANCE = 0.5
FUTURE_SLACK = timedelta(days=1)
FALLBACK_WEEKS = 8
MIN_INTERVALS_TO_INFER = 3
CATEGORY = {
    AlertKind.richness_drop: "ecology",
    AlertKind.activity_drop: "ecology",
    AlertKind.new_species_for_site: "ecology",
    AlertKind.priority_species_detected: "ecology",
    AlertKind.expected_species_missing: "ecology",
    AlertKind.species_surge: "ecology",
    AlertKind.low_quality_streak: "quality",
    AlertKind.speech_detected: "quality",
    AlertKind.muffled_audio: "recorder",
    AlertKind.level_drift: "recorder",
    AlertKind.recording_gap: "recorder",
    AlertKind.clipping_increase: "recorder",
    AlertKind.channel_imbalance: "recorder",
    AlertKind.dc_offset: "recorder",
    AlertKind.battery_low: "recorder",
    AlertKind.temperature_extreme: "recorder",
    AlertKind.clock_suspect: "recorder",
    AlertKind.schedule_deviation: "recorder",
}
SUGGESTED_ACTION = {
    AlertKind.richness_drop: (
        "Listen to a few of the recent recordings. If the audio sounds normal, the change may "
        "be real (weather, season, mowing or grazing). If it sounds dull or quiet, check the "
        "recorder."
    ),
    AlertKind.activity_drop: (
        "Listen to a few of the recent recordings. If the audio sounds normal, note the weather "
        "and any work on the land; if it sounds dull or quiet, check the recorder."
    ),
    AlertKind.new_species_for_site: (
        "Open the recording and listen to the event before counting on it. A new species at a "
        "site is worth a second opinion."
    ),
    AlertKind.priority_species_detected: (
        "Review the event and mark it accepted or rejected so the record is ready for reports."
    ),
    AlertKind.expected_species_missing: (
        "Check that the recorder is still in place and working. If it is, note any recent "
        "change on the land (cutting, grazing, water level) next to this alert."
    ),
    AlertKind.species_surge: (
        "Listen to a few events to confirm the species. A sudden rise is often a chorus, a "
        "flock passing through, or one repeated sound given the same label."
    ),
    AlertKind.low_quality_streak: (
        "Look at the quality checks on the recent recordings (wind, rain, clipping, silence) "
        "and visit the recorder if they keep failing."
    ),
    AlertKind.speech_detected: (
        "Human speech may be in this recording. Review it before sharing audio or exports, "
        "and consider moving the recorder away from paths and buildings."
    ),
    AlertKind.muffled_audio: (
        "Check the windscreen and microphone port for water, debris or spider webs, and "
        "confirm the recorder has not been turned toward a wall or into vegetation."
    ),
    AlertKind.level_drift: (
        "Check that the gain setting has not changed and that the microphone is not covered, "
        "loose or facing a new direction."
    ),
    AlertKind.recording_gap: (
        "Visit the recorder: check the battery, the SD card space and the schedule, and "
        "confirm it is still switched on."
    ),
    AlertKind.clipping_increase: (
        "Lower the gain one step or move the recorder a little further from the loudest "
        "source (a stream, a road, a barn)."
    ),
    AlertKind.channel_imbalance: (
        "One channel is much quieter than the other. Check both microphones and their "
        "cables; a dead channel usually means water or a broken connector."
    ),
    AlertKind.dc_offset: (
        "A steady offset usually points to a faulty microphone, cable or input. Try another "
        "microphone or cable."
    ),
    AlertKind.battery_low: (
        "Replace or recharge the batteries at the next visit; recordings stop when the "
        "voltage falls further."
    ),
    AlertKind.temperature_extreme: (
        "The recorder reported a temperature outside its comfortable range. Shade it or move "
        "it, and expect shorter battery life."
    ),
    AlertKind.clock_suspect: (
        "Check the recorder's clock and time zone. Set it again from a phone or GPS, and "
        "confirm the batteries were not removed for long."
    ),
    AlertKind.schedule_deviation: (
        "Compare the recorder's schedule with what the deployment expects, and check for "
        "restarts or a full SD card."
    ),
}


# ----------------------------------------------------------------- stats


@dataclass
class Baseline:
    median: float
    mad: float
    n: int
    description: str

    def z(self, value: float, floor: float) -> float:
        spread = max(self.mad, floor)
        return (value - self.median) / spread

    def as_dict(self) -> dict:
        return {
            "baseline_median": round(self.median, 4),
            "baseline_mad": round(self.mad, 4),
            "n": self.n,
            "baseline": self.description,
        }


def robust(values: Sequence[float], description: str) -> Baseline | None:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    med = statistics.median(vals)
    mad = statistics.median(abs(v - med) for v in vals) * MAD_SCALE
    return Baseline(median=med, mad=mad, n=len(vals), description=description)


@dataclass
class Candidate:
    kind: AlertKind
    severity: AlertSeverity
    title: str
    detail: str
    evidence: dict
    site_id: str | None = None
    recorder_id: str | None = None
    deployment_id: str | None = None
    species: tuple[str, str] | None = None
    recording_ids: list[str] = field(default_factory=list)

    @property
    def dedupe_key(self) -> str:
        sci = self.species[0] if self.species else ""
        return f"{self.kind.value}|{self.site_id or ''}|{self.recorder_id or ''}|{sci}"


def _fmt(x: float | None, digits: int = 2) -> str:
    if x is None:
        return "unknown"
    return f"{x:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{x:.0f}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# ---------------------------------------------------------------- engine


class AlertEngine:
    def __init__(
        self,
        settings: Settings,
        platform: PlatformRepository,
        notify,  # type: ignore[no-untyped-def]
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.settings = settings
        self.platform = platform
        self.notify = notify
        self.clock = clock

    # -- rules --------------------------------------------------------------
    def rules(self, org_id: str) -> AlertRules:
        stored = self.platform.alert_rules(org_id)
        try:
            return AlertRules.model_validate(stored) if stored else AlertRules()
        except Exception:  # noqa: BLE001 - never let bad stored rules stop the engine
            log.warning("invalid stored alert rules; using defaults", extra={"org_id": org_id})
            return AlertRules()

    def put_rules(self, org_id: str, rules: AlertRules) -> AlertRules:
        self.platform.put_alert_rules(org_id, rules.model_dump(mode="json"))
        return rules

    # -- entry points -------------------------------------------------------
    def evaluate_analysis(self, analysis_id: str) -> list[AlertRow]:
        """Evaluate the recording of a just-completed analysis."""
        rid = self.platform.recording_id_for_analysis(analysis_id)
        if rid is None:
            return []
        view = self.platform.get_recording(rid)
        if view is None or view.stats is None:
            return []
        return self.evaluate_recording(view.recording, view.stats)

    def evaluate_recording(self, rec: RecordingRow, stats: RecordingStatsRow) -> list[AlertRow]:
        org_id = rec.organization_id
        if not org_id:
            return []
        rules = self.rules(org_id)
        if not rules.enabled or not self.settings.alerts_enabled:
            return []
        candidates: list[Candidate] = []
        candidates.extend(self._ecology(rec, stats, rules))
        candidates.extend(self._quality(rec, stats, rules))
        candidates.extend(self._recorder(rec, stats, rules))
        return [row for c in candidates if (row := self.raise_alert(org_id, c)) is not None]

    def evaluate_org(self, org_id: str, limit: int = 200) -> list[AlertRow]:
        """Run the engine now over recent recordings, deployments and sites."""
        rules = self.rules(org_id)
        out: list[AlertRow] = []
        if not rules.enabled or not self.settings.alerts_enabled:
            return out
        self.platform.unsnooze_due(self.clock())
        recent = self.platform.stats_query(org_id, limit=limit, newest_first=True)
        for st in reversed(recent):
            view = self.platform.get_recording(st.recording_id)
            if view is None:
                continue
            out.extend(self.evaluate_recording(view.recording, st))
        out.extend(self.nightly(org_id))
        return out

    def nightly(self, org_id: str) -> list[AlertRow]:
        """Gaps for active deployments and expected species per site."""
        rules = self.rules(org_id)
        out: list[AlertRow] = []
        if not rules.enabled or not self.settings.alerts_enabled:
            return out
        self.platform.unsnooze_due(self.clock())
        now = self.clock()
        for dep in self.platform.list_deployments(org_id, active=True, now=now):
            c = self._gap_for_deployment(dep, rules, now)
            if c is not None:
                row = self.raise_alert(org_id, c)
                if row is not None:
                    out.append(row)
        for site in self.platform.list_sites(org_id):
            for c in self._expected_species(site, rules):
                row = self.raise_alert(org_id, c)
                if row is not None:
                    out.append(row)
        return out

    def evaluate_batch(self, job_id: str) -> list[AlertRow]:
        """Clock checks across one upload, per recorder: order, duplicates, future times.

        Order is checked among files whose time came from file metadata (their
        names are sequence counters): in natural name order, which is the order
        recorders write them in, a time earlier than the previous file's means
        the clock jumped back. Duplicates and future times apply to every file.
        """
        found = self.platform.get_job(job_id)
        if found is None:
            return []
        job, items = found
        rules = self.rules(job.organization_id)
        if not rules.enabled or not self.settings.alerts_enabled:
            return []
        from thicket.services.filenames import filename_sort_key

        groups: dict[str | None, list[tuple[str, datetime, str | None, str]]] = {}
        for it in items:
            if it.captured_at is None:
                continue
            recorder_id = job.recorder_id
            if it.recording_id:
                view = self.platform.get_recording(it.recording_id)
                if view is not None and view.recording.recorder_id:
                    recorder_id = view.recording.recorder_id
            groups.setdefault(recorder_id, []).append(
                (it.filename, it.captured_at, it.recording_id, it.captured_at_source)
            )
        now = self.clock()
        out: list[AlertRow] = []
        for recorder_id, stamped in sorted(groups.items(), key=lambda kv: kv[0] or ""):
            if len(stamped) < 2:
                continue
            ordered = sorted(
                (s for s in stamped if s[3] == "file_metadata"),
                key=lambda s: filename_sort_key(s[0]),
            )
            out_of_order = sum(1 for a, b in zip(ordered, ordered[1:], strict=False) if b[1] < a[1])
            times = [s[1] for s in stamped]
            duplicates = len(times) - len(set(times))
            future = sum(1 for ts in times if ts > now + FUTURE_SLACK)
            if not (out_of_order or duplicates or future):
                continue
            problems = []
            if out_of_order:
                problems.append(f"{_plural(out_of_order, 'file')} out of time order")
            if duplicates:
                problems.append(_plural(duplicates, "duplicate timestamp"))
            if future:
                problems.append(f"{_plural(future, 'timestamp')} in the future")
            recorder = self.platform.get_recorder(recorder_id) if recorder_id else None
            label = recorder.label if recorder else "the recorder"
            c = Candidate(
                kind=AlertKind.clock_suspect,
                severity=AlertSeverity.watch,
                title=f"Clock of {label} looks suspect",
                detail=(
                    f"Observed {', '.join(problems)} among {len(stamped)} timestamped files from "
                    f"{label} in one upload; baseline (expected) 0 problems; n = {len(stamped)} files."
                ),
                evidence={
                    "observed": {
                        "out_of_order": out_of_order,
                        "duplicates": duplicates,
                        "future": future,
                    },
                    "baseline": 0,
                    "n": len(stamped),
                    "window": "upload",
                    "job_id": job.id,
                },
                site_id=job.site_id,
                recorder_id=recorder_id,
                deployment_id=job.deployment_id,
                recording_ids=[s[2] for s in stamped if s[2]][:20],
            )
            row = self.raise_alert(job.organization_id, c)
            if row is not None:
                out.append(row)
        return out

    # -- persistence --------------------------------------------------------
    def raise_alert(self, org_id: str, c: Candidate) -> AlertRow | None:
        now = self.clock()
        existing = self.platform.find_open_alert(org_id, c.dedupe_key)
        if existing is not None:
            merged_ids = list(dict.fromkeys([*existing.recording_ids, *c.recording_ids]))[-20:]
            return self.platform.update_alert(
                existing.id,
                {
                    "last_seen_at": now,
                    "occurrences": int(existing.occurrences or 1) + 1,
                    "detail": c.detail,
                    "evidence": c.evidence,
                    "severity": max(existing.severity, c.severity.value, key=_severity_rank),
                    "recording_ids": merged_ids,
                },
            )
        row = self.platform.insert_alert(
            {
                "organization_id": org_id,
                "kind": c.kind.value,
                "category": CATEGORY[c.kind],
                "severity": c.severity.value,
                "status": "open",
                "title": c.title,
                "detail": c.detail,
                "suggested_action": SUGGESTED_ACTION.get(c.kind),
                "evidence": c.evidence,
                "site_id": c.site_id,
                "recorder_id": c.recorder_id,
                "deployment_id": c.deployment_id,
                "species_scientific_name": c.species[0] if c.species else None,
                "species_common_name": c.species[1] if c.species else None,
                "recording_ids": c.recording_ids[:20],
                "dedupe_key": c.dedupe_key,
                "first_seen_at": now,
                "last_seen_at": now,
                "occurrences": 1,
                "created_at": now,
                "updated_at": now,
            }
        )
        log.info(
            "alert opened",
            extra={
                "alert_id": row.id,
                "kind": row.kind,
                "severity": row.severity,
                "org_id": org_id,
                "site_id": c.site_id,
                "recorder_id": c.recorder_id,
            },
        )
        try:
            self.notify.on_alert(row)
        except Exception:  # noqa: BLE001 - notifications never block the engine
            log.exception("notification failed", extra={"alert_id": row.id})
        return row

    # -- baselines ----------------------------------------------------------
    def _site_history(
        self, org_id: str, site_id: str, before: datetime | None
    ) -> list[RecordingStatsRow]:
        rows = self.platform.stats_query(org_id, site_id=site_id)
        if before is None:
            return rows
        return [r for r in rows if r.captured_at is not None and r.captured_at < before]

    @staticmethod
    def comparable(
        history: Sequence[RecordingStatsRow],
        current: RecordingStatsRow,
        min_n: int,
    ) -> tuple[list[RecordingStatsRow], str]:
        """Same bucket and season window across years, else the last eight weeks."""
        same_bucket = [r for r in history if r.hour_bucket == current.hour_bucket]
        weeks = season_weeks((current.iso_year, current.iso_week))
        seasonal = [r for r in same_bucket if r.iso_week in weeks]
        if len(seasonal) >= min_n:
            return seasonal, (
                f"same site, {current.hour_bucket} recordings within three ISO weeks of week "
                f"{current.iso_week} across years"
            )
        if current.captured_at is not None:
            since = current.captured_at - timedelta(weeks=FALLBACK_WEEKS)
            recent = [
                r for r in same_bucket if r.captured_at is not None and r.captured_at >= since
            ]
        else:
            recent = same_bucket[-max(min_n, 0) * 4 :]
        if len(recent) >= min_n:
            return recent, f"same site, {current.hour_bucket} recordings from the last eight weeks"
        return [], ""

    # -- ecology --------------------------------------------------------------
    def _ecology(
        self, rec: RecordingRow, st: RecordingStatsRow, rules: AlertRules
    ) -> list[Candidate]:
        out: list[Candidate] = []
        site = self.platform.get_site(rec.site_id) if rec.site_id else None
        site_name = site.name if site else (rec.site_name or "this site")
        species_here = st.species or {}
        for sci in rules.priority_species:
            for found, info in species_here.items():
                if (
                    found.lower() == sci.strip().lower()
                    or str(info[0]).lower() == sci.strip().lower()
                ):
                    out.append(
                        Candidate(
                            kind=AlertKind.priority_species_detected,
                            severity=AlertSeverity.info,
                            title=f"{info[0]} detected at {site_name}",
                            detail=(
                                f"Observed {_plural(int(info[2]), 'detection event')} of {info[0]} "
                                f"({found}) with a highest score of {_fmt(float(info[3]))}; baseline "
                                "none (priority species listed in the alert rules); n = 1 recording."
                            ),
                            evidence={
                                "observed": int(info[2]),
                                "max_confidence": float(info[3]),
                                "baseline": None,
                                "n": 1,
                            },
                            site_id=rec.site_id,
                            recorder_id=rec.recorder_id,
                            deployment_id=rec.deployment_id,
                            species=(found, str(info[0])),
                            recording_ids=[rec.id],
                        )
                    )
        if not rec.site_id or st.captured_at is None:
            return out
        history = self._site_history(rec.organization_id or "", rec.site_id, st.captured_at)
        if not history:
            return out
        # New species for the site: needs enough history to mean anything.
        if len(history) >= rules.min_baseline_recordings:
            known = set()
            for h in history:
                known.update((h.species or {}).keys())
            for sci, info in species_here.items():
                if sci not in known and str(info[4] or "unknown") != "unlikely":
                    out.append(
                        Candidate(
                            kind=AlertKind.new_species_for_site,
                            severity=AlertSeverity.info,
                            title=f"New species for {site_name}: {info[0]}",
                            detail=(
                                f"Observed {info[0]} ({sci}) for the first time at this site, "
                                f"{_plural(int(info[2]), 'event')} with a highest score of "
                                f"{_fmt(float(info[3]))}; baseline {len(known)} species known from "
                                f"n = {len(history)} earlier recordings."
                            ),
                            evidence={
                                "observed": int(info[2]),
                                "max_confidence": float(info[3]),
                                "baseline": len(known),
                                "n": len(history),
                            },
                            site_id=rec.site_id,
                            recorder_id=rec.recorder_id,
                            deployment_id=rec.deployment_id,
                            species=(sci, str(info[0])),
                            recording_ids=[rec.id],
                        )
                    )
        comparable, description = self.comparable(history, st, rules.min_baseline_recordings)
        if not comparable:
            return out
        # Drops need the last N recordings in this bucket to agree.
        same_bucket = [r for r in history if r.hour_bucket == st.hour_bucket]
        run = (
            [*same_bucket[-(rules.consecutive_recordings - 1) :], st]
            if rules.consecutive_recordings > 1
            else [st]
        )
        if len(run) == rules.consecutive_recordings:
            out.extend(
                self._drop(
                    rec,
                    st,
                    run,
                    comparable,
                    description,
                    AlertKind.richness_drop,
                    "richness",
                    rules.richness_drop_mad,
                    1.0,
                    "species richness",
                    site_name,
                )
            )
            out.extend(
                self._drop(
                    rec,
                    st,
                    run,
                    comparable,
                    description,
                    AlertKind.activity_drop,
                    "events_per_minute",
                    rules.activity_drop_mad,
                    0.05,
                    "detection events per minute",
                    site_name,
                )
            )
        # Species surge: this species' events against its own history where present.
        for sci, info in species_here.items():
            past = [
                int((h.species or {}).get(sci, [None, None, 0])[2])
                for h in comparable
                if sci in (h.species or {})
            ]
            if len(past) < rules.min_baseline_recordings:
                continue
            base = robust(past, description)
            if base is None:
                continue
            z = base.z(float(info[2]), 1.0)
            if z >= rules.species_surge_mad:
                out.append(
                    Candidate(
                        kind=AlertKind.species_surge,
                        severity=AlertSeverity.watch,
                        title=f"{info[0]} activity surged at {site_name}",
                        detail=(
                            f"Observed {_plural(int(info[2]), 'detection event')} of {info[0]} in "
                            f"this recording; baseline median {_fmt(base.median, 1)} per recording "
                            f"(MAD {_fmt(base.mad, 2)}) from n = {base.n} comparable recordings "
                            f"({description})."
                        ),
                        evidence={
                            "observed": int(info[2]),
                            "robust_z": round(z, 2),
                            **base.as_dict(),
                        },
                        site_id=rec.site_id,
                        recorder_id=rec.recorder_id,
                        deployment_id=rec.deployment_id,
                        species=(sci, str(info[0])),
                        recording_ids=[rec.id],
                    )
                )
        return out

    def _drop(
        self,
        rec: RecordingRow,
        st: RecordingStatsRow,
        run: Sequence[RecordingStatsRow],
        comparable: Sequence[RecordingStatsRow],
        description: str,
        kind: AlertKind,
        attr: str,
        k: float,
        floor: float,
        label: str,
        site_name: str,
    ) -> list[Candidate]:
        base = robust([getattr(r, attr) for r in comparable], description)
        if base is None:
            return []
        values = [float(getattr(r, attr)) for r in run]
        zs = [base.z(v, floor) for v in values]
        if not all(z <= -k for z in zs):
            return []
        worst = min(zs)
        severity = AlertSeverity.warning if worst <= -1.5 * k else AlertSeverity.watch
        observed = ", ".join(_fmt(v, 2 if attr != "richness" else 0) for v in values)
        return [
            Candidate(
                kind=kind,
                severity=severity,
                title=f"{label.capitalize()} dropped at {site_name}",
                detail=(
                    f"Observed {label} of {observed} in the last {_plural(len(run), 'recording')} "
                    f"({st.hour_bucket}); baseline median {_fmt(base.median, 2)} "
                    f"(MAD {_fmt(base.mad, 2)}) from n = {base.n} comparable recordings "
                    f"({description})."
                ),
                evidence={
                    "observed": values,
                    "robust_z": [round(z, 2) for z in zs],
                    "threshold_mad": k,
                    "hour_bucket": st.hour_bucket,
                    **base.as_dict(),
                },
                site_id=rec.site_id,
                recorder_id=rec.recorder_id,
                deployment_id=rec.deployment_id,
                recording_ids=[r.recording_id for r in run],
            )
        ]

    def _expected_species(self, site: SiteRow, rules: AlertRules) -> list[Candidate]:
        rows = self.platform.stats_query(site.organization_id or "", site_id=site.id)
        if len(rows) < rules.min_baseline_recordings + rules.expected_species_missing_recordings:
            return []
        latest = rows[-rules.expected_species_missing_recordings :]
        current = latest[-1]
        history = [
            r
            for r in rows
            if r.captured_at is not None
            and current.captured_at is not None
            and r.captured_at < latest[0].captured_at
        ]  # type: ignore[operator]
        weeks = season_weeks((current.iso_year, current.iso_week))
        seasonal = [r for r in history if r.iso_week in weeks]
        description = "same site, within three ISO weeks of this week across years"
        if len(seasonal) < rules.min_baseline_recordings:
            if latest[0].captured_at is None:
                return []
            since = latest[0].captured_at - timedelta(weeks=FALLBACK_WEEKS)
            seasonal = [r for r in history if r.captured_at is not None and r.captured_at >= since]
            description = "same site, the eight weeks before these recordings"
        if len(seasonal) < rules.min_baseline_recordings:
            return []
        presence: dict[str, int] = {}
        names: dict[str, str] = {}
        for r in seasonal:
            for sci, info in (r.species or {}).items():
                presence[sci] = presence.get(sci, 0) + 1
                names[sci] = str(info[0])
        recent_species = set()
        for r in latest:
            recent_species.update((r.species or {}).keys())
        out: list[Candidate] = []
        for sci, n_present in presence.items():
            fraction = n_present / len(seasonal)
            if fraction < rules.expected_species_min_presence or sci in recent_species:
                continue
            out.append(
                Candidate(
                    kind=AlertKind.expected_species_missing,
                    severity=AlertSeverity.watch,
                    title=f"{names[sci]} not detected recently at {site.name}",
                    detail=(
                        f"Observed 0 recordings with {names[sci]} ({sci}) in the last "
                        f"{len(latest)} recordings; baseline presence {_fmt(fraction * 100, 0)}% "
                        f"of n = {len(seasonal)} comparable recordings ({description}). Not detected "
                        "in this effort does not mean the species is gone."
                    ),
                    evidence={
                        "observed": 0,
                        "recent_recordings": len(latest),
                        "baseline_presence_fraction": round(fraction, 3),
                        "n": len(seasonal),
                        "baseline": description,
                    },
                    site_id=site.id,
                    species=(sci, names[sci]),
                    recording_ids=[r.recording_id for r in latest],
                )
            )
        return out

    # -- quality --------------------------------------------------------------
    def _quality(
        self, rec: RecordingRow, st: RecordingStatsRow, rules: AlertRules
    ) -> list[Candidate]:
        out: list[Candidate] = []
        if st.speech_detected:
            out.append(
                Candidate(
                    kind=AlertKind.speech_detected,
                    severity=AlertSeverity.info,
                    title="Possible human speech in a recording",
                    detail=(
                        "Observed BirdNET's human vocal score at or above 0.5 in at least one "
                        "window; baseline (threshold) 0.5; n = 1 recording."
                    ),
                    evidence={"observed": True, "baseline": 0.5, "n": 1},
                    site_id=rec.site_id,
                    recorder_id=rec.recorder_id,
                    deployment_id=rec.deployment_id,
                    recording_ids=[rec.id],
                )
            )
        if st.quality_status == "not_usable":
            scope = (
                self.platform.stats_query(rec.organization_id or "", recorder_id=rec.recorder_id)
                if rec.recorder_id
                else (
                    self.platform.stats_query(rec.organization_id or "", site_id=rec.site_id)
                    if rec.site_id
                    else []
                )
            )
            ordered = [r for r in scope if r.captured_at is not None]
            tail = ordered[-rules.low_quality_streak :]
            if len(tail) == rules.low_quality_streak and all(
                r.quality_status == "not_usable" for r in tail
            ):
                out.append(
                    Candidate(
                        kind=AlertKind.low_quality_streak,
                        severity=AlertSeverity.warning,
                        title="Several recordings in a row failed quality checks",
                        detail=(
                            f"Observed {len(tail)} consecutive recordings rated not usable; "
                            f"baseline (threshold) {rules.low_quality_streak} in a row; "
                            f"n = {len(tail)} recordings."
                        ),
                        evidence={
                            "observed": len(tail),
                            "baseline": rules.low_quality_streak,
                            "n": len(tail),
                        },
                        site_id=rec.site_id,
                        recorder_id=rec.recorder_id,
                        deployment_id=rec.deployment_id,
                        recording_ids=[r.recording_id for r in tail],
                    )
                )
        return out

    # -- recorder health --------------------------------------------------------
    def _recorder(
        self, rec: RecordingRow, st: RecordingStatsRow, rules: AlertRules
    ) -> list[Candidate]:
        out: list[Candidate] = []
        profile = rec.signal_profile or {}
        telemetry = rec.telemetry or {}
        recorder = self.platform.get_recorder(rec.recorder_id) if rec.recorder_id else None
        label = recorder.label if recorder else "the recorder"
        common = {
            "site_id": rec.site_id,
            "recorder_id": rec.recorder_id,
            "deployment_id": rec.deployment_id,
        }
        # Fixed-threshold checks (no baseline needed).
        imbalance = channel_imbalance_db(profile) if profile else None
        if imbalance is not None and imbalance > CHANNEL_IMBALANCE_DB:
            out.append(
                Candidate(
                    kind=AlertKind.channel_imbalance,
                    severity=AlertSeverity.watch,
                    title=f"Channel imbalance on {label}",
                    detail=(
                        f"Observed {_fmt(imbalance, 1)} dB between the loudest and quietest channel; "
                        f"baseline (threshold) {_fmt(CHANNEL_IMBALANCE_DB, 0)} dB; n = 1 recording."
                    ),
                    evidence={
                        "observed": round(imbalance, 2),
                        "baseline": CHANNEL_IMBALANCE_DB,
                        "n": 1,
                    },
                    recording_ids=[rec.id],
                    **common,
                )
            )
        dc = profile.get("dc_offset")
        if dc is not None and abs(float(dc)) > DC_OFFSET_LIMIT:
            out.append(
                Candidate(
                    kind=AlertKind.dc_offset,
                    severity=AlertSeverity.watch,
                    title=f"DC offset on {label}",
                    detail=(
                        f"Observed a DC offset of {float(dc):+.3f} (full scale is 1.0); baseline "
                        f"(threshold) {DC_OFFSET_LIMIT:.2f}; n = 1 recording."
                    ),
                    evidence={"observed": float(dc), "baseline": DC_OFFSET_LIMIT, "n": 1},
                    recording_ids=[rec.id],
                    **common,
                )
            )
        battery = telemetry.get("battery_v")
        if battery is not None:
            make = recorder.make if recorder else "other"
            limit = rules.battery_low_v.get(make, rules.battery_low_v.get("other", 3.6))
            if float(battery) < limit:
                out.append(
                    Candidate(
                        kind=AlertKind.battery_low,
                        severity=AlertSeverity.warning,
                        title=f"Battery low on {label}",
                        detail=(
                            f"Observed {_fmt(float(battery), 2)} V; baseline (threshold for "
                            f"{make.replace('_', ' ')}) {_fmt(limit, 2)} V; n = 1 recording."
                        ),
                        evidence={
                            "observed": float(battery),
                            "baseline": limit,
                            "n": 1,
                            "make": make,
                        },
                        recording_ids=[rec.id],
                        **common,
                    )
                )
        temp = telemetry.get("temperature_c")
        if (
            temp is not None
            and not rules.temperature_min_c <= float(temp) <= rules.temperature_max_c
        ):
            out.append(
                Candidate(
                    kind=AlertKind.temperature_extreme,
                    severity=AlertSeverity.watch,
                    title=f"Temperature extreme at {label}",
                    detail=(
                        f"Observed {_fmt(float(temp), 1)} C; baseline (allowed range) "
                        f"{_fmt(rules.temperature_min_c, 0)} to {_fmt(rules.temperature_max_c, 0)} C; "
                        "n = 1 recording."
                    ),
                    evidence={
                        "observed": float(temp),
                        "baseline": [rules.temperature_min_c, rules.temperature_max_c],
                        "n": 1,
                    },
                    recording_ids=[rec.id],
                    **common,
                )
            )
        if not profile:
            return out
        # Baseline checks within the deployment (or the recorder).
        scope_id = rec.deployment_id or rec.recorder_id
        if not scope_id:
            return out
        recordings = (
            self.platform.recordings_for_deployment(rec.deployment_id)
            if rec.deployment_id
            else self.platform.recordings_for_recorder(rec.recorder_id or "")
        )
        current_ts = rec.captured_at_utc or st.captured_at
        earlier = [
            r
            for r in recordings
            if r.id != rec.id
            and r.signal_profile
            and (r.captured_at_utc is None or current_ts is None or r.captured_at_utc < current_ts)
        ]
        if len(earlier) < rules.min_baseline_recordings:
            return out
        buckets: dict[str, str] = {}
        if rec.deployment_id:
            for s in self.platform.stats_query(
                rec.organization_id or "", deployment_id=rec.deployment_id
            ):
                buckets[s.recording_id] = s.hour_bucket
        same_bucket = [r for r in earlier if buckets.get(r.id) == st.hour_bucket]
        base_set = same_bucket if len(same_bucket) >= rules.min_baseline_recordings else earlier
        where = "same deployment" + (
            f", {st.hour_bucket} recordings" if base_set is same_bucket else ", all hours"
        )
        n_run = rules.consecutive_recordings
        run = [*earlier[-(n_run - 1) :], rec] if n_run > 1 else [rec]
        run_profiles = [r.signal_profile or {} for r in run]
        # muffled: high band and centroid both below baseline by > 3 MAD for the run
        hb = robust([high_band_fraction(r.signal_profile or {}) for r in base_set], where)
        ce = robust(
            [float((r.signal_profile or {}).get("spectral_centroid_hz", 0.0)) for r in base_set],
            where,
        )
        if hb and ce and len(run) == n_run:
            hb_z = [hb.z(high_band_fraction(p), 0.01) for p in run_profiles]
            ce_z = [ce.z(float(p.get("spectral_centroid_hz", 0.0)), 50.0) for p in run_profiles]
            if all(z <= -MUFFLED_MAD for z in hb_z) and all(z <= -MUFFLED_MAD for z in ce_z):
                out.append(
                    Candidate(
                        kind=AlertKind.muffled_audio,
                        severity=AlertSeverity.warning,
                        title=f"Muffled audio from {label}",
                        detail=(
                            f"Observed a high-band share of {_fmt(high_band_fraction(profile) * 100, 1)}% "
                            f"and a spectral centroid of {_fmt(float(profile.get('spectral_centroid_hz', 0.0)), 0)} Hz "
                            f"in the last {_plural(len(run), 'recording')}; baseline medians "
                            f"{_fmt(hb.median * 100, 1)}% (MAD {_fmt(hb.mad * 100, 1)}) and "
                            f"{_fmt(ce.median, 0)} Hz (MAD {_fmt(ce.mad, 0)}) from n = {hb.n} "
                            f"recordings ({where})."
                        ),
                        evidence={
                            "observed": {
                                "high_band_fraction": round(high_band_fraction(profile), 4),
                                "spectral_centroid_hz": float(
                                    profile.get("spectral_centroid_hz", 0.0)
                                ),
                            },
                            "robust_z": {
                                "high_band": [round(z, 2) for z in hb_z],
                                "centroid": [round(z, 2) for z in ce_z],
                            },
                            "baseline_median": {
                                "high_band_fraction": round(hb.median, 4),
                                "spectral_centroid_hz": round(ce.median, 1),
                            },
                            "baseline_mad": {
                                "high_band_fraction": round(hb.mad, 4),
                                "spectral_centroid_hz": round(ce.mad, 1),
                            },
                            "n": hb.n,
                            "baseline": where,
                        },
                        recording_ids=[r.id for r in run],
                        **common,
                    )
                )
        # level drift: RMS more than 6 dB from the deployment median for the same bucket
        lv = robust(
            [float((r.signal_profile or {}).get("rms_dbfs", -120.0)) for r in base_set], where
        )
        rms = float(profile.get("rms_dbfs", -120.0))
        if lv is not None and abs(rms - lv.median) > LEVEL_DRIFT_DB:
            delta = rms - lv.median
            out.append(
                Candidate(
                    kind=AlertKind.level_drift,
                    severity=AlertSeverity.warning
                    if abs(delta) > LEVEL_DRIFT_WARNING_DB
                    else AlertSeverity.watch,
                    title=f"Level drift on {label}",
                    detail=(
                        f"Observed an RMS level of {_fmt(rms, 1)} dBFS, {_fmt(abs(delta), 1)} dB "
                        f"{'above' if delta > 0 else 'below'} the baseline median of {_fmt(lv.median, 1)} dBFS "
                        f"(MAD {_fmt(lv.mad, 1)}) from n = {lv.n} recordings ({where}); the limit is "
                        f"{_fmt(LEVEL_DRIFT_DB, 0)} dB."
                    ),
                    evidence={
                        "observed": rms,
                        "delta_db": round(delta, 2),
                        "limit_db": LEVEL_DRIFT_DB,
                        **lv.as_dict(),
                    },
                    recording_ids=[rec.id],
                    **common,
                )
            )
        # clipping increase for the run
        cl = robust(
            [float((r.signal_profile or {}).get("clipping_fraction", 0.0)) for r in base_set], where
        )
        if cl is not None and len(run) == n_run:
            limit = max(cl.median + MUFFLED_MAD * max(cl.mad, 0.0), CLIPPING_FLOOR)
            vals = [float(p.get("clipping_fraction", 0.0)) for p in run_profiles]
            if all(v > limit for v in vals):
                out.append(
                    Candidate(
                        kind=AlertKind.clipping_increase,
                        severity=AlertSeverity.watch,
                        title=f"Clipping increased on {label}",
                        detail=(
                            f"Observed clipping in {_fmt(vals[-1] * 100, 2)}% of samples "
                            f"(last {_plural(len(run), 'recording')} all above the limit); baseline "
                            f"median {_fmt(cl.median * 100, 3)}% (MAD {_fmt(cl.mad * 100, 3)}) from "
                            f"n = {cl.n} recordings ({where})."
                        ),
                        evidence={"observed": vals, "limit": round(limit, 6), **cl.as_dict()},
                        recording_ids=[r.id for r in run],
                        **common,
                    )
                )
        # schedule deviation when an expected interval is declared
        dep = self.platform.get_deployment(rec.deployment_id) if rec.deployment_id else None
        if dep is not None and dep.expected_interval_minutes and current_ts is not None:
            stamped = [r for r in earlier if r.captured_at_utc is not None]
            if stamped:
                prev = stamped[-1]
                gap_min = (current_ts - prev.captured_at_utc).total_seconds() / 60.0  # type: ignore[operator]
                expected = float(dep.expected_interval_minutes)
                gap_hours_limit = max(rules.gap_multiplier * expected / 60.0, rules.gap_min_hours)
                deviates = abs(gap_min - expected) > SCHEDULE_TOLERANCE * expected
                if deviates and gap_min / 60.0 < gap_hours_limit:
                    out.append(
                        Candidate(
                            kind=AlertKind.schedule_deviation,
                            severity=AlertSeverity.watch,
                            title=f"Schedule deviation on {label}",
                            detail=(
                                f"Observed {_fmt(gap_min, 1)} minutes since the previous recording; "
                                f"baseline (expected interval) {_fmt(expected, 1)} minutes; n = 1 "
                                "interval."
                            ),
                            evidence={"observed": round(gap_min, 2), "baseline": expected, "n": 1},
                            recording_ids=[prev.id, rec.id],
                            **common,
                        )
                    )
        return out

    def _gap_for_deployment(
        self, dep: DeploymentRow, rules: AlertRules, now: datetime
    ) -> Candidate | None:
        recordings = [
            r
            for r in self.platform.recordings_for_deployment(dep.id)
            if r.captured_at_utc is not None
        ]
        if len(recordings) < 2:
            return None
        times = [r.captured_at_utc for r in recordings]
        intervals = [
            (b - a).total_seconds() / 60.0
            for a, b in zip(times, times[1:], strict=False)  # type: ignore[operator]
        ]
        if not dep.expected_interval_minutes and len(intervals) < MIN_INTERVALS_TO_INFER:
            return None  # too few intervals to infer a schedule
        median_interval = (
            float(dep.expected_interval_minutes)
            if dep.expected_interval_minutes
            else statistics.median(intervals)
        )
        if median_interval <= 0:
            return None
        limit_hours = max(rules.gap_multiplier * median_interval / 60.0, rules.gap_min_hours)
        last = times[-1]
        gap_hours = (now - last).total_seconds() / 3600.0  # type: ignore[operator]
        if gap_hours < limit_hours:
            return None
        recorder = self.platform.get_recorder(dep.recorder_id)
        label = recorder.label if recorder else "the recorder"
        return Candidate(
            kind=AlertKind.recording_gap,
            severity=AlertSeverity.warning,
            title=f"No recordings from {label} for {_fmt(gap_hours, 0)} hours",
            detail=(
                f"Observed {_fmt(gap_hours, 1)} hours since the last recording "
                f"({last.isoformat(timespec='minutes')}); baseline median interval "  # type: ignore[union-attr]
                f"{_fmt(median_interval, 1)} minutes from n = {len(intervals)} intervals; the limit is "
                f"{_fmt(limit_hours, 1)} hours ({rules.gap_multiplier:g} times the interval, at least "
                f"{rules.gap_min_hours:g} hours)."
            ),
            evidence={
                "observed_gap_hours": round(gap_hours, 2),
                "baseline_median_interval_minutes": round(median_interval, 2),
                "n": len(intervals),
                "limit_hours": round(limit_hours, 2),
                "last_recording_at": last.isoformat(),  # type: ignore[union-attr]
            },
            site_id=dep.site_id,
            recorder_id=dep.recorder_id,
            deployment_id=dep.id,
            recording_ids=[recordings[-1].id],
        )

    # -- health summaries used by sites and recorders ---------------------------
    @staticmethod
    def health_from_counts(counts: dict[str, int] | None) -> str:
        if counts is None:
            return "unknown"
        if counts.get("warning"):
            return "attention"
        if counts.get("watch"):
            return "watch"
        return "good"


def _severity_rank(value: str) -> int:
    return {"info": 0, "watch": 1, "warning": 2}.get(value, 0)
