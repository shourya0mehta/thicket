"""Report field schema, bundle, PDF rendering for all five templates, the
forbidden-wording check and the report API."""

import hashlib
import io
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader
from tests.platform_helpers import CSRF, create_org, dev_login, insert_analysis

from thicket.api.platform_schemas import PLATFORM_SCHEMA_VERSION, ReportTemplateKey
from thicket.api.schemas import EventReviewUpdate, ReviewStatus
from thicket.ids import LOCAL_ORG_ID, LOCAL_USER_ID
from thicket.reports import field_schema
from thicket.reports.bundle import build_bundle, dumps, sha256_text

DOCS = Path(__file__).resolve().parents[3] / "docs" / "REPORTING.md"
A, B, P = "Turdus migratorius", "Dolichonyx oryzivorus", "Pseudacris crucifer"
MAY, APRIL = (date(2026, 5, 1), date(2026, 5, 31)), (date(2026, 4, 1), date(2026, 4, 30))


# ------------------------------------------------------------------ schema


def doc_fields() -> list[dict]:
    text = DOCS.read_text()
    block = re.search(r"## 7\. `report_field_schema`.*?```json\n(.*?)\n```", text, re.S).group(1)
    return json.loads(block)["report_field_schema"]["fields"]


def forbidden_phrases() -> list[str]:
    """Section 8's "Never write" column plus the renderer's own list."""
    section = DOCS.read_text().split("## 8. Claims Thicket must not make", 1)[1]
    phrases = set(field_schema.forbidden_wording())
    for line in section.splitlines():
        if not line.startswith("| ") or line.startswith("| Never") or line.startswith("|---"):
            continue
        first = line.split("|")[1]
        for quoted in re.findall(r'"([^"]+)"', first):
            q = quoted.lower().replace("species x ", "").replace("x individuals", "individuals")
            q = q.replace(" / mbta / clean water act", "").replace("esa", "").strip()
            q = re.sub(r"\s+", " ", q).strip(" /")
            if q:
                phrases.add(q)
    return sorted(phrases)


def test_schema_mirrors_reporting_md_section_7():
    ours = {f.name: f for f in field_schema.all_fields()}
    theirs = doc_fields()
    assert len(ours) == len(theirs) == 120
    letters = {"a": "evidence", "b": "nrcs", "c": "aem", "d": "certification", "e": "credit"}
    for f in theirs:
        mine = ours[f["name"]]
        assert mine.type == f["type"] and mine.group == f["group"]
        assert [t.value for t in mine.templates] == [letters[x] for x in f["templates"]]
        assert mine.options == f.get("options") and mine.example == f.get("example")
        assert mine.label and mine.help and "\u2014" not in mine.help


def test_templates_and_pages():
    tpls = {t.key: t for t in field_schema.templates().templates}
    assert set(tpls) == set(ReportTemplateKey)
    assert [len(tpls[k].pages) for k in ReportTemplateKey] == [11, 6, 6, 6, 10]
    assert all(t.fields for t in tpls.values())
    assert "nrcs_contract_number" in {f.name for f in tpls[ReportTemplateKey.nrcs].fields}
    assert "nrcs_contract_number" not in {f.name for f in tpls[ReportTemplateKey.evidence].fields}


def test_missing_and_unknown_fields():
    missing = field_schema.missing_fields(
        ReportTemplateKey.nrcs, {"participant_name": "Jane", "county": " "}
    )
    assert "participant_name" not in missing and "county" in missing
    required = [f.name for f in field_schema.fields_for(ReportTemplateKey.nrcs) if f.required]
    assert missing[: len(required) - 1] == [r for r in required if r != "participant_name"]
    assert field_schema.unknown_fields(
        ReportTemplateKey.evidence, {"aem_id": "x", "report_title": "t"}
    ) == ["aem_id"]


# ------------------------------------------------------------------- data


@pytest.fixture
def farm(container):
    c = container
    site = c.platform.create_site(
        LOCAL_ORG_ID,
        {
            "name": "North pasture",
            "latitude": 42.44,
            "longitude": -76.5,
            "habitat_type": "pasture",
            "fsa_field_number": "4",
        },
    )
    rec = c.platform.create_recorder(
        LOCAL_ORG_ID, {"label": "AM-1", "make": "audiomoth", "serial": "24A1"}
    )
    c.platform.create_deployment(
        LOCAL_ORG_ID,
        {
            "recorder_id": rec.id,
            "site_id": site.id,
            "started_at": datetime(2026, 4, 1, tzinfo=UTC),
            "mount_height_m": 1.5,
        },
    )
    aids = []
    for i in range(4):
        aid, _ = insert_analysis(
            c,
            site_id=site.id,
            recorder_id=rec.id,
            captured_at=datetime(2026, 5, 10 + i, 10, tzinfo=UTC),
            species={A: 2, B: 1, P: 1},
            filename=f"20260510_{i}.WAV",
        )
        aids.append(aid)
        insert_analysis(
            c,
            site_id=site.id,
            captured_at=datetime(2026, 4, 10 + i, 10, tzinfo=UTC),
            species={A: 1},
        )
    events = c.analysis.view(aids[0]).events
    bobolink = next(e for e in events if e.scientific_name == B)
    c.analysis.review(
        bobolink.id,
        EventReviewUpdate(review_status=ReviewStatus.rejected, review_note="meadowlark song"),
        None,
        reviewed_by=LOCAL_USER_ID,
    )
    return c, site, aids


def report_row(c, template, *, period=MAY, baseline=APRIL, fields=None, **kw):
    key = ReportTemplateKey(template)
    if fields is None:
        fields = {f.name: f.example for f in field_schema.fields_for(key) if f.type != "file"}
    return c.platform.create_report(
        {
            "organization_id": LOCAL_ORG_ID,
            "template": key.value,
            "title": "Spring 2026 acoustic survey",
            "status": "queued",
            "created_by": LOCAL_USER_ID,
            "period_start": period[0],
            "period_end": period[1],
            "baseline_start": baseline[0] if baseline else None,
            "baseline_end": baseline[1] if baseline else None,
            "site_ids": kw.pop("site_ids", []),
            "decision_threshold": kw.pop("decision_threshold", None),
            "fields": c.reports._clean_fields(key, fields),
            "missing_fields": [],
            **kw,
        }
    )


def pdf_pages(c, row) -> list[str]:
    path = c.storage.resolve_uri(row.pdf_uri)
    return [p.extract_text() for p in PdfReader(str(path)).pages]


def normalized(pages: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(pages)).lower()


# ------------------------------------------------------------------ bundle


def test_bundle_numbers_and_review_log(farm):
    c, site, aids = farm
    row = report_row(c, "evidence")
    org = c.platform.get_org(LOCAL_ORG_ID)
    b = build_bundle(c.repo, c.platform, row, org, generated_at=datetime(2026, 6, 1, tzinfo=UTC))
    assert b["summary"]["recordings"] == 4 and b["summary"]["minutes_recorded"] == 4.0
    # 4 recordings x (A2 B1 P1) with one Bobolink event rejected: A8 B3 P4.
    sp = {s["scientific_name"]: s for s in b["species"]}
    assert (sp[A]["detection_events"], sp[B]["detection_events"], sp[P]["detection_events"]) == (
        8,
        3,
        4,
    )
    assert sp[B]["rejected_events"] == 1 and sp[B]["reviewed_events"] == 1
    assert b["summary"]["detection_events"] == 15 and b["summary"]["species_counted"] == 3
    (log,) = b["review_log"]
    assert log["review_status"] == "rejected" and log["review_note"] == "meadowlark song"
    assert log["model_label"] == "Bobolink" and not log["counted_in_metrics"]
    assert b["reviewers"] == ["Local user"]
    assert (
        b["baseline"]["summary"]["recordings"] == 4
        and b["baseline"]["summary"]["species_counted"] == 1
    )
    assert b["baseline"]["richness_per_recording"]["mean"] == 1.0
    assert len(b["manifest"]) == 4 and b["manifest"][0]["checksum_sha256"] == "0" * 64
    assert b["deployments"][0]["mount_height_m"] == 1.5 and b["recorders"][0]["serial"] == "24A1"
    assert b["report"]["platform_schema_version"] == PLATFORM_SCHEMA_VERSION
    assert [col["name"] for col in b["csv_columns"]][:3] == [
        "analysis_id",
        "recording_filename",
        "site_name",
    ]
    assert "deployment_photo" in b["missing_fields"]


def test_bundle_is_deterministic_and_threshold_aware(farm):
    c, *_ = farm
    org = c.platform.get_org(LOCAL_ORG_ID)
    row = report_row(c, "evidence")
    when = datetime(2026, 6, 1, tzinfo=UTC)
    one = dumps(build_bundle(c.repo, c.platform, row, org, generated_at=when))
    two = dumps(build_bundle(c.repo, c.platform, row, org, generated_at=when))
    assert one == two and sha256_text(one) == sha256_text(two)
    strict = report_row(c, "evidence", decision_threshold=0.95)
    b = build_bundle(c.repo, c.platform, strict, org, generated_at=when)
    assert b["summary"]["detection_events"] == 0  # every window scored 0.9
    assert all(e["decision_threshold"] == 0.95 for e in b["recordings"])


def test_site_filter_and_toggles(farm):
    c, site, _ = farm
    other = c.platform.create_site(LOCAL_ORG_ID, {"name": "Other"})
    insert_analysis(
        c, site_id=other.id, captured_at=datetime(2026, 5, 20, tzinfo=UTC), species={A: 9}
    )
    org = c.platform.get_org(LOCAL_ORG_ID)
    row = report_row(
        c, "evidence", site_ids=[site.id], include_review_log=False, include_raw_manifest=False
    )
    b = build_bundle(c.repo, c.platform, row, org)
    assert b["summary"]["recordings"] == 4 and [s["id"] for s in b["sites"]] == [site.id]
    assert b["review_log"] == [] and b["manifest"] == []


# --------------------------------------------------------------- rendering


@pytest.mark.parametrize("template", [t.value for t in ReportTemplateKey])
def test_every_template_renders_with_footer_and_no_forbidden_wording(farm, template):
    c, *_ = farm
    row = c.reports.render(report_row(c, template).id)
    assert row.status == "ready", row.error_message
    assert row.page_count >= 5 and row.analysis_count == 4
    pages = pdf_pages(c, row)
    assert len(pages) == row.page_count
    for text in pages:
        flat = re.sub(r"\s+", " ", text)
        assert f"Report {row.id}" in flat
        assert f"platform schema {PLATFORM_SCHEMA_VERSION}" in flat and "Thicket " in flat
        assert f"bundle sha256 {row.bundle_sha256}" in flat
    text = normalized(pages)
    hits = [
        ph
        for ph in forbidden_phrases()
        if re.search(r"(?<![a-z])" + re.escape(ph) + r"(?![a-z])", text)
    ]
    assert hits == [], hits
    assert "\u2014" not in text
    tpl = field_schema.template(ReportTemplateKey(template))
    for page in tpl.pages:
        if page not in ("Cover", "Header"):
            assert page.lower() in text, page
    pdf_bytes = c.storage.resolve_uri(row.pdf_uri).read_bytes()
    assert hashlib.sha256(pdf_bytes).hexdigest() == row.checksum_sha256
    bundle_text = c.storage.resolve_uri(row.bundle_uri).read_text()
    assert sha256_text(bundle_text) == row.bundle_sha256


def test_forbidden_list_is_meaningful():
    phrases = forbidden_phrases()
    for expected in (
        "individuals",
        "absent",
        "wheg score",
        "cart points",
        "verified",
        "quality hectares",
        "biodiversity score",
    ):
        assert expected in phrases


def test_nrcs_target_species_not_detected_wording(farm):
    c, *_ = farm
    fields = {
        f.name: f.example
        for f in field_schema.fields_for(ReportTemplateKey.nrcs)
        if f.type != "file"
    }
    fields["target_species"] = ["Bobolink", "Eastern Meadowlark"]
    row = c.reports.render(report_row(c, "nrcs", fields=fields).id)
    text = normalized(pdf_pages(c, row))
    assert "not detected in this effort" in text and "eastern meadowlark" in text
    assert "supporting documentation prepared by the participant" in text


def test_empty_period_renders_a_clear_page(farm):
    c, *_ = farm
    row = c.reports.render(
        report_row(c, "credit", period=(date(2025, 1, 1), date(2025, 1, 31)), baseline=None).id
    )
    assert row.status == "ready" and row.analysis_count == 0
    text = normalized(pdf_pages(c, row))
    assert "no recordings in this period" in text
    assert "no completed recordings fall in this period" in " ".join(row.warnings).lower()


def test_missing_fields_and_blank_values(farm):
    c, *_ = farm
    row = c.reports.render(report_row(c, "aem", fields={"aem_id": "T-0456"}).id)
    assert "farm_name" in row.missing_fields and "aem_id" not in row.missing_fields
    assert row.missing_fields[0] == "report_title"  # required fields first
    assert "not provided" in normalized(pdf_pages(c, row))


def test_logo_and_images(farm, tmp_path):
    c, *_ = farm
    logo = tmp_path / "logo.png"
    Image.new("RGB", (120, 60), (55, 113, 87)).save(logo)
    c.reports.settings = c.reports.settings.model_copy(update={"report_logo_path": logo})
    photo = c.storage.files / "photo.png"
    Image.new("RGB", (80, 60), (200, 220, 200)).save(photo)
    f = c.platform.create_file(
        {
            "organization_id": LOCAL_ORG_ID,
            "filename": "photo.png",
            "content_type": "image/png",
            "byte_size": photo.stat().st_size,
            "checksum_sha256": "0" * 64,
            "storage_uri": c.storage.storage_uri(photo),
        }
    )
    fields = {"deployment_photo": f.id, "tract_map_image": "file_" + "b" * 24}
    row = c.reports.render(report_row(c, "nrcs", fields=fields).id)
    assert row.status == "ready"
    assert row.warnings == ["FSA tract map could not be found; it was left out."]
    assert "deployment photo" in normalized(pdf_pages(c, row))


# --------------------------------------------------------------------- API


def wait_ready(client, rid):
    import time

    for _ in range(300):
        r = client.get(f"/api/v1/reports/{rid}").json()
        if r["status"] in ("ready", "failed"):
            return r
        time.sleep(0.05)
    raise AssertionError(r)


def test_report_api_lifecycle(make_platform_client):
    client = make_platform_client()
    c = client.app.state.container
    site = c.platform.create_site(LOCAL_ORG_ID, {"name": "API"})
    insert_analysis(
        c, site_id=site.id, captured_at=datetime(2026, 5, 14, tzinfo=UTC), species={A: 2}
    )
    t = client.get("/api/v1/reports/templates").json()
    assert [x["key"] for x in t["templates"]] == [
        "evidence",
        "nrcs",
        "aem",
        "certification",
        "credit",
    ]
    body = {
        "template": "evidence",
        "title": "API report",
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
        "fields": {"report_title": "API report", "preparer_name": "Jane"},
    }
    r = client.post(f"/api/v1/orgs/{LOCAL_ORG_ID}/reports", json=body)
    assert r.status_code == 202 and r.json()["status"] in ("queued", "rendering", "ready")
    assert r.headers["location"] == f"/api/v1/reports/{r.json()['id']}"
    rep = wait_ready(client, r.json()["id"])
    assert rep["status"] == "ready" and rep["analysis_count"] == 1 and rep["page_count"] >= 5
    assert rep["pdf_url"] == f"/api/v1/reports/{rep['id']}.pdf"
    pdf = client.get(rep["pdf_url"])
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert hashlib.sha256(pdf.content).hexdigest() == rep["checksum_sha256"]
    bundle = client.get(rep["json_url"])
    assert bundle.json()["report"]["id"] == rep["id"]
    footer_sha = hashlib.sha256(bundle.content).hexdigest()
    assert f"bundle sha256 {footer_sha}" in re.sub(
        r"\s+", " ", PdfReader(io.BytesIO(pdf.content)).pages[0].extract_text()
    )
    listed = client.get(f"/api/v1/orgs/{LOCAL_ORG_ID}/reports").json()["items"]
    assert [x["id"] for x in listed] == [rep["id"]]
    assert client.delete(f"/api/v1/reports/{rep['id']}").status_code == 204
    assert client.get(f"/api/v1/reports/{rep['id']}").status_code == 404
    assert list(c.storage.reports.iterdir()) == []


@pytest.mark.parametrize(
    "patch",
    [
        {"fields": {"no_such_field": "x"}},
        {"fields": {"data_license": "MIT"}},
        {"fields": {"deployment_photo": "photo.jpg"}},
        {"fields": {"mount_height_m": "tall"}},
        {"period_start": "2026-06-01"},
        {"baseline_start": "2026-04-01"},
        {"decision_threshold": 0.01},
        {"template": "glossy"},
        {"title": ""},
    ],
)
def test_report_validation(make_platform_client, patch):
    client = make_platform_client()
    body = {
        "template": "evidence",
        "title": "x",
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
    }
    body.update(patch)
    r = client.post(f"/api/v1/orgs/{LOCAL_ORG_ID}/reports", json=body)
    assert r.status_code == 422, r.text


def test_report_roles(make_platform_client):
    client = make_platform_client(auth_mode="dev")
    dev_login(client, "owner@example.org")
    org = create_org(client)
    token = (
        client.post(
            f"/api/v1/orgs/{org['id']}/invites",
            json={"email": "v@example.org", "role": "viewer"},
            headers=CSRF,
        )
        .json()["accept_url"]
        .rsplit("/", 1)[-1]
    )
    dev_login(client, "v@example.org")
    client.post(f"/api/v1/invites/{token}/accept", headers=CSRF)
    body = {
        "template": "evidence",
        "title": "x",
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
    }
    assert (
        client.post(f"/api/v1/orgs/{org['id']}/reports", json=body, headers=CSRF).status_code == 403
    )
    assert client.get(f"/api/v1/orgs/{org['id']}/reports").status_code == 200
    assert client.get("/api/v1/reports/templates").status_code == 200
    client.post("/api/v1/auth/logout", headers=CSRF)
    assert client.get("/api/v1/reports/templates").status_code == 401


def test_uploaded_image_api(make_platform_client):
    client = make_platform_client()
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="JPEG")
    r = client.post(
        f"/api/v1/orgs/{LOCAL_ORG_ID}/files",
        files={"file": ("p.jpg", buf.getvalue(), "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["content_type"] == "image/jpeg" and body["url"] == f"/api/v1/files/{body['id']}"
    got = client.get(body["url"])
    assert got.status_code == 200 and got.content == buf.getvalue()
    bad = client.post(
        f"/api/v1/orgs/{LOCAL_ORG_ID}/files",
        files={"file": ("x.png", b"not an image", "image/png")},
    )
    assert bad.status_code == 415
    two = client.post(
        f"/api/v1/orgs/{LOCAL_ORG_ID}/files",
        files=[
            ("file", ("a.jpg", buf.getvalue(), "image/jpeg")),
            ("file", ("b.jpg", buf.getvalue(), "image/jpeg")),
        ],
    )
    assert two.status_code == 422
    big = client.post(
        f"/api/v1/orgs/{LOCAL_ORG_ID}/files",
        files={"file": ("big.png", b"\x89PNG\r\n\x1a\n" + b"0" * (11 * 1024 * 1024), "image/png")},
    )
    assert big.status_code == 413
