import subprocess
import sys
from pathlib import Path

import pytest

from thicket.api.schemas import HealthResponse, ModelsResponse

BACKEND = Path(__file__).resolve().parents[2]


@pytest.mark.birdnet
def test_health_ok_when_birdnet_ready(client):
    client.app.state.container.registry.require_ready("birdnet", timeout=60)
    h = HealthResponse.model_validate(client.get("/api/v1/health").json())
    assert h.status == "ok"
    assert h.models == {"birdnet": "ready", "frog_insect": "disabled"}
    assert h.ffmpeg is True and h.environment == "test" and h.version


def test_health_degraded_without_birdnet(make_client):
    client = make_client(birdnet_enabled=False)
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert client.head("/api/v1/health").status_code == 200
    h = HealthResponse.model_validate(r.json())
    assert h.status == "degraded" and h.models["birdnet"] == "disabled"


def test_models_shape(client):
    m = ModelsResponse.model_validate(client.get("/api/v1/models").json())
    by_key = {x.key: x for x in m.models}
    assert set(by_key) == {"birdnet", "frog_insect"}
    b = by_key["birdnet"]
    assert (b.name, b.version, b.license, b.experimental) == (
        "BirdNET",
        "2.4",
        "CC BY-NC-SA 4.0",
        False,
    )
    assert b.taxa == ["bird", "amphibian", "insect", "mammal"]
    f = by_key["frog_insect"]
    assert f.experimental and f.status == "disabled" and f.unavailable_reason
    assert f.model_card_url == "docs/model-cards/frog-insect.md"


def test_openapi_available(client):
    spec = client.get("/api/openapi.json").json()
    assert "/api/v1/analyses" in spec["paths"]
    assert (
        "multipart/form-data" in spec["paths"]["/api/v1/analyses"]["post"]["requestBody"]["content"]
    )


def test_root_without_frontend(client):
    assert client.get("/").json()["api"] == "/api/v1"


def test_serves_frontend_with_spa_fallback(make_client, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Thicket</title>")
    (dist / "assets" / "app.123.js").write_text("console.log(1)")
    client = make_client(serve_frontend_dir=dist)
    assert "Thicket" in client.get("/").text
    assert "Thicket" in client.get("/history/ana_x").text  # SPA route
    js = client.get("/assets/app.123.js")
    assert js.text == "console.log(1)" and "immutable" in js.headers["cache-control"]
    assert client.get("/../../etc/passwd").status_code in (200, 404)
    assert "root:" not in client.get("/..%2F..%2Fetc%2Fpasswd").text
    api = client.get("/api/v1/nope")
    assert api.status_code == 404 and api.json()["error_code"] == "not_found"
    assert client.get("/api/v1/health").status_code == 200


def test_schema_export_is_current():
    r = subprocess.run(
        [sys.executable, "scripts/export_schema.py", "--check"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_app_module_is_lazy():
    code = (
        "import thicket.main as m, sys; "
        "assert '_app' in vars(m) and m._app is None; "
        "print(type(m.app).__name__)"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", "THICKET_DATA_DIR": str(BACKEND / "var" / "lazy-test")},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "FastAPI"
