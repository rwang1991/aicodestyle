from fastapi.testclient import TestClient

from aianalyzer.web.app import create_app


def test_app_serves_health():
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_app_serves_static_chart_js():
    client = TestClient(create_app())
    r = client.get("/static/chart.umd.js")
    assert r.status_code == 200
    assert "Chart" in r.text
