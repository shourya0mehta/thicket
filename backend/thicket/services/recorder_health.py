"""Recorder health: series, gaps, checks and uptime for one recorder.

Reads the signal profiles and telemetry stored on recordings (no audio) for
the ``days`` up to the recorder's latest recording (SD cards arrive weeks
late, so the window follows the data, not the calendar), works out the
recording window (declared ``HH:MM-HH:MM`` ranges in the deployment's
schedule description, else the local hours its recordings cover), infers the
interval when the deployment does not declare one, finds gaps between
consecutive recordings counted in active minutes only (longer than
``gap_multiplier`` times the interval and at least ``gap_min_hours``), and
summarizes checks with a status and the baseline each one was compared
against. Uptime compares the recordings in the 7 days up to the latest one
with the number the schedule expects inside its active hours.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from thicket.api.platform_schemas import (
    AlertRules,
    Gap,
    HealthCheck,
    Recorder,
    RecorderHealth,
    SeriesPoint,
)
from thicket.config import Settings
from thicket.domain.schedule import (
    ALL_HOURS,
    Schedule,
    expected_recordings,
    find_active_gaps,
    infer_interval,
    schedule_for,
)
from thicket.domain.signal_profile import channel_imbalance_db, high_band_fraction
from thicket.persistence.db import DeploymentRow, RecorderRow, RecordingRow
from thicket.persistence.platform_repositories import PlatformRepository
from thicket.services.alerts import (
    CHANNEL_IMBALANCE_DB,
    CLIPPING_FLOOR,
    DC_OFFSET_LIMIT,
    LEVEL_DRIFT_DB,
    LEVEL_DRIFT_WARNING_DB,
    MAD_SCALE,
    MIN_INTERVALS_TO_INFER,
    AlertEngine,
)
from thicket.services.notify import alert_model

Status = str


def _median_mad(values: Sequence[float]) -> tuple[float, float] | None:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    med = statistics.median(vals)
    mad = statistics.median(abs(v - med) for v in vals) * MAD_SCALE
    return med, mad


def _latest_and_median(points: Sequence[SeriesPoint]) -> tuple[float, float] | None:
    """(latest value, median of the earlier values, or of the only value)."""
    if not points:
        return None
    earlier = [p.v for p in points[:-1]] or [points[-1].v]
    return points[-1].v, statistics.median(earlier)


def _worst(statuses: Sequence[Status]) -> Status:
    order = {"unknown": 0, "good": 1, "watch": 2, "attention": 3}
    known = [s for s in statuses if s != "unknown"]
    if not known:
        return "unknown"
    return max(known, key=lambda s: order[s])


_ROUND_THE_CLOCK = Schedule(tz=ZoneInfo("UTC"), hours=ALL_HOURS, source="declared")


def find_gaps(
    times: Sequence[datetime],
    *,
    interval_minutes: float | None,
    multiplier: float,
    min_hours: float,
    schedule: Schedule | None = None,
) -> list[Gap]:
    """Gaps between consecutive recordings; ``hours`` counts active hours only."""
    found = find_active_gaps(
        times,
        schedule or _ROUND_THE_CLOCK,
        interval_minutes=interval_minutes,
        multiplier=multiplier,
        min_hours=min_hours,
    )
    return [
        Gap(
            start=g.start,
            end=g.end,
            hours=g.active_hours,
            expected_recordings=g.expected_recordings,
        )
        for g in found
    ]


def infer_interval_minutes(
    times: Sequence[datetime], schedule: Schedule | None = None
) -> float | None:
    if len(times) < MIN_INTERVALS_TO_INFER + 1:
        return None
    return infer_interval(times, schedule or _ROUND_THE_CLOCK)


class RecorderHealthService:
    def __init__(
        self, settings: Settings, platform: PlatformRepository, alerts: AlertEngine
    ) -> None:
        self.settings = settings
        self.platform = platform
        self.alerts = alerts

    def build(
        self,
        recorder_row: RecorderRow,
        recorder: Recorder,
        deployment_model,  # type: ignore[no-untyped-def]
        deployment: DeploymentRow | None,
        *,
        days: int,
        now: datetime | None = None,
    ) -> RecorderHealth:
        now = now or datetime.now(UTC)
        # The window follows the data: backfilled SD cards would otherwise show
        # an empty (or 0% uptime) recorder until the calendar catches up.
        latest = self.platform.recorder_last_recording([recorder_row.id]).get(recorder_row.id)
        anchor = min(latest, now) if latest else now
        since = anchor - timedelta(days=days)
        rules: AlertRules = self.alerts.rules(recorder_row.organization_id)
        recordings = [
            r
            for r in self.platform.recordings_for_recorder(recorder_row.id, since=since)
            if r.captured_at_utc is not None
        ]
        times = [r.captured_at_utc for r in recordings]
        org = self.platform.get_org(recorder_row.organization_id)
        schedule = schedule_for(
            [(r.captured_at_utc, float(r.duration_seconds or 0.0)) for r in recordings],  # type: ignore[misc]
            org.timezone if org else None,
            deployment.schedule_description if deployment else None,
        )
        declared = (
            float(deployment.expected_interval_minutes)
            if deployment and deployment.expected_interval_minutes
            else None
        )
        inferred = infer_interval_minutes(times, schedule)  # type: ignore[arg-type]
        interval = declared or inferred
        gaps = find_gaps(
            times,  # type: ignore[arg-type]
            interval_minutes=interval,
            multiplier=rules.gap_multiplier,
            min_hours=rules.gap_min_hours,
            schedule=schedule,
        )
        last_7d: list = []
        expected_7d = None
        uptime = None
        if times:
            window_end = times[-1]
            window_start = max(window_end - timedelta(days=7), times[0])  # type: ignore[operator, type-var]
            last_7d = [t for t in times if t >= window_start]  # type: ignore[operator]
            if interval:
                expected_7d = expected_recordings(window_start, window_end, schedule, interval)  # type: ignore[arg-type]
                uptime = min(1.0, len(last_7d) / expected_7d) if expected_7d else None

        def series(getter) -> list[SeriesPoint]:  # type: ignore[no-untyped-def]
            out = []
            for r in recordings:
                v = getter(r)
                if v is not None:
                    out.append(SeriesPoint(t=r.captured_at_utc, v=round(float(v), 4)))  # type: ignore[arg-type]
            return out

        battery = series(lambda r: (r.telemetry or {}).get("battery_v"))
        temperature = series(lambda r: (r.telemetry or {}).get("temperature_c"))
        level = series(lambda r: (r.signal_profile or {}).get("rms_dbfs"))
        high_band = series(
            lambda r: high_band_fraction(r.signal_profile) if r.signal_profile else None
        )
        centroid = series(lambda r: (r.signal_profile or {}).get("spectral_centroid_hz"))
        clipping = series(lambda r: (r.signal_profile or {}).get("clipping_fraction"))

        checks = self._checks(
            recorder_row,
            recordings,
            rules,
            level=level,
            high_band=high_band,
            centroid=centroid,
            clipping=clipping,
            battery=battery,
            temperature=temperature,
            gaps=gaps,
            uptime=uptime,
            interval=interval,
            declared=declared,
        )
        open_alerts = [
            alert_model(a)
            for a in self.platform.open_alerts_for(
                recorder_row.organization_id, recorder_id=recorder_row.id
            )
        ]
        alert_status = (
            "attention"
            if any(a.severity.value == "warning" for a in open_alerts)
            else ("watch" if any(a.severity.value == "watch" for a in open_alerts) else "unknown")
        )
        status = _worst([*(c.status for c in checks), alert_status]) if recordings else "unknown"
        if declared:
            interval_text = f" Declared interval {declared:g} min."
        elif inferred:
            interval_text = f" Inferred interval {inferred:g} min."
        else:
            interval_text = " Interval unknown."
        if recordings:
            source = (
                "from the deployment's schedule"
                if schedule.source == "declared"
                else "learned from its recordings"
            )
            interval_text += (
                f" Recording window: {schedule.describe()} ({source}); gaps and uptime count "
                "only those hours."
            )
        window = (
            f"the {days} days up to the latest recording ({anchor.date().isoformat()})"
            if latest
            else f"the last {days} days"
        )
        if not recordings:
            note = f"No timestamped recordings from this recorder in {window}."
        elif len(recordings) < rules.min_baseline_recordings:
            note = (
                f"{len(recordings)} recordings in {window}; baselines need "
                f"{rules.min_baseline_recordings}, so checks compare against the window median only."
                + interval_text
            )
        else:
            note = (
                f"Baselines are medians over {len(recordings)} recordings in {window}."
                + interval_text
            )
        return RecorderHealth(
            recorder=recorder,
            deployment=deployment_model,
            status=status,  # type: ignore[arg-type]
            checks=checks,
            last_recording_at=times[-1] if times else None,
            recordings_last_7d=len(last_7d),
            expected_last_7d=expected_7d,
            uptime_fraction_7d=round(uptime, 4) if uptime is not None else None,
            median_interval_minutes=interval,
            battery=battery,
            temperature=temperature,
            level_dbfs=level,
            high_band_fraction=high_band,
            spectral_centroid_hz=centroid,
            clipping_fraction=clipping,
            gaps=gaps,
            open_alerts=open_alerts,
            baseline_note=note,
        )

    def _checks(
        self,
        recorder: RecorderRow,
        recordings: list[RecordingRow],
        rules: AlertRules,
        *,
        level: list[SeriesPoint],
        high_band: list[SeriesPoint],
        centroid: list[SeriesPoint],
        clipping: list[SeriesPoint],
        battery: list[SeriesPoint],
        temperature: list[SeriesPoint],
        gaps: list[Gap],
        uptime: float | None,
        interval: float | None,
        declared: float | None,
    ) -> list[HealthCheck]:
        checks: list[HealthCheck] = []
        if not recordings:
            return [
                HealthCheck(
                    name="recordings", status="unknown", message="No recordings in the window."
                )
            ]
        last = recordings[-1]
        profile = last.signal_profile or {}

        lv = _latest_and_median(level)
        if lv is None:
            checks.append(
                HealthCheck(name="level_dbfs", status="unknown", message="No level data.")
            )
        else:
            value, med = lv
            d = abs(value - med)
            checks.append(
                HealthCheck(
                    name="level_dbfs",
                    status="attention"
                    if d > LEVEL_DRIFT_WARNING_DB
                    else ("watch" if d > LEVEL_DRIFT_DB else "good"),
                    message=f"Latest {value:g} dBFS, median {med:g} dBFS over {len(level)} recordings.",
                    value=round(value, 4),
                    baseline=round(med, 4),
                )
            )
        for name, points, unit, watch_at, attention_at in (
            ("high_band_fraction", high_band, "", 0.10, 0.25),
            ("spectral_centroid_hz", centroid, " Hz", 800.0, 1500.0),
        ):
            lm = _latest_and_median(points)
            if lm is None:
                checks.append(
                    HealthCheck(
                        name=name, status="unknown", message=f"No {name.replace('_', ' ')} data."
                    )
                )
                continue
            value, med = lm
            drop = med - value
            checks.append(
                HealthCheck(
                    name=name,
                    status="attention"
                    if drop >= attention_at
                    else ("watch" if drop >= watch_at else "good"),
                    message=(
                        f"Latest {value:g}{unit}, median {med:g}{unit} over {len(points)} recordings."
                    ),
                    value=round(value, 4),
                    baseline=round(med, 4),
                )
            )
        if clipping:
            v = clipping[-1].v
            status = "attention" if v >= 0.01 else ("watch" if v > CLIPPING_FLOOR else "good")
            checks.append(
                HealthCheck(
                    name="clipping",
                    status=status,  # type: ignore[arg-type]
                    message=f"Latest clipping fraction {v:.4f}; limit {CLIPPING_FLOOR}.",
                    value=round(v, 6),
                    baseline=CLIPPING_FLOOR,
                )
            )
        imbalance = channel_imbalance_db(profile) if profile else None
        if imbalance is not None:
            checks.append(
                HealthCheck(
                    name="channel_balance",
                    status="watch" if imbalance > CHANNEL_IMBALANCE_DB else "good",
                    message=f"Channels differ by {imbalance:.1f} dB; limit {CHANNEL_IMBALANCE_DB:g} dB.",
                    value=round(imbalance, 2),
                    baseline=CHANNEL_IMBALANCE_DB,
                )
            )
        dc = profile.get("dc_offset")
        if dc is not None:
            checks.append(
                HealthCheck(
                    name="dc_offset",
                    status="watch" if abs(float(dc)) > DC_OFFSET_LIMIT else "good",
                    message=f"DC offset {float(dc):+.4f}; limit {DC_OFFSET_LIMIT}.",
                    value=round(float(dc), 5),
                    baseline=DC_OFFSET_LIMIT,
                )
            )
        if battery:
            limit = rules.battery_low_v.get(recorder.make, rules.battery_low_v.get("other", 3.6))
            v = battery[-1].v
            status = "attention" if v < limit else ("watch" if v < limit + 0.2 else "good")
            checks.append(
                HealthCheck(
                    name="battery",
                    status=status,  # type: ignore[arg-type]
                    message=f"Latest battery {v:.2f} V; low below {limit:.2f} V for {recorder.make.replace('_', ' ')}.",
                    value=round(v, 3),
                    baseline=limit,
                )
            )
        else:
            checks.append(
                HealthCheck(name="battery", status="unknown", message="No battery telemetry.")
            )
        if temperature:
            v = temperature[-1].v
            ok = rules.temperature_min_c <= v <= rules.temperature_max_c
            checks.append(
                HealthCheck(
                    name="temperature",
                    status="good" if ok else "watch",
                    message=f"Latest {v:.1f} C; allowed {rules.temperature_min_c:g} to {rules.temperature_max_c:g} C.",
                    value=round(v, 2),
                )
            )
        if interval:
            checks.append(
                HealthCheck(
                    name="gaps",
                    status="attention" if gaps else "good",
                    message=(
                        f"{len(gaps)} gap{'s' if len(gaps) != 1 else ''} longer than "
                        f"{max(rules.gap_multiplier * interval / 60.0, rules.gap_min_hours):.1f} h "
                        "inside the recording window "
                        f"({'declared' if declared else 'inferred'} interval {interval:g} min)."
                    ),
                    value=float(len(gaps)),
                    baseline=interval,
                )
            )
            if uptime is not None:
                checks.append(
                    HealthCheck(
                        name="uptime_7d",
                        status="good"
                        if uptime >= 0.9
                        else ("watch" if uptime >= 0.6 else "attention"),
                        message=(
                            f"{uptime * 100:.0f}% of the recordings the schedule expects arrived "
                            "in the 7 days up to the latest one."
                        ),
                        value=round(uptime, 4),
                        baseline=1.0,
                    )
                )
        else:
            checks.append(
                HealthCheck(
                    name="gaps",
                    status="unknown",
                    message="Interval unknown: declare expected_interval_minutes on the deployment or upload more recordings.",
                )
            )
        return checks
