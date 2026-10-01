"""Report templates and the user-entered fields each one needs.

``field_schema.json`` is ``docs/REPORTING.md`` section 7 with a label, help
text and a ``required`` flag per field. Template letters a to e in that
document map to the API keys ``evidence``, ``nrcs``, ``aem``,
``certification`` and ``credit``. Page outlines come from section 6.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from thicket.api.platform_schemas import (
    ReportField,
    ReportTemplate,
    ReportTemplateKey,
    ReportTemplates,
)

SCHEMA_PATH = Path(__file__).with_name("field_schema.json")

TEMPLATE_META: dict[ReportTemplateKey, dict] = {
    ReportTemplateKey.evidence: {
        "title": "Thicket Evidence Package",
        "audience": "Anyone who needs the complete, checkable record: land managers, ecologists, funders.",
        "description": (
            "The full record of a monitoring period: what was recorded, where and when, every "
            "species table with plausibility and review columns, quality checks, the review log, "
            "limitations and a provenance appendix with file hashes."
        ),
        "pages": [
            "Cover",
            "Summary",
            "Site and deployment",
            "Methods",
            "Results: species",
            "Results: timeline and metrics",
            "Quality",
            "Review log",
            "Limitations",
            "Provenance appendix",
            "Data dictionary and attestation",
        ],
    },
    ReportTemplateKey.nrcs: {
        "title": "NRCS practice documentation annex",
        "audience": "NRCS field office planners and the participant's case file (EQIP, CSP, RCPP).",
        "description": (
            "A dated field log, map and photo pages, target species presence per date and a "
            "provenance statement, shaped to slot into the case file as supporting documentation. "
            "It is not a practice certification."
        ),
        "pages": [
            "Header",
            "Field log",
            "Map and photos",
            "Target species presence",
            "Habitat context",
            "Provenance and statement",
        ],
    },
    ReportTemplateKey.aem: {
        "title": "NY AEM Tier 5 evaluation annex",
        "audience": "County Soil and Water Conservation District planners (New York AEM).",
        "description": (
            "Evidence offered for the planner's Tier 5A or 5B evaluation: the BMP under evaluation, "
            "the Tier 2 worksheet rows it speaks to, a season-matched before and after comparison, "
            "field evidence and provenance. The planner owns the rating."
        ),
        "pages": [
            "Header",
            "BMP under evaluation",
            "Worksheet linkage",
            "Before and after",
            "Field evidence",
            "Planner notes and provenance",
        ],
    },
    ReportTemplateKey.certification: {
        "title": "Certification monitoring summary",
        "audience": "Certifiers and verifiers (ROC, Land to Market EOV, Audubon Conservation Ranching, Regenified, AGW).",
        "description": (
            "Management context, a native fauna record with dates and review status, the "
            "monitoring design, indicator values per period and a clear statement of what this "
            "is not (not the certifier's own index or observation)."
        ),
        "pages": [
            "Header",
            "Management context",
            "Native fauna record",
            "Monitoring design",
            "Indicators and trend",
            "Limits and provenance",
        ],
    },
    ReportTemplateKey.credit: {
        "title": "Biodiversity credit monitoring report",
        "audience": "Validation and verification bodies and registries (CCB, PV Nature, Nature Framework, TNFD-aligned).",
        "description": (
            "Project details, the monitoring plan versus what was implemented, equipment and data "
            "capture, identification method and validation, results per stratum and period, a "
            "baseline comparison with intervals, QA/QC, data provenance, safeguards and attestation. "
            "No credit arithmetic."
        ),
        "pages": [
            "Project details",
            "Monitoring plan vs implemented",
            "Equipment and data capture",
            "Identification method",
            "Results",
            "Baseline comparison and uncertainty",
            "QA/QC",
            "Data provenance and availability",
            "Safeguards and public summary",
            "Attestation",
        ],
    },
}


@lru_cache(maxsize=1)
def raw_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["report_field_schema"]


def letter_map() -> dict[str, ReportTemplateKey]:
    return {k: ReportTemplateKey(v) for k, v in raw_schema()["templates"].items()}


@lru_cache(maxsize=1)
def all_fields() -> list[ReportField]:
    letters = letter_map()
    out: list[ReportField] = []
    for f in raw_schema()["fields"]:
        out.append(
            ReportField(
                name=f["name"],
                type=f["type"],
                group=f["group"],
                templates=[letters[t] for t in f["templates"]],
                label=f["label"],
                help=f.get("help"),
                required=bool(f.get("required", False)),
                options=f.get("options"),
                example=f.get("example"),
            )
        )
    return out


def fields_for(template: ReportTemplateKey) -> list[ReportField]:
    return [f for f in all_fields() if template in f.templates]


def field_by_name(name: str) -> ReportField | None:
    return next((f for f in all_fields() if f.name == name), None)


def template(key: ReportTemplateKey) -> ReportTemplate:
    meta = TEMPLATE_META[key]
    return ReportTemplate(
        key=key,
        title=meta["title"],
        audience=meta["audience"],
        description=meta["description"],
        pages=list(meta["pages"]),
        fields=fields_for(key),
    )


def templates() -> ReportTemplates:
    return ReportTemplates(templates=[template(k) for k in ReportTemplateKey])


def is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list | dict):
        return len(value) == 0
    return False


def missing_fields(key: ReportTemplateKey, values: dict) -> list[str]:
    """Template fields left blank, required ones first, then in schema order."""
    fields = fields_for(key)
    missing = [f for f in fields if is_blank(values.get(f.name))]
    return [f.name for f in missing if f.required] + [f.name for f in missing if not f.required]


def unknown_fields(key: ReportTemplateKey, values: dict) -> list[str]:
    names = {f.name for f in fields_for(key)}
    return sorted(k for k in values if k not in names)


def forbidden_wording() -> list[str]:
    """Phrases from docs/REPORTING.md section 8 that the renderer must never produce."""
    return list(FORBIDDEN_PHRASES)


FORBIDDEN_PHRASES = (
    "individuals",
    "population of",
    "abundance increased",
    "density",
    "species absent",
    "absent",
    "practice certified",
    "meets nrcs standard",
    "wheg score",
    "cart points",
    "tier 5 evaluation complete",
    "level of concern reduced",
    "bird-friendliness index",
    "ehi",
    "regenerating",
    "verified",
    "credits earned",
    "1% uplift",
    "quality hectares",
    "compliance with",
    "no take",
    "because of the practice",
    "precision 0.9",
    "biodiversity score",
)
