"""Render a report bundle to PDF with ReportLab and matplotlib (Agg).

One renderer serves the five templates in ``docs/REPORTING.md`` section 6:
each has its own cover and header block, then the pages its outline lists,
built from shared blocks (summary, sites and deployments, methods, species,
timeline and metrics, quality, review log, limitations, provenance, data
dictionary and attestation). A period with no recordings renders a clear
"no recordings in this period" page instead of failing.

Every page footer prints the report id, the software version, the platform
schema version and the SHA-256 of the JSON bundle. Charts use a calm palette
(forest greens on paper). No wording from section 8 is produced here; a test
extracts the PDF text and checks.
"""

from __future__ import annotations

import io
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from matplotlib.figure import Figure
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

FOREST_600 = "#377157"
FOREST_700 = "#2f5c47"
FOREST_800 = "#224235"
FOREST_300 = "#8fbfa6"
FOREST_100 = "#deeee5"
PAPER = "#f6f8f4"
INK = "#1f2d26"
MUTED = "#6b7a72"
RULE = "#d7e2db"
SERIES = [FOREST_700, "#5b8f73", "#8fbfa6", "#b7d6c4", "#3f5f52", "#7aa58d", "#a9c9b6", "#2a4a3a"]

PAGE_W, PAGE_H = letter
MARGIN = 0.75 * inch
MAX_TIMELINES = 12
MAX_TABLE_ROWS = 400


@dataclass
class RenderResult:
    page_count: int
    warnings: list[str]


# -------------------------------------------------------------- styling


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "body",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        textColor=INK,
    )
    return {
        "title": ParagraphStyle(
            "title",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=27,
            textColor=FOREST_800,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=body, fontSize=12, leading=16, textColor=FOREST_700
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            textColor=FOREST_800,
            spaceBefore=6,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=FOREST_700,
            spaceBefore=8,
            spaceAfter=3,
        ),
        "body": body,
        "small": ParagraphStyle("small", parent=body, fontSize=8, leading=10.5, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=body, fontSize=8, leading=10),
        "cellb": ParagraphStyle(
            "cellb",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=FOREST_800,
        ),
        "mono": ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=7.5, leading=9.5),
        "note": ParagraphStyle(
            "note",
            parent=body,
            fontSize=9,
            leading=12.5,
            textColor=FOREST_800,
            backColor=FOREST_100,
            borderPadding=(6, 8, 6, 8),
            alignment=TA_LEFT,
        ),
    }


def _p(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")).replace("\n", "<br/>"), style)


def _italic(text: str, style: ParagraphStyle) -> Paragraph:
    """Escaped text set in italics (scientific names)."""
    return Paragraph(f"<i>{escape(text)}</i>", style)


def _fmt(value: object, digits: int = 2) -> str:
    if value is None or value == "":
        return "not provided"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "not provided"
        return f"{value:.{digits}f}"
    if isinstance(value, list):
        return ", ".join(_fmt(v) for v in value) if value else "not provided"
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_fmt(v)}" for k, v in value.items()) or "not provided"
    return str(value)


def _when(iso: str | None) -> str:
    if not iso:
        return "unknown time"
    return iso.replace("T", " ")[:16]


def _table(
    rows: Sequence[Sequence[object]],
    styles: dict,
    *,
    widths: Sequence[float] | None = None,
    header: bool = True,
    zebra: bool = True,
) -> Table:
    data = []
    for i, row in enumerate(rows):
        style = styles["cellb"] if (header and i == 0) else styles["cell"]
        data.append(
            [
                c if hasattr(c, "wrap") else _p(_fmt(c) if not isinstance(c, str) else c, style)
                for c in row
            ]
        )
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    ts = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(FOREST_300)),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, colors.HexColor(RULE)),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        ts.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(FOREST_100)))
    if zebra:
        for i in range(1 if header else 0, len(data)):
            if i % 2 == 0:
                ts.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor(PAPER)))
    t.setStyle(TableStyle(ts))
    return t


def _kv(
    pairs: Sequence[tuple[str, object]], styles: dict, widths=(2.1 * inch, 4.7 * inch)
) -> Table:  # type: ignore[no-untyped-def]
    rows = [[_p(k, styles["cellb"]), _p(_fmt(v), styles["cell"])] for k, v in pairs]
    t = Table(rows, colWidths=list(widths), hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(RULE)),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return t


# ---------------------------------------------------------------- charts


def _fig_image(fig, width: float, height: float) -> Image:  # type: ignore[no-untyped-def]
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", metadata={"Software": None})
    buf.seek(0)
    return Image(buf, width=width, height=height)


def _style_axes(ax) -> None:  # type: ignore[no-untyped-def]
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(RULE)
    ax.tick_params(colors=MUTED, labelsize=7)
    ax.yaxis.label.set_color(INK)
    ax.xaxis.label.set_color(INK)
    ax.grid(axis="y", color=RULE, linewidth=0.5)
    ax.set_axisbelow(True)


def richness_chart(by_day: Sequence[dict], baseline: dict | None) -> Image | None:
    if not by_day:
        return None
    fig = Figure(figsize=(6.6, 2.6), facecolor="white")
    ax = fig.subplots()
    xs = list(range(len(by_day)))
    ys = [d["species_richness"] for d in by_day]
    if baseline and baseline.get("richness_by_day"):
        b = [d["species_richness"] for d in baseline["richness_by_day"]]
        med = sorted(b)[len(b) // 2]
        mad = sorted(abs(v - med) for v in b)[len(b) // 2] * 1.4826
        ax.axhspan(
            max(0, med - mad), med + mad, color=FOREST_100, label="baseline median, 1 MAD band"
        )
        ax.axhline(med, color=FOREST_300, linewidth=1, linestyle="--")
    ax.plot(
        xs,
        ys,
        color=FOREST_700,
        linewidth=1.6,
        marker="o",
        markersize=3.2,
        label="species counted per day",
    )
    ax.set_ylabel("species counted", fontsize=8)
    step = max(1, len(by_day) // 8)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([by_day[i]["date"][5:] for i in xs[::step]], fontsize=7)
    ax.set_ylim(bottom=0)
    _style_axes(ax)
    ax.legend(fontsize=7, frameon=False, loc="upper left")
    return _fig_image(fig, 6.6 * inch, 2.6 * inch)


def species_chart(species: Sequence[dict], limit: int = 15) -> Image | None:
    top = list(species[:limit])
    if not top:
        return None
    fig = Figure(figsize=(6.6, 0.28 * len(top) + 0.8), facecolor="white")
    ax = fig.subplots()
    names = [s["common_name"] for s in top][::-1]
    vals = [s["detection_events"] for s in top][::-1]
    ax.barh(names, vals, color=FOREST_600, height=0.6)
    ax.set_xlabel("detection events", fontsize=8)
    ax.tick_params(axis="y", labelsize=7)
    _style_axes(ax)
    ax.grid(axis="x", color=RULE, linewidth=0.5)
    ax.grid(axis="y", visible=False)
    return _fig_image(fig, 6.6 * inch, (0.28 * len(top) + 0.8) * inch)


def timeline_strip(entry: dict, max_species: int = 8) -> Image | None:
    events = entry.get("events") or []
    if not events:
        return None
    counted = [e for e in events if e["counted_in_metrics"]]
    order: list[str] = []
    for e in sorted(counted, key=lambda e: e["start_seconds"]):
        if e["common_name"] not in order:
            order.append(e["common_name"])
    order = order[:max_species]
    if not order:
        order = ["other sounds"]
    rows = {name: i for i, name in enumerate(order)}
    fig = Figure(figsize=(6.6, 0.26 * len(order) + 0.7), facecolor="white")
    ax = fig.subplots()
    dur = float(entry.get("duration_seconds") or 0.0)
    for e in events:
        name = e["common_name"] if e["counted_in_metrics"] else "other sounds"
        if name not in rows:
            continue
        y = rows[name]
        color = SERIES[y % len(SERIES)] if e["counted_in_metrics"] else "#c9d1cc"
        ax.broken_barh(
            [(e["start_seconds"], max(0.4, e["end_seconds"] - e["start_seconds"]))],
            (y - 0.35, 0.7),
            color=color,
        )
    ax.set_yticks(list(rows.values()))
    ax.set_yticklabels(list(rows.keys()), fontsize=7)
    ax.set_xlim(0, max(dur, 1.0))
    ax.set_xlabel("seconds", fontsize=7)
    ax.invert_yaxis()
    _style_axes(ax)
    ax.grid(axis="y", visible=False)
    return _fig_image(fig, 6.6 * inch, (0.26 * len(order) + 0.7) * inch)


# -------------------------------------------------------------- renderer


class ReportRenderer:
    def __init__(
        self,
        bundle: dict,
        bundle_sha256: str,
        *,
        logo_path: Path | None = None,
        image_resolver: Callable[[str], Path | None] | None = None,
    ) -> None:
        self.b = bundle
        self.sha = bundle_sha256
        self.logo = logo_path if logo_path and logo_path.is_file() else None
        self.resolve_image = image_resolver or (lambda _fid: None)
        self.s = _styles()
        self.warnings: list[str] = []
        self.template = bundle["report"]["template"]
        self.fields = dict(bundle.get("fields") or {})
        self.labels = dict(bundle.get("field_labels") or {})

    # -- page furniture -----------------------------------------------------
    def _on_page(self, canvas, doc) -> None:  # type: ignore[no-untyped-def]
        r = self.b["report"]
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor(RULE))
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, PAGE_H - MARGIN + 10, PAGE_W - MARGIN, PAGE_H - MARGIN + 10)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(
            MARGIN, PAGE_H - MARGIN + 14, f"{self.b['organization']['name']}  |  {r['title']}"[:120]
        )
        canvas.drawRightString(
            PAGE_W - MARGIN, PAGE_H - MARGIN + 14, f"{r['period_start']} to {r['period_end']}"
        )
        canvas.line(MARGIN, MARGIN - 14, PAGE_W - MARGIN, MARGIN - 14)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(
            MARGIN,
            MARGIN - 24,
            f"Report {r['id']}  |  Thicket {r['software_version']}  |  platform schema "
            f"{r['platform_schema_version']}",
        )
        canvas.drawRightString(PAGE_W - MARGIN, MARGIN - 24, f"page {doc.page}")
        canvas.drawString(MARGIN, MARGIN - 33, f"bundle sha256 {self.sha}")
        canvas.restoreState()

    def render(self, out_path: Path) -> RenderResult:
        doc = BaseDocTemplate(
            str(out_path),
            pagesize=letter,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=MARGIN + 6,
            bottomMargin=MARGIN + 6,
            title=self.b["report"]["title"],
            author=self.b["organization"]["name"],
            subject=f"Thicket report {self.b['report']['template']}",
            creator=f"Thicket {self.b['report']['software_version']}",
            invariant=1,
        )
        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
        doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=self._on_page)])
        story = self.story()
        doc.build(story)
        return RenderResult(page_count=doc.page, warnings=list(self.warnings))

    # -- story --------------------------------------------------------------
    def story(self) -> list:
        parts: list = []
        parts += self.cover()
        if not self.b["recordings"]:
            parts += [PageBreak(), *self.no_recordings_page()]
            parts += [PageBreak(), *self.provenance_block()]
            parts += [PageBreak(), *self.attestation_block()]
            return parts
        builder = {
            "evidence": self.evidence_pages,
            "nrcs": self.nrcs_pages,
            "aem": self.aem_pages,
            "certification": self.certification_pages,
            "credit": self.credit_pages,
        }[self.template]
        parts += builder()
        return parts

    def _field(self, name: str) -> object:
        return self.fields.get(name)

    def _label(self, name: str) -> str:
        return self.labels.get(name, name.replace("_", " ").capitalize())

    def _field_rows(self, names: Sequence[str]) -> list[tuple[str, object]]:
        return [(self._label(n), self._field(n)) for n in names]

    def _section(self, title: str) -> list:
        return [PageBreak(), _p(title, self.s["h1"])]

    # -- covers -------------------------------------------------------------
    def cover(self) -> list:
        r, o, f = self.b["report"], self.b["organization"], self.fields
        s = self.s
        parts: list = []
        if self.logo:
            try:
                parts.append(
                    Image(
                        str(self.logo),
                        width=1.4 * inch,
                        height=0.7 * inch,
                        kind="proportional",
                        hAlign="LEFT",
                    )
                )
            except Exception:  # noqa: BLE001
                self.warnings.append(
                    "The logo could not be read; the cover was rendered without it."
                )
        heading = {
            "evidence": "Thicket Evidence Package",
            "nrcs": "NRCS practice documentation annex",
            "aem": "NY AEM Tier 5 evaluation annex",
            "certification": "Certification monitoring summary",
            "credit": "Biodiversity credit monitoring report",
        }[self.template]
        parts += [
            Spacer(1, 0.6 * inch),
            _p(heading, s["subtitle"]),
            _p(r["title"], s["title"]),
            Spacer(1, 0.25 * inch),
            _p(
                f"{f.get('property_name') or o['name']}  |  {r['period_start']} to {r['period_end']}",
                s["subtitle"],
            ),
            Spacer(1, 0.4 * inch),
        ]
        pairs = [
            ("Organization", f.get("organization_name") or o["name"]),
            ("Prepared by", _join(f.get("preparer_name"), f.get("preparer_role"))),
            ("Prepared for", f.get("prepared_for")),
            ("Monitoring period", f"{r['period_start']} to {r['period_end']} ({r['timezone']})"),
            ("Sites", len(self.b["sites"])),
            ("Recordings analyzed", self.b["summary"]["recordings"]),
            ("Analysis ids", _id_list([e["analysis_id"] for e in self.b["recordings"]])),
            (
                "Decision threshold",
                f"{r['decision_threshold']:g}"
                if r["decision_threshold"] is not None
                else "each analysis's own",
            ),
            ("Generated", r["generated_at"].replace("T", " ")[:19] + " UTC"),
            ("Bundle checksum (SHA-256)", self.sha),
        ]
        parts.append(_kv(pairs, s))
        if self.template == "nrcs":
            parts += [
                Spacer(1, 0.2 * inch),
                _p("Identifier block", s["h2"]),
                _kv(
                    self._field_rows(
                        [
                            "participant_name",
                            "nrcs_program",
                            "nrcs_contract_number",
                            "fsa_farm_number",
                            "fsa_tract_number",
                            "fsa_field_numbers",
                            "county",
                            "state",
                            "practice_code",
                            "practice_name",
                            "enhancement_code",
                            "contract_item_number",
                            "planned_amount",
                            "applied_amount",
                            "amount_unit",
                            "fiscal_year",
                            "nrcs_planner_name",
                            "conservation_plan_id",
                        ]
                    ),
                    s,
                ),
            ]
        elif self.template == "aem":
            parts += [
                Spacer(1, 0.2 * inch),
                _p("AEM header", s["h2"]),
                _kv(
                    self._field_rows(
                        [
                            "aem_id",
                            "county_swcd",
                            "swcd_planner_name",
                            "evaluating_agency",
                            "farm_name",
                            "owner_name",
                            "operator_name",
                            "watershed_name",
                            "huc12",
                            "aem_tier",
                        ]
                    ),
                    s,
                ),
            ]
        elif self.template == "certification":
            parts += [
                Spacer(1, 0.2 * inch),
                _p("Program header", s["h2"]),
                _kv(
                    self._field_rows(
                        [
                            "certification_program",
                            "certifier_name",
                            "certification_id",
                            "audit_date",
                            "operation_name",
                            "land_base_acres",
                        ]
                    ),
                    s,
                ),
            ]
        elif self.template == "credit":
            parts += [
                Spacer(1, 0.2 * inch),
                _p("Project details", s["h2"]),
                _kv(
                    self._field_rows(
                        [
                            "project_id",
                            "registry",
                            "standard_version",
                            "project_proponent",
                            "monitoring_period_start",
                            "monitoring_period_end",
                            "vvb_name",
                            "land_tenure_note",
                        ]
                    ),
                    s,
                ),
            ]
            strata = self._field("strata_definitions")
            if isinstance(strata, list) and strata:
                rows = [["Stratum", "Habitat type", "Hectares"]] + [
                    [
                        str(x.get("stratum", "")),
                        str(x.get("habitat_type", "")),
                        _fmt(x.get("hectares")),
                    ]
                    for x in strata
                    if isinstance(x, dict)
                ]
                parts += [
                    Spacer(1, 6),
                    _table(rows, s, widths=[1.6 * inch, 3.0 * inch, 1.4 * inch]),
                ]
            boundary = self._field("project_boundary_file")
            parts += self._image_block(boundary, "Project boundary")
        missing = self.b.get("missing_fields") or []
        if missing:
            parts += [
                Spacer(1, 0.25 * inch),
                _p(
                    f"{len(missing)} template field{'s' if len(missing) != 1 else ''} left blank: "
                    + ", ".join(self._label(m) for m in missing[:12])
                    + (" and more" if len(missing) > 12 else "")
                    + ". Blank fields print as 'not provided'.",
                    s["small"],
                ),
            ]
        return parts

    def no_recordings_page(self) -> list:
        r = self.b["report"]
        s = self.s
        sites = ", ".join(x["name"] for x in self.b["sites"]) or "the selected sites"
        return [
            _p("No recordings in this period", s["h1"]),
            _p(
                f"No completed analyses fall between {r['period_start']} and {r['period_end']} "
                f"({r['timezone']}) for {sites}. The report therefore has no species table, "
                "metrics, timeline or quality summary. Upload and analyze recordings from this "
                "period, or widen the period, and create the report again.",
                s["body"],
            ),
            Spacer(1, 8),
            _p(
                "A report without recordings makes no statement about which species were or "
                "were not present.",
                s["note"],
            ),
        ]

    # -- template page lists -------------------------------------------------
    def evidence_pages(self) -> list:
        return [
            *self._section("Summary"),
            *self.summary_block(),
            *self._section("Site and deployment"),
            *self.sites_block(),
            *self._section("Methods"),
            *self.methods_block(),
            *self._section("Results: species"),
            *self.species_block(),
            *self._section("Results: timeline and metrics"),
            *self.timeline_block(),
            *self._section("Quality"),
            *self.quality_block(),
            *self._section("Review log"),
            *self.review_block(),
            *self._section("Limitations"),
            *self.limitations_block(),
            *self._section("Provenance appendix"),
            *self.provenance_block(),
            *self._section("Data dictionary and attestation"),
            *self.dictionary_block(),
            *self.attestation_block(),
        ]

    def nrcs_pages(self) -> list:
        s = self.s
        return [
            *self._section("Field log"),
            *self.field_log_block(),
            *self._section("Map and photos"),
            *self.sites_block(photos=True, tract_map=True),
            *self._section("Target species presence"),
            *self.target_species_block(),
            *self._section("Habitat context"),
            _kv(
                self._field_rows(
                    ["habitat_objectives", "limiting_factors", "habitat_management_plan_reference"]
                ),
                s,
            ),
            Spacer(1, 8),
            _p(
                "Thicket quality checks and soundscape index values are context only; they do not score habitat.",
                s["small"],
            ),
            *self.indices_table(),
            *self.quality_block(compact=True),
            *self._section("Provenance and statement"),
            *self.provenance_block(),
            Spacer(1, 10),
            _p(
                "Supporting documentation prepared by the participant. Not a practice certification, "
                "a habitat evaluation score or a ranking assessment. The NRCS planner decides what "
                "this evidence supports.",
                s["note"],
            ),
            *self.attestation_block(),
        ]

    def aem_pages(self) -> list:
        s = self.s
        return [
            *self._section("BMP under evaluation"),
            _kv(
                self._field_rows(
                    [
                        "bmp_system",
                        "practice_code",
                        "bmp_install_date",
                        "funding_program",
                        "project_contract_number",
                        "management_changes_since_last_period",
                    ]
                ),
                s,
            ),
            *self._section("Worksheet linkage"),
            _kv(
                self._field_rows(
                    [
                        "tier2_worksheets_completed",
                        "worksheet_rows_addressed",
                        "level_of_concern_before",
                        "level_of_concern_after",
                    ]
                ),
                s,
            ),
            Spacer(1, 8),
            _p(
                "The levels of concern above are the planner's own ratings as entered on the form; Thicket does not rate worksheet rows.",
                s["small"],
            ),
            *self._section("Before and after"),
            *self.before_after_block(),
            *self._section("Field evidence"),
            *self.sites_block(photos=True),
            *self.field_log_block(compact=True),
            *self._section("Planner notes and provenance"),
            _kv(self._field_rows(["planner_notes"]), s),
            Spacer(1, 8),
            _p(
                "Evidence offered for the planner's Tier 5 evaluation. The SWCD planner owns the evaluation and its outcome.",
                s["note"],
            ),
            *self.provenance_block(),
            *self.attestation_block(),
        ]

    def certification_pages(self) -> list:
        s = self.s
        return [
            *self._section("Management context"),
            _kv(
                self._field_rows(
                    [
                        "pasture_or_paddock_ids",
                        "grazing_system_description",
                        "habitat_practices",
                        "hmp_reference",
                        "management_changes_since_last_period",
                        "sensitive_areas",
                    ]
                ),
                s,
            ),
            *self._section("Native fauna record"),
            *self.species_block(priority=True),
            *self._section("Monitoring design"),
            *self.sites_block(),
            _kv(
                self._field_rows(
                    [
                        "eov_site_ids",
                        "recorder_make",
                        "recorder_model",
                        "mount_height_m",
                        "recording_schedule",
                    ]
                ),
                s,
            ),
            *self._section("Indicators and trend"),
            *self.before_after_block(),
            *self.indices_table(),
            *self._section("Limits and provenance"),
            _p(
                "This summary is a species list and metric set for the certifier's review. It is not "
                "the certifier's own bird index, ecological health index or field observation, and "
                "it does not decide any certification outcome.",
                s["note"],
            ),
            *self.limitations_block(),
            *self.provenance_block(),
            *self.attestation_block(),
        ]

    def credit_pages(self) -> list:
        s = self.s
        return [
            *self._section("Monitoring plan vs implemented"),
            _kv(
                self._field_rows(
                    [
                        "indicator_set",
                        "sampling_design_description",
                        "reference_site_ids",
                        "deviations_from_plan",
                    ]
                ),
                s,
            ),
            Spacer(1, 8),
            *self.effort_table(),
            *self._section("Equipment and data capture"),
            *self.sites_block(),
            _kv(
                self._field_rows(
                    [
                        "recorder_make",
                        "recorder_model",
                        "recorder_serial",
                        "firmware_version",
                        "gain_setting",
                        "sample_rate_setting",
                        "recording_schedule",
                        "mount_height_m",
                        "chain_of_custody_notes",
                    ]
                ),
                s,
            ),
            *self._section("Identification method"),
            *self.methods_block(),
            _kv(
                self._field_rows(
                    [
                        "validation_method",
                        "reviewer_name",
                        "reviewer_qualifications",
                        "analytics_provider",
                    ]
                ),
                s,
            ),
            *self.review_summary(),
            *self._section("Results"),
            *self.credit_results_block(),
            *self.species_block(),
            *self._section("Baseline comparison and uncertainty"),
            *self.before_after_block(intervals=True),
            _kv(self._field_rows(["baseline_period_reference", "uncertainty_method"]), s),
            *self._section("QA/QC"),
            *self.quality_block(),
            _kv(self._field_rows(["qaqc_notes"]), s),
            *self._section("Data provenance and availability"),
            *self.provenance_block(),
            _kv(
                self._field_rows(
                    ["audio_retention_statement", "data_license", "data_access_conditions"]
                ),
                s,
            ),
            *self.dictionary_block(),
            *self._section("Safeguards and public summary"),
            _kv(
                self._field_rows(["landowner_consent", "privacy_statement", "public_summary_text"]),
                s,
            ),
            Spacer(1, 6),
            _p(
                f"Recordings with possible human speech: {self.b['summary']['speech_flagged_recordings']}.",
                s["body"],
            ),
            *self._section("Attestation"),
            *self.attestation_block(),
        ]

    # -- shared blocks --------------------------------------------------------
    def summary_block(self) -> list:
        s, sm = self.s, self.b["summary"]
        parts: list = []
        objective = self._field("monitoring_objective")
        if objective:
            parts += [_p("Monitoring objective", s["h2"]), _p(objective, s["body"])]
        sites = ", ".join(x["name"] for x in self.b["sites"]) or "not assigned"
        parts += [
            _p("What was recorded", s["h2"]),
            _p(
                f"{sm['recordings']} recordings ({sm['minutes_recorded']:.1f} minutes) from {sites}, "
                f"{_when(sm['first_recording_at'])} to {_when(sm['last_recording_at'])}.",
                s["body"],
            ),
            Spacer(1, 6),
            _table(
                [
                    [
                        "Recordings",
                        "Minutes",
                        "Species counted",
                        "Detection events",
                        "Events per minute",
                        "Shannon H'",
                        "Quality",
                    ],
                    [
                        sm["recordings"],
                        f"{sm['minutes_recorded']:.1f}",
                        sm["species_counted"],
                        sm["detection_events"],
                        f"{sm['events_per_minute']:.2f}",
                        f"{sm['shannon_index']:.3f}",
                        _quality_text(sm["quality_counts"]),
                    ],
                ],
                s,
            ),
            Spacer(1, 8),
            _p(
                "Limits in one paragraph: every number comes from acoustic detection events at the "
                "stated threshold, consolidated by species and recording. Events are not animals and "
                "there is no recall estimate, so a species that was not detected is reported as not "
                "detected in this effort. Birds flagged unlikely for the place and week, rejected "
                "events and non-wildlife sounds are listed but not counted.",
                s["small"],
            ),
        ]
        for w in self.b.get("warnings") or []:
            parts.append(_p(w, s["note"]))
        return parts

    def sites_block(self, *, photos: bool = False, tract_map: bool = False) -> list:
        s = self.s
        parts: list = [_p("Sites", s["h2"])]
        rows = [["Site", "Latitude", "Longitude", "Habitat", "Field / paddock", "Area (ha)"]]
        for x in self.b["sites"]:
            rows.append(
                [
                    x["name"],
                    _fmt(x["latitude"], 5) if x["latitude"] is not None else "not provided",
                    _fmt(x["longitude"], 5) if x["longitude"] is not None else "not provided",
                    (
                        x.get("habitat_type") or self._field("habitat_type") or "not provided"
                    ).replace("_", " "),
                    _join(x.get("fsa_field_number"), x.get("paddock_id")),
                    _fmt(x.get("area_hectares"), 1)
                    if x.get("area_hectares") is not None
                    else "not provided",
                ]
            )
        parts.append(
            _table(
                rows,
                s,
                widths=[1.5 * inch, 0.9 * inch, 0.9 * inch, 1.0 * inch, 1.3 * inch, 0.9 * inch],
            )
        )
        if not any(x["latitude"] is not None for x in self.b["sites"]):
            parts.append(
                _p("No coordinates are recorded for these sites, so no map is drawn.", s["small"])
            )
        else:
            parts.append(
                _p(
                    "Recorder points are the coordinates above; draw them on the parcel map in your GIS or on the FSA tract map.",
                    s["small"],
                )
            )
        recorders = {r["id"]: r for r in self.b["recorders"]}
        site_names = {x["id"]: x["name"] for x in self.b["sites"]}
        if self.b["deployments"]:
            rows = [
                [
                    "Recorder",
                    "Make / model",
                    "Serial",
                    "Site",
                    "Start",
                    "End",
                    "Height (m)",
                    "Gain",
                    "Schedule",
                ]
            ]
            for d in self.b["deployments"]:
                r = recorders.get(d["recorder_id"], {})
                rows.append(
                    [
                        r.get("label", "unknown"),
                        _join(
                            r.get("make", "").replace("_", " ") if r.get("make") else None,
                            r.get("model"),
                        ),
                        r.get("serial") or "not provided",
                        site_names.get(d["site_id"], d["site_id"]),
                        _when(d["started_at"]),
                        _when(d["ended_at"]) if d["ended_at"] else "ongoing",
                        _fmt(d.get("mount_height_m"), 1)
                        if d.get("mount_height_m") is not None
                        else "not provided",
                        d.get("gain_setting") or "not provided",
                        d.get("schedule_description")
                        or (
                            f"{d['expected_interval_minutes']:g} min interval"
                            if d.get("expected_interval_minutes")
                            else "not provided"
                        ),
                    ]
                )
            parts += [
                _p("Deployments", s["h2"]),
                _table(
                    rows,
                    s,
                    widths=[
                        0.9 * inch,
                        0.9 * inch,
                        0.8 * inch,
                        0.9 * inch,
                        0.8 * inch,
                        0.8 * inch,
                        0.5 * inch,
                        0.5 * inch,
                        0.9 * inch,
                    ],
                ),
            ]
        else:
            parts += [
                _p("Deployments", s["h2"]),
                _p(
                    "No deployment records overlap this period. Recorder details below come from the report form.",
                    s["small"],
                ),
            ]
        parts += [
            _p("Deployment details from the form", s["h2"]),
            _kv(
                self._field_rows(
                    [
                        "recorder_make",
                        "recorder_model",
                        "recorder_serial",
                        "firmware_version",
                        "microphone_type",
                        "mount_height_m",
                        "orientation",
                        "gain_setting",
                        "recording_schedule",
                        "deployment_start",
                        "deployment_end",
                        "gps_accuracy_m",
                        "distance_to_edge_m",
                        "deployed_by",
                        "weather_summary",
                    ]
                ),
                s,
            ),
        ]
        if photos:
            parts += self._image_block(self._field("deployment_photo"), "Deployment photo")
        if tract_map:
            parts += self._image_block(self._field("tract_map_image"), "FSA tract map")
        return parts

    def _image_block(self, ref: object, title: str) -> list:
        s = self.s
        if not ref:
            return [Spacer(1, 6), _p(f"{title}: not provided.", s["small"])]
        path = self.resolve_image(str(ref)) if isinstance(ref, str) else None
        if path is None or not Path(path).is_file():
            self.warnings.append(f"{title} could not be found; it was left out.")
            return [Spacer(1, 6), _p(f"{title}: file not found.", s["small"])]
        try:
            img = Image(
                str(path), width=5.5 * inch, height=3.6 * inch, kind="proportional", hAlign="LEFT"
            )
        except Exception:  # noqa: BLE001
            self.warnings.append(f"{title} could not be read; it was left out.")
            return [Spacer(1, 6), _p(f"{title}: file could not be read.", s["small"])]
        return [Spacer(1, 6), _p(title, s["h2"]), img]

    def methods_block(self) -> list:
        s = self.s
        models = self.b["models"]
        rows = [["Model", "Version", "Window", "Experimental", "SHA-256"]] + [
            [
                m["model"],
                m["version"],
                f"{m['window_seconds']:g} s",
                "yes" if m["experimental"] else "no",
                _p(m.get("model_sha256") or "n/a", s["mono"]),
            ]
            for m in models
        ]
        settings = self.b["recordings"][0]["settings"] if self.b["recordings"] else {}
        thresholds = sorted({e["decision_threshold"] for e in self.b["recordings"]})
        return [
            _p("Pipeline", s["h2"]),
            _p(
                "Upload, type and size checks, decode with FFmpeg to 48 kHz mono, audio quality checks, "
                "spectrogram, species detector in 3 s windows (every window at or above the ingestion "
                "floor is kept), consolidation of adjacent windows of one species into detection events "
                "at the decision threshold, range and season plausibility for birds, human review, then "
                "species table and metrics from that one event set.",
                s["body"],
            ),
            _p("Models", s["h2"]),
            _table(rows, s, widths=[2.0 * inch, 0.7 * inch, 0.7 * inch, 0.9 * inch, 2.5 * inch])
            if models
            else _p("No model runs.", s["small"]),
            _p("Settings", s["h2"]),
            _kv(
                [
                    ("Decision threshold", ", ".join(f"{t:g}" for t in thresholds) or "n/a"),
                    ("Ingestion floor (raw threshold)", _fmt(settings.get("raw_threshold"))),
                    ("Window hop", f"{settings.get('hop_seconds', 'n/a')} s"),
                    ("Merge gap", f"{settings.get('merge_gap_seconds', 'n/a')} s"),
                    ("Range and season filter", "on" if settings.get("location_filter") else "off"),
                    ("Location filter threshold", _fmt(settings.get("location_filter_threshold"))),
                    ("Survey protocol reference", self._field("survey_protocol_reference")),
                ],
                s,
            ),
            _p("Rules", s["h2"]),
            _p(
                "Consolidation merges windows of one species closer than the merge gap, keeps the "
                "highest and mean score, and never merges across models. Birds below the location "
                "filter threshold for the place and ISO week are flagged unlikely and left out of "
                "metrics; the flag never applies to frogs, insects or mammals. Reviews follow the "
                "reviewed windows: a rejected event is excluded, a correction counts for the "
                "reviewer's label when the models know it. The soundscape QC head flags rain, wind, "
                "water, engines and other contamination from the detector's embeddings.",
                s["body"],
            ),
            _p("Metric definitions", s["h2"]),
            _p(
                "With n_i detection events for species i, N the total and p_i = n_i / N: richness S, "
                "Shannon H' = -sum p_i ln p_i, Pielou J' = H' / ln S for S > 1, Gini-Simpson 1 - sum p_i^2, "
                "events per minute = N / minutes. Acoustic indices: ACI, ADI, AEI, BI, NDSI, spectral and "
                "temporal entropy, computed on the 48 kHz mono signal.",
                s["body"],
            ),
        ]

    def species_block(self, *, priority: bool = False) -> list:
        s = self.s
        species = self.b["species"]
        if not species:
            return [
                _p("No species were counted in this period at the stated threshold.", s["body"])
            ]
        prio = (
            {
                str(x).lower()
                for x in (self._field("priority_species") or self._field("target_species") or [])
            }
            if priority
            else set()
        )
        header = [
            "Common name",
            "Scientific name",
            "Taxon",
            "Events",
            "Recordings",
            "Detected",
            "Max score",
            "Plausibility",
            "Reviewed",
        ]
        if priority:
            header.insert(0, "Priority")
        rows = [header]
        for sp in species[:MAX_TABLE_ROWS]:
            first = sp["first_detected_at"][:10] if sp["first_detected_at"] else None
            last = sp["last_detected_at"][:10] if sp["last_detected_at"] else None
            if not first:
                detected = "no time recorded"
            elif first == last:
                detected = first
            else:
                detected = f"{first} to {last}"
            plaus = sp["plausibility"] if sp["taxon"] == "bird" else "unverified non-bird label"
            row = [
                sp["common_name"],
                _italic(sp["scientific_name"], s["cell"]),
                sp["taxon"],
                sp["detection_events"],
                sp["recordings_with_detection"],
                detected,
                f"{sp['max_confidence']:.2f}",
                plaus,
                _review_text(sp),
            ]
            if priority:
                hit = sp["common_name"].lower() in prio or sp["scientific_name"].lower() in prio
                row.insert(0, "yes" if hit else "")
            rows.append(row)
        if priority:
            inches = [0.6, 0.9, 1.0, 0.65, 0.45, 0.75, 0.75, 0.45, 0.7, 0.75]
        else:
            inches = [1.1, 1.2, 0.65, 0.5, 0.75, 0.8, 0.45, 0.75, 0.8]
        widths = [w * inch for w in inches]
        parts: list = [_table(rows, s, widths=widths)]
        if len(species) > MAX_TABLE_ROWS:
            parts.append(
                _p(
                    f"Showing the first {MAX_TABLE_ROWS} of {len(species)} species; the JSON bundle has them all.",
                    s["small"],
                )
            )
        chart = species_chart(species)
        if chart is not None:
            parts += [Spacer(1, 8), chart]
        parts.append(
            _p(
                "Events are stretches of audio in which the species was detected; they do not count animals.",
                s["small"],
            )
        )
        return parts

    def timeline_block(self) -> list:
        s = self.s
        parts: list = [_p("Species counted per day", s["h2"])]
        chart = richness_chart(self.b["richness_by_day"], self.b.get("baseline"))
        if chart is not None:
            parts.append(chart)
        parts += [_p("Metrics per recording", s["h2"])]
        rows = [
            [
                "Recording",
                "Captured",
                "Site",
                "Min",
                "Richness",
                "Events",
                "Events per min",
                "Shannon",
                "Pielou",
                "Gini-Simpson",
                "Threshold",
            ]
        ]
        for e in self.b["recordings"][:MAX_TABLE_ROWS]:
            m = e["metrics"] or {}
            rows.append(
                [
                    e["filename"][:28],
                    _when(e["captured_at"]),
                    e["site_name"] or "n/a",
                    f"{e['duration_seconds'] / 60:.1f}",
                    m.get("species_richness", 0),
                    m.get("total_detection_events", 0),
                    f"{m.get('events_per_minute', 0):.2f}",
                    f"{m.get('shannon_index', 0):.3f}",
                    f"{m.get('pielou_evenness', 0):.3f}",
                    f"{m.get('simpson_diversity', 0):.3f}",
                    f"{e['decision_threshold']:g}",
                ]
            )
        parts.append(
            _table(
                rows,
                s,
                widths=[
                    w * inch for w in (1.15, 0.8, 0.75, 0.35, 0.6, 0.5, 0.55, 0.6, 0.5, 0.6, 0.6)
                ],
            )
        )
        parts += self.indices_table()
        parts += [_p("Event timelines", s["h2"])]
        shown = 0
        for e in self.b["recordings"]:
            strip = timeline_strip(e)
            if strip is None:
                continue
            parts.append(
                KeepTogether(
                    [
                        _p(
                            f"{e['filename']}  |  {_when(e['captured_at'])}  |  {e['site_name'] or 'no site'}",
                            s["small"],
                        ),
                        strip,
                    ]
                )
            )
            shown += 1
            if shown >= MAX_TIMELINES:
                break
        if shown == 0:
            parts.append(_p("No detection events to draw.", s["small"]))
        elif len(self.b["recordings"]) > MAX_TIMELINES:
            parts.append(
                _p(
                    f"Timelines are drawn for the first {MAX_TIMELINES} recordings; events for all recordings are in the JSON bundle and CSV exports.",
                    s["small"],
                )
            )
        return parts

    def indices_table(self) -> list:
        s = self.s
        rows = [
            ["Recording", "ACI", "ADI", "AEI", "BI", "NDSI", "Spectral entropy", "Temporal entropy"]
        ]
        for e in self.b["recordings"][:MAX_TABLE_ROWS]:
            ai = e.get("acoustic_indices") or {}
            if not ai:
                continue
            rows.append(
                [
                    e["filename"][:28],
                    f"{ai.get('acoustic_complexity_index', 0):.1f}",
                    f"{ai.get('acoustic_diversity_index', 0):.3f}",
                    f"{ai.get('acoustic_evenness_index', 0):.3f}",
                    f"{ai.get('bioacoustic_index', 0):.2f}",
                    f"{ai.get('ndsi', 0):.3f}",
                    f"{ai.get('spectral_entropy', 0):.3f}",
                    f"{ai.get('temporal_entropy', 0):.3f}",
                ]
            )
        if len(rows) == 1:
            return []
        return [
            _p("Acoustic indices", s["h2"]),
            _table(
                rows,
                s,
                widths=[w * inch for w in (1.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.9, 0.9)],
            ),
            _p(
                "Soundscape index values, context only. Indices respond to weather, noise and insects and are not species counts.",
                s["small"],
            ),
        ]

    def quality_block(self, *, compact: bool = False) -> list:
        s = self.s
        counts = self.b["summary"]["quality_counts"]
        parts: list = [
            _p("Quality summary", s["h2"]),
            _table(
                [
                    ["Usable", "Usable with warnings", "Not usable", "Speech flagged"],
                    [
                        counts.get("usable", 0),
                        counts.get("usable_with_warnings", 0),
                        counts.get("not_usable", 0),
                        self.b["summary"]["speech_flagged_recordings"],
                    ],
                ],
                s,
            ),
        ]
        if compact:
            return parts
        rows = [
            [
                "Recording",
                "Status",
                "Score",
                "Peak dBFS",
                "RMS dBFS",
                "Clipping",
                "Silence",
                "Speech",
                "Flags",
            ]
        ]
        for e in self.b["recordings"][:MAX_TABLE_ROWS]:
            q = e.get("quality") or {}
            flags = [
                c["name"].replace("soundscape_", "")
                for c in q.get("checks", [])
                if c.get("status") in ("warn", "fail") and c["name"] not in ("speech",)
            ]
            rows.append(
                [
                    e["filename"][:28],
                    (q.get("status") or "n/a").replace("_", " "),
                    f"{q.get('score', 0):.2f}",
                    f"{q.get('peak_dbfs', 0):.1f}",
                    f"{q.get('rms_dbfs', 0):.1f}",
                    f"{q.get('clipping_fraction', 0) * 100:.2f}%",
                    f"{q.get('silence_fraction', 0) * 100:.0f}%",
                    "yes" if q.get("speech_detected") else "no",
                    ", ".join(flags) or "none",
                ]
            )
        parts.append(
            _table(
                rows,
                s,
                widths=[
                    1.5 * inch,
                    0.9 * inch,
                    0.45 * inch,
                    0.6 * inch,
                    0.6 * inch,
                    0.6 * inch,
                    0.5 * inch,
                    0.5 * inch,
                    1.3 * inch,
                ],
            )
        )
        parts.append(
            _p(
                "Recordings rated not usable keep their detections listed; treat them with care. Quality rules are heuristics evaluated on curated clips, not on these sites.",
                s["small"],
            )
        )
        return parts

    def review_summary(self) -> list:
        s = self.s
        log = self.b["review_log"]
        n = len(log)
        acc = sum(1 for r in log if r["review_status"] == "accepted")
        rej = sum(1 for r in log if r["review_status"] == "rejected")
        cor = sum(1 for r in log if r["review_status"] == "corrected")
        total_events = sum(len(e["events"]) for e in self.b["recordings"])
        return [
            _p("Validation summary", s["h2"]),
            _p(
                f"{n} of {total_events} detection events were reviewed: {acc} accepted, {rej} rejected, "
                f"{cor} corrected. Reviewers: {', '.join(self.b.get('reviewers') or []) or self._field('reviewer_name') or 'not recorded'}. "
                "Review counts are reported as such; no field accuracy figure is claimed.",
                s["body"],
            ),
        ]

    def review_block(self) -> list:
        s = self.s
        parts = self.review_summary()
        parts.append(
            _kv(
                self._field_rows(
                    ["reviewer_name", "reviewer_qualifications", "review_date", "validation_method"]
                ),
                s,
            )
        )
        log = self.b["review_log"]
        if not self.b["report"]["include_review_log"]:
            parts.append(_p("The review log was left out of this report by choice.", s["small"]))
            return parts
        if not log:
            parts.append(_p("No events were reviewed in this period.", s["small"]))
            return parts
        rows = [
            [
                "Event",
                "Recording",
                "At (s)",
                "Model label",
                "Score",
                "Status",
                "Reviewer label",
                "Note",
            ]
        ]
        for r in log[:MAX_TABLE_ROWS]:
            rows.append(
                [
                    _p(r["event_id"], s["mono"]),
                    r["recording_filename"][:22],
                    f"{r['start_seconds']:.0f}",
                    r["model_label"],
                    f"{r['max_confidence']:.2f}",
                    r["review_status"],
                    r["reviewer_label"] or "",
                    (r["review_note"] or "")[:160],
                ]
            )
        parts.append(
            _table(
                rows,
                s,
                widths=[w * inch for w in (1.2, 1.1, 0.4, 1.1, 0.45, 0.65, 0.9, 1.2)],
            )
        )
        return parts

    def limitations_block(self) -> list:
        s = self.s
        parts: list = [_p(t, s["body"]) for t in self.b["limitations"]]
        extra = sorted({w for e in self.b["recordings"] for w in (e.get("warnings") or [])})
        if extra:
            parts += [_p("Analysis warnings", s["h2"])] + [_p(w, s["small"]) for w in extra[:40]]
        parts += [
            Spacer(1, 6),
            _kv([("Caveats acknowledged", self._field("caveats_acknowledged"))], s),
        ]
        return parts

    def provenance_block(self) -> list:
        s = self.s
        r = self.b["report"]
        parts: list = [
            _p("Software and schema", s["h2"]),
            _kv(
                [
                    ("Thicket version", r["software_version"]),
                    ("API schema version", r["schema_version"]),
                    ("Platform schema version", r["platform_schema_version"]),
                    ("Bundle SHA-256", _p(self.sha, s["mono"])),
                    ("Generated", r["generated_at"]),
                    ("Audio retention statement", self._field("audio_retention_statement")),
                    ("Data license", self._field("data_license")),
                    ("Privacy statement", self._field("privacy_statement")),
                ],
                s,
            ),
        ]
        if self.b["models"]:
            parts += [_p("Model weights", s["h2"])] + [
                _p(
                    f"{m['model']} {m['version']}: sha256 {m.get('model_sha256') or 'n/a'}",
                    s["mono"],
                )
                for m in self.b["models"]
            ]
        if self.b["manifest"]:
            rows = [["File", "SHA-256", "Bytes", "Seconds", "Analysis id"]]
            for m in self.b["manifest"][:MAX_TABLE_ROWS]:
                rows.append(
                    [
                        m["filename"][:30],
                        _p(m["checksum_sha256"], s["mono"]),
                        m["byte_size"],
                        f"{m['duration_seconds']:.1f}",
                        _p(m["analysis_id"], s["mono"]),
                    ]
                )
            parts += [
                _p("File manifest", s["h2"]),
                _table(
                    rows, s, widths=[1.5 * inch, 2.6 * inch, 0.7 * inch, 0.6 * inch, 1.5 * inch]
                ),
            ]
        elif self.b["recordings"]:
            parts.append(
                _p("The raw file manifest was left out of this report by choice.", s["small"])
            )
        if self.b["recordings"]:
            e = self.b["recordings"][0]
            parts += [
                _p(
                    "Configuration of the first analysis (others identical unless the settings table says otherwise)",
                    s["h2"],
                )
            ]
            for m in e["model_runs"]:
                conf = ", ".join(
                    f"{k}={v}" for k, v in sorted((m.get("configuration") or {}).items())
                )
                parts.append(_p(f"{m['model']}: {conf[:900]}", s["mono"]))
            timings = ", ".join(f"{k} {v} ms" for k, v in sorted(e["stage_timings_ms"].items()))
            parts.append(_p(f"Stage timings: {timings}", s["mono"]))
        return parts

    def dictionary_block(self) -> list:
        s = self.s
        rows = [["Column", "Definition"]] + [
            [c["name"], c["definition"]] for c in self.b["csv_columns"]
        ]
        return [
            _p("CSV data dictionary", s["h2"]),
            _table(rows, s, widths=[1.8 * inch, 5.0 * inch]),
        ]

    def attestation_block(self) -> list:
        s = self.s
        return [
            _p("Attestation", s["h2"]),
            _p(
                "The person named below states that the recordings and settings described here are "
                "accurate to their knowledge. Thicket produced the numbers; it signs nothing.",
                s["body"],
            ),
            _kv(
                [
                    ("Name", self._field("attestation_name")),
                    ("Date", self._field("attestation_date")),
                    ("Signature", ""),
                ],
                s,
            ),
        ]

    # -- template specific blocks ---------------------------------------------
    def field_log_block(self, *, compact: bool = False) -> list:
        s = self.s
        site_fields: dict[str, str] = {}
        for row in self._field("site_field_map") or []:
            if isinstance(row, dict) and row.get("site_name"):
                site_fields[str(row["site_name"]).lower()] = _join(
                    row.get("fsa_field_number"), row.get("paddock_id")
                )
        site_meta = {
            x["name"].lower(): _join(x.get("fsa_field_number"), x.get("paddock_id"))
            for x in self.b["sites"]
        }
        header = [
            "Date",
            "Time",
            "Field / paddock",
            "Site",
            "Minutes",
            "Deployed by",
            "Weather",
            "Activity",
        ]
        rows = [header]
        for e in self.b["recordings"][:MAX_TABLE_ROWS]:
            when = _when(e["captured_at"])
            name = (e["site_name"] or "").lower()
            rows.append(
                [
                    when[:10] if e["captured_at"] else "unknown",
                    when[11:16] if e["captured_at"] else "",
                    site_fields.get(name) or site_meta.get(name) or "not provided",
                    e["site_name"] or "n/a",
                    f"{e['duration_seconds'] / 60:.1f}",
                    self._field("deployed_by") or "not provided",
                    (self._field("weather_summary") or "not provided")[:60],
                    "Acoustic recording analyzed",
                ]
            )
        parts: list = [
            _table(
                rows,
                s,
                widths=[w * inch for w in (0.75, 0.5, 1.0, 1.0, 0.55, 0.9, 1.3, 1.0)],
            )
        ]
        if compact:
            return parts
        actions = self._field("management_action_dates")
        if isinstance(actions, list) and actions:
            arows = [["Action", "Date"]] + [
                [str(a.get("action", "")), str(a.get("date", ""))]
                for a in actions
                if isinstance(a, dict)
            ]
            parts += [
                _p("Management actions", s["h2"]),
                _table(arows, s, widths=[4.5 * inch, 1.5 * inch]),
            ]
        return parts

    def target_species_block(self) -> list:
        s = self.s
        targets = [str(t) for t in (self._field("target_species") or [])]
        if not targets:
            return [
                _p(
                    "No target species were entered on the form. Enter them to get a presence table per date.",
                    s["small"],
                ),
                *self.species_block(),
            ]
        by_name = {sp["common_name"].lower(): sp for sp in self.b["species"]}
        by_sci = {sp["scientific_name"].lower(): sp for sp in self.b["species"]}
        dates = sorted({e["local_date"] for e in self.b["recordings"]})
        detections: dict[str, dict[str, tuple[float, str, str]]] = {}
        for e in self.b["recordings"]:
            for sp in e["species"]:
                key = sp["common_name"].lower()
                best = detections.setdefault(key, {})
                prev = best.get(e["local_date"])
                conf = float(sp["max_confidence"])
                if prev is None or conf > prev[0]:
                    status = (
                        "reviewed"
                        if any(
                            ev["review_status"] != "unreviewed"
                            and ev["scientific_name"] == sp["scientific_name"]
                            for ev in e["events"]
                        )
                        else "unreviewed"
                    )
                    best[e["local_date"]] = (conf, sp["plausibility"], status)
        minutes = self.b["summary"]["minutes_recorded"]
        thr = self.b["report"]["decision_threshold"]
        parts: list = []
        for t in targets:
            sp = by_name.get(t.lower()) or by_sci.get(t.lower())
            rows = [["Date", "Result", "Max score", "Plausibility", "Review"]]
            det = detections.get(sp["common_name"].lower(), {}) if sp else {}
            for d in dates:
                if d in det:
                    conf, pl, st = det[d]
                    rows.append([d, "detected", f"{conf:.2f}", pl, st])
                else:
                    rows.append([d, "not detected in this effort", "", "", ""])
            parts += [
                _p(t, s["h2"]),
                _table(
                    rows, s, widths=[1.1 * inch, 2.2 * inch, 0.9 * inch, 1.0 * inch, 1.0 * inch]
                ),
                _p(
                    f"Not detected means not detected in this effort ({minutes:.0f} minutes"
                    + (
                        f", threshold {thr:g}"
                        if thr is not None
                        else ", each analysis's own threshold"
                    )
                    + "). It is not a statement that the species was away.",
                    s["small"],
                ),
            ]
        return parts

    def effort_table(self) -> list:
        s = self.s
        per_site: dict[str, dict] = {}
        for e in self.b["recordings"]:
            d = per_site.setdefault(
                e["site_name"] or "no site", {"recordings": 0, "minutes": 0.0, "days": set()}
            )
            d["recordings"] += 1
            d["minutes"] += e["duration_seconds"] / 60.0
            d["days"].add(e["local_date"])
        rows = [["Site", "Recordings", "Minutes", "Days with recordings"]] + [
            [name, d["recordings"], f"{d['minutes']:.1f}", len(d["days"])]
            for name, d in sorted(per_site.items())
        ]
        return [
            _p("Effort as implemented", s["h2"]),
            _table(rows, s, widths=[2.5 * inch, 1.1 * inch, 1.1 * inch, 1.5 * inch]),
        ]

    def before_after_block(self, *, intervals: bool = False) -> list:
        s = self.s
        base = self.b.get("baseline")
        cur = self.b["summary"]
        if not base:
            return [
                _p(
                    "No baseline period was chosen for this report, so no before and after comparison is shown. Set baseline_start and baseline_end to add one.",
                    s["small"],
                ),
                Spacer(1, 6),
                _kv(
                    self._field_rows(
                        [
                            "baseline_period_reference",
                            "baseline_analysis_ids",
                            "follow_up_analysis_ids",
                        ]
                    ),
                    s,
                ),
            ]
        bs = base["summary"]
        rows = [
            [
                "",
                f"Baseline {base['period_start']} to {base['period_end']}",
                f"This period {self.b['report']['period_start']} to {self.b['report']['period_end']}",
            ],
            ["Recordings", bs["recordings"], cur["recordings"]],
            ["Minutes", f"{bs['minutes_recorded']:.1f}", f"{cur['minutes_recorded']:.1f}"],
            ["Species counted", bs["species_counted"], cur["species_counted"]],
            ["Detection events", bs["detection_events"], cur["detection_events"]],
            [
                "Events per minute",
                f"{bs['events_per_minute']:.2f}",
                f"{cur['events_per_minute']:.2f}",
            ],
            ["Shannon H'", f"{bs['shannon_index']:.3f}", f"{cur['shannon_index']:.3f}"],
        ]
        parts: list = [
            _p("Before and after, same sites", s["h2"]),
            _table(rows, s, widths=[1.8 * inch, 2.5 * inch, 2.5 * inch]),
        ]
        if intervals:
            cur_r = _bootstrap(
                [int((e["metrics"] or {}).get("species_richness", 0)) for e in self.b["recordings"]]
            )
            cur_e = _bootstrap(
                [
                    float((e["metrics"] or {}).get("events_per_minute", 0.0))
                    for e in self.b["recordings"]
                ]
            )
            irows = [
                ["Per recording", "Baseline mean (95% interval)", "This period mean (95% interval)"]
            ]
            irows.append(["Species richness", _ci(base.get("richness_per_recording")), _ci(cur_r)])
            irows.append(
                ["Events per minute", _ci(base.get("events_per_minute_per_recording")), _ci(cur_e)]
            )
            parts += [
                _p("Uncertainty from resampling across recordings", s["h2"]),
                _table(irows, s, widths=[1.8 * inch, 2.5 * inch, 2.5 * inch]),
            ]
        effort_note = (
            f"Effort differs between the periods ({bs['minutes_recorded']:.0f} vs {cur['minutes_recorded']:.0f} minutes); compare rates, not totals."
            if abs(bs["minutes_recorded"] - cur["minutes_recorded"])
            > 0.2 * max(bs["minutes_recorded"], cur["minutes_recorded"], 1)
            else "Effort is similar between the periods."
        )
        parts.append(
            _p(
                effort_note
                + " Change is reported for the same sites and season; it is not attributed to any practice or cause.",
                s["small"],
            )
        )
        return parts

    def credit_results_block(self) -> list:
        s = self.s
        per_site: dict[str, dict] = {}
        for e in self.b["recordings"]:
            d = per_site.setdefault(
                e["site_name"] or "no site",
                {"minutes": 0.0, "species": {}, "events": 0, "recordings": 0},
            )
            d["minutes"] += e["duration_seconds"] / 60.0
            d["recordings"] += 1
            for sp in e["species"]:
                d["species"][sp["scientific_name"]] = (
                    d["species"].get(sp["scientific_name"], 0) + sp["detection_event_count"]
                )
                d["events"] += sp["detection_event_count"]
        rows = [
            [
                "Site",
                "Recordings",
                "Minutes",
                "Richness (Hill q=0)",
                "Shannon H'",
                "Hill q=1 exp(H')",
                "Pielou J'",
                "Gini-Simpson",
                "Events/min",
            ]
        ]
        for name, d in sorted(per_site.items()):
            counts = list(d["species"].values())
            n = sum(counts)
            h = -sum((c / n) * math.log(c / n) for c in counts if c > 0) if n else 0.0
            S = len(counts)
            rows.append(
                [
                    name,
                    d["recordings"],
                    f"{d['minutes']:.1f}",
                    S,
                    f"{h:.3f}",
                    f"{math.exp(h):.2f}" if n else "0.00",
                    f"{(h / math.log(S)) if S > 1 else 0.0:.3f}",
                    f"{(1 - sum((c / n) ** 2 for c in counts)) if n else 0.0:.3f}",
                    f"{(d['events'] / d['minutes']) if d['minutes'] else 0.0:.2f}",
                ]
            )
        return [
            _p("Indicator values per site, this period", s["h2"]),
            _table(
                rows,
                s,
                widths=[
                    1.2 * inch,
                    0.7 * inch,
                    0.6 * inch,
                    0.9 * inch,
                    0.7 * inch,
                    0.8 * inch,
                    0.6 * inch,
                    0.8 * inch,
                    0.6 * inch,
                ],
            ),
            _p(
                "Indicator values for the monitoring period, with intervals on the next page. No issuance arithmetic is performed here.",
                s["small"],
            ),
        ]


# ------------------------------------------------------------- helpers


def _review_text(sp: dict) -> str:
    n = int(sp.get("reviewed_events") or 0)
    if n == 0:
        return "none"
    other = n - int(sp["accepted_events"]) - int(sp["rejected_events"])
    parts = [f"{sp['accepted_events']} accepted", f"{sp['rejected_events']} rejected"]
    if other:
        parts.append(f"{other} corrected")
    return ", ".join(parts)


def _join(*parts: object) -> str:
    vals = [str(p) for p in parts if p not in (None, "")]
    return ", ".join(vals) if vals else "not provided"


def _id_list(ids: Sequence[str]) -> str:
    if not ids:
        return "none"
    if len(ids) <= 6:
        return ", ".join(ids)
    return ", ".join(ids[:6]) + f" and {len(ids) - 6} more (full list in the manifest)"


def _quality_text(counts: dict) -> str:
    return ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(counts.items())) or "n/a"


def _bootstrap(values: Sequence[float]) -> dict | None:
    from thicket.reports.bundle import _bootstrap_ci

    return _bootstrap_ci(values)


def _ci(stat: dict | None) -> str:
    if not stat:
        return "too few recordings"
    lo, hi = stat["ci95"]
    return f"{stat['mean']:.2f} ({lo:.2f} to {hi:.2f}), n = {stat['n']}"
