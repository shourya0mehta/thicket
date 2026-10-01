"""Write shared/api.schema.json from the canonical Pydantic models.

The frontend generates its TypeScript types from this file
(`npm run gen:types`), and a backend test fails if it is stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic.json_schema import models_json_schema

from thicket.api import platform_schemas as ps
from thicket.api import schemas as s

MODELS = [
    s.Analysis,
    s.AnalysisExport,
    s.AnalysisList,
    s.ModelsResponse,
    s.HealthResponse,
    s.ErrorResponse,
    s.EventReviewUpdate,
    s.Preview,
    # platform
    ps.AuthConfig,
    ps.Me,
    ps.DevLogin,
    ps.Organization,
    ps.OrganizationCreate,
    ps.OrganizationUpdate,
    ps.Membership,
    ps.MembershipUpdate,
    ps.Invite,
    ps.InviteCreate,
    ps.Site,
    ps.SiteCreate,
    ps.SiteUpdate,
    ps.Recorder,
    ps.RecorderCreate,
    ps.RecorderUpdate,
    ps.Deployment,
    ps.DeploymentCreate,
    ps.DeploymentUpdate,
    ps.RecordingSummary,
    ps.RecordingPage,
    ps.BatchJob,
    ps.Dashboard,
    ps.Phenology,
    ps.Accumulation,
    ps.SiteComparison,
    ps.Alert,
    ps.AlertPage,
    ps.AlertUpdate,
    ps.AlertRules,
    ps.NotificationPrefs,
    ps.NotificationPage,
    ps.RecorderHealth,
    ps.ReportTemplates,
    ps.ReportCreate,
    ps.Report,
    ps.ReportList,
    ps.UploadedFile,
]

OUT = Path(__file__).resolve().parents[2] / "shared" / "api.schema.json"


def build() -> str:
    _, top = models_json_schema([(m, "serialization") for m in MODELS], title="ThicketAPI")
    top["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    top["x-schema-version"] = s.SCHEMA_VERSION
    top["x-platform-schema-version"] = ps.PLATFORM_SCHEMA_VERSION
    return json.dumps(top, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    text = build()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print("shared/api.schema.json is stale; run python backend/scripts/export_schema.py")
            sys.exit(1)
        print("schema up to date")
    else:
        OUT.write_text(text)
        print(f"wrote {OUT}")
