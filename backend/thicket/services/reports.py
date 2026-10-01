"""Report jobs: create a row, render on the worker pool's batch lane, poll.

``create`` validates the request against the template's field schema,
stores a ``queued`` row and schedules :meth:`render`, which assembles the
bundle (:mod:`thicket.reports.bundle`), writes it next to the PDF, renders
(:mod:`thicket.reports.render`) and updates the row to ``ready`` (or
``failed`` with a plain message). Both files live under ``<data>/reports``.
"""

from __future__ import annotations

import hashlib
import logging
import math
from datetime import UTC, datetime
from pathlib import Path

from thicket.api.platform_schemas import Report, ReportCreate, ReportTemplateKey
from thicket.config import Settings
from thicket.errors import invalid_parameter, not_found
from thicket.ids import is_valid_id
from thicket.persistence.db import ReportRow
from thicket.persistence.platform_repositories import PlatformRepository
from thicket.persistence.repositories import Repository
from thicket.reports import field_schema
from thicket.reports.bundle import build_bundle, dumps, sha256_text
from thicket.reports.render import ReportRenderer
from thicket.services.analysis import AnalysisService
from thicket.services.intake import clean_text
from thicket.services.results import validate_threshold
from thicket.services.storage import Storage

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
MAX_FIELD_TEXT = 4000
MAX_LIST_ITEMS = 200


class ReportService:
    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        repo: Repository,
        platform: PlatformRepository,
        analysis: AnalysisService,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.repo = repo
        self.platform = platform
        self.analysis = analysis

    # -- validation -----------------------------------------------------------
    def _clean_fields(self, key: ReportTemplateKey, values: dict) -> dict:
        unknown = field_schema.unknown_fields(key, values)
        if unknown:
            raise invalid_parameter(
                f"Unknown report field{'s' if len(unknown) != 1 else ''}: {', '.join(unknown[:5])}.",
                field="fields",
            )
        out: dict = {}
        for name, value in values.items():
            spec = field_schema.field_by_name(name)
            if spec is None or field_schema.is_blank(value):
                continue
            if spec.type in ("string", "text", "date", "datetime", "enum"):
                if not isinstance(value, str):
                    value = str(value)
                text = clean_text(value, MAX_FIELD_TEXT, name)
                if text is None:
                    continue
                if spec.type == "enum" and spec.options and text not in spec.options:
                    raise invalid_parameter(
                        f"{name} must be one of: {', '.join(spec.options)}.", field=name
                    )
                out[name] = text
            elif spec.type in ("number", "integer"):
                try:
                    num = float(value)
                except (TypeError, ValueError) as exc:
                    raise invalid_parameter(f"{name} must be a number.", field=name) from exc
                if not math.isfinite(num):
                    # NaN would print as "not provided"; inf breaks int() and the bundle JSON.
                    raise invalid_parameter(f"{name} must be a finite number.", field=name)
                out[name] = int(num) if spec.type == "integer" else num
            elif spec.type == "boolean":
                out[name] = (
                    bool(value)
                    if not isinstance(value, str)
                    else value.lower() in ("true", "yes", "1")
                )
            elif spec.type == "list":
                if not isinstance(value, list):
                    raise invalid_parameter(f"{name} must be a list.", field=name)
                if len(value) > MAX_LIST_ITEMS:
                    raise invalid_parameter(f"{name} has too many items.", field=name)
                cleaned = []
                for item in value:
                    if isinstance(item, dict):
                        cleaned.append(
                            {
                                str(k)[:60]: (
                                    clean_text(str(v), 500, name) if v is not None else None
                                )
                                for k, v in item.items()
                            }
                        )
                    else:
                        text = clean_text(str(item), 500, name)
                        if text:
                            cleaned.append(text)
                out[name] = cleaned
            elif spec.type == "file":
                if not isinstance(value, str) or not is_valid_id(value, "file"):
                    raise invalid_parameter(
                        f"{name} must be the id of an uploaded file (POST /orgs/{{org}}/files).",
                        field=name,
                    )
                out[name] = value
        return out

    def create(self, org_id: str, body: ReportCreate, user_id: str) -> Report:
        if body.period_start > body.period_end:
            raise invalid_parameter(
                "period_start must not be after period_end.", field="period_start"
            )
        if (body.baseline_start is None) != (body.baseline_end is None):
            raise invalid_parameter(
                "Set both baseline_start and baseline_end, or neither.", field="baseline_start"
            )
        if body.baseline_start and body.baseline_end and body.baseline_start > body.baseline_end:
            raise invalid_parameter(
                "baseline_start must not be after baseline_end.", field="baseline_start"
            )
        threshold = (
            validate_threshold(body.decision_threshold, self.settings.raw_threshold, 0.0)
            if body.decision_threshold is not None
            else None
        )
        for sid in body.site_ids:
            site = self.platform.get_site(sid) if is_valid_id(sid, "site") else None
            if site is None or site.organization_id != org_id:
                raise invalid_parameter(
                    "site_ids must be sites of this organization.", field="site_ids"
                )
        fields = self._clean_fields(body.template, dict(body.fields))
        for name, value in fields.items():
            spec = field_schema.field_by_name(name)
            if spec is not None and spec.type == "file":
                f = self.platform.get_file(str(value))
                if f is None or f.organization_id != org_id:
                    raise invalid_parameter(
                        f"{name} refers to a file this organization does not have.", field=name
                    )
        title = clean_text(body.title, 200, "title") or "Thicket report"
        row = self.platform.create_report(
            {
                "organization_id": org_id,
                "template": body.template.value,
                "title": title,
                "status": "queued",
                "created_by": user_id,
                "period_start": body.period_start,
                "period_end": body.period_end,
                "baseline_start": body.baseline_start,
                "baseline_end": body.baseline_end,
                "site_ids": list(body.site_ids),
                "decision_threshold": threshold,
                "include_review_log": body.include_review_log,
                "include_raw_manifest": body.include_raw_manifest,
                "fields": fields,
                "missing_fields": field_schema.missing_fields(body.template, fields),
            }
        )
        log.info(
            "report queued", extra={"report_id": row.id, "org_id": org_id, "template": row.template}
        )
        self.analysis.submit_task(lambda: self.render(row.id), batch=True)
        return self.model(row)

    # -- rendering ------------------------------------------------------------
    def render(self, report_id: str) -> ReportRow | None:
        row = self.platform.get_report(report_id)
        if row is None:
            return None
        self.platform.update_report(report_id, {"status": "rendering"})
        try:
            org = self.platform.get_org(row.organization_id)
            if org is None:
                raise RuntimeError("organization missing")
            bundle = build_bundle(self.repo, self.platform, row, org)
            text = dumps(bundle)
            bundle_sha = sha256_text(text)
            bundle_path = self.storage.report_bundle_path(report_id)
            pdf_path = self.storage.report_pdf_path(report_id)
            bundle_path.write_text(text, encoding="utf-8")
            renderer = ReportRenderer(
                bundle,
                bundle_sha,
                logo_path=self.settings.report_logo_path,
                image_resolver=self._image_path,
            )
            result = renderer.render(pdf_path)
            pdf_sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            updated = self.platform.update_report(
                report_id,
                {
                    "status": "ready",
                    "completed_at": datetime.now(UTC),
                    "analysis_count": len(bundle["recordings"]),
                    "page_count": result.page_count,
                    "checksum_sha256": pdf_sha,
                    "bundle_sha256": bundle_sha,
                    "warnings": [*bundle.get("warnings", []), *result.warnings],
                    "missing_fields": list(bundle.get("missing_fields", [])),
                    "pdf_uri": self.storage.storage_uri(pdf_path),
                    "bundle_uri": self.storage.storage_uri(bundle_path),
                },
            )
            log.info(
                "report rendered",
                extra={
                    "report_id": report_id,
                    "pages": result.page_count,
                    "analyses": len(bundle["recordings"]),
                },
            )
            return updated
        except Exception:  # noqa: BLE001 - the row carries a plain message, the log the trace
            log.exception("report rendering failed", extra={"report_id": report_id})
            return self.platform.update_report(
                report_id,
                {
                    "status": "failed",
                    "completed_at": datetime.now(UTC),
                    "error_message": "The report could not be rendered because of an internal error.",
                },
            )

    def _image_path(self, file_id: str) -> Path | None:
        f = self.platform.get_file(file_id)
        if f is None:
            return None
        return self.storage.resolve_uri(f.storage_uri)

    # -- reads ----------------------------------------------------------------
    def model(self, row: ReportRow) -> Report:
        ready = row.status == "ready"
        return Report(
            id=row.id,
            organization_id=row.organization_id,
            template=ReportTemplateKey(row.template),
            title=row.title,
            status=row.status,  # type: ignore[arg-type]
            created_by=row.created_by,
            created_at=row.created_at,
            completed_at=row.completed_at,
            period_start=row.period_start,
            period_end=row.period_end,
            site_ids=list(row.site_ids or []),
            analysis_count=int(row.analysis_count or 0),
            page_count=row.page_count,
            pdf_url=f"{API_PREFIX}/reports/{row.id}.pdf" if ready else None,
            json_url=f"{API_PREFIX}/reports/{row.id}.json" if ready else None,
            checksum_sha256=row.checksum_sha256,
            warnings=list(row.warnings or []),
            missing_fields=list(row.missing_fields or []),
            error_message=row.error_message,
        )

    def pdf_path(self, row: ReportRow) -> Path:
        if row.status != "ready" or not row.pdf_uri:
            raise not_found("The report is not ready yet.")
        path = self.storage.resolve_uri(row.pdf_uri)
        if path is None or not path.is_file():
            raise not_found("The report file is missing.")
        return path

    def bundle_path(self, row: ReportRow) -> Path:
        if row.status != "ready" or not row.bundle_uri:
            raise not_found("The report is not ready yet.")
        path = self.storage.resolve_uri(row.bundle_uri)
        if path is None or not path.is_file():
            raise not_found("The report bundle is missing.")
        return path

    def delete(self, row: ReportRow) -> None:
        self.platform.delete_report(row.id)
        for uri in (row.pdf_uri, row.bundle_uri):
            p = self.storage.resolve_uri(uri)
            if p is not None:
                p.unlink(missing_ok=True)
        log.info("report deleted", extra={"report_id": row.id})
