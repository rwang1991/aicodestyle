import time

from fastapi.testclient import TestClient

from aianalyzer.web.app import create_app


def test_scan_then_profile_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("AIANALYZER_CACHE_DIR", str(tmp_path))
    from aianalyzer.web import services
    monkeypatch.setattr(services, "discover_all_sessions", lambda: [])

    client = TestClient(create_app())

    r = client.post("/api/scan", json={})
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    deadline = time.time() + 5
    j = None
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert j is not None and j["status"] == "done", j
    assert j["result"]["discovered"] == 0

    p = client.get("/api/profile").json()
    assert p["totals"]["sessions"] == 0
    assert "primary_archetype" in p
    assert "session_type_counts" in p
    assert "axes" in p
    assert "planning" in p["axes"]
    assert "control" in p["axes"]


def test_jobs_returns_404_for_unknown_id():
    client = TestClient(create_app())
    r = client.get("/api/jobs/nope")
    assert r.status_code == 404


def test_scan_job_reports_failure_on_discovery_error(tmp_path, monkeypatch):
    monkeypatch.setenv("AIANALYZER_CACHE_DIR", str(tmp_path))
    from aianalyzer.web import services

    def boom():
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(services, "discover_all_sessions", boom)
    client = TestClient(create_app())
    r = client.post("/api/scan", json={})
    job_id = r.json()["job_id"]

    deadline = time.time() + 5
    j = None
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert j is not None and j["status"] == "failed", j
    assert "disk on fire" in j["error"]
