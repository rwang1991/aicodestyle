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
    # Empty cache -> by_client is an empty dict (no fake clients).
    assert p["by_client"] == {}

    # Behavior radar payload: six independent trait dimensions, each with a
    # normalized score in [0, 1] and a human-readable help string. With an
    # empty cache every signal is 0 -> every score is 0.
    radar = p["behavior_radar"]
    assert len(radar) == 6
    expected_labels = {"Planner", "Questioner", "TODO-driver", "Hands-on", "Deliberator", "Multi-tasker"}
    assert {row["label"] for row in radar} == expected_labels
    for row in radar:
        assert 0.0 <= row["score"] <= 1.0
        assert row["help"]  # non-empty explanation
        assert "ceiling" in row and row["ceiling"] > 0
        assert "raw" in row


def test_behavior_radar_normalizes_against_ceiling(tmp_path, monkeypatch):
    """A raw signal at or above its ceiling reads score=1.0; halfway reads
    0.5. This is what makes the radar shape interpretable as 'percentage of
    classifier-max'."""
    from aianalyzer.web import services
    from aianalyzer.features import UserProfile

    profile = UserProfile(
        session_count=10,
        total_turns=100,
        # Force each radar input to its ceiling so we can predict the output.
        planning_language_ratio=0.6,   # ceiling 0.6
        question_ratio=0.3,            # ceiling 0.6 -> 0.5
        total_todos=20,                # 20/10 = 2.0 == ceiling
        prompt_specificity_avg=0.5,    # ceiling 0.5 (Hands-on spoke)
        thinks_before_prompt_sec_avg=120.0,  # ceiling 60 -> clamps to 1.0
        parallel_tool_call_rate=0.25,  # ceiling 1.0
    )
    radar = services._build_behavior_radar(profile)
    by_label = {row["label"]: row for row in radar}
    assert by_label["Planner"]["score"] == 1.0
    assert by_label["Questioner"]["score"] == 0.5
    assert by_label["TODO-driver"]["score"] == 1.0
    assert by_label["Hands-on"]["score"] == 1.0
    assert by_label["Deliberator"]["score"] == 1.0      # clamped
    assert by_label["Multi-tasker"]["score"] == 0.25


def test_jobs_returns_404_for_unknown_id():
    client = TestClient(create_app())
    r = client.get("/api/jobs/nope")
    assert r.status_code == 404


def test_profile_includes_behavior_block_with_modifiers(tmp_path, monkeypatch):
    """The behavior block exposes the raw signals used by the classifier and
    a modifier-by-modifier breakdown so the user can see *why* each tag did or
    didn't apply. Empty cache => zeroed signals + every modifier missed."""
    monkeypatch.setenv("AIANALYZER_CACHE_DIR", str(tmp_path))
    from aianalyzer.web import services
    monkeypatch.setattr(services, "discover_all_sessions", lambda: [])
    client = TestClient(create_app())
    p = client.get("/api/profile").json()

    b = p["behavior"]
    plan_names = {row["name"] for row in b["planning"]}
    assert {"planning_language_ratio", "question_ratio", "todo_density"} <= plan_names
    ctrl_names = {row["name"] for row in b["control"]}
    assert {"prompt_specificity_avg", "accept_and_go_ratio", "ai_agency_rate"} <= ctrl_names

    # Every planning/control row carries its normalizer ceiling so the bar can
    # render value/norm_max correctly.
    for row in b["planning"] + b["control"]:
        assert "norm_max" in row and row["norm_max"] > 0

    mods = b["modifiers"]
    tags = {m["tag"] for m in mods}
    assert tags == {"questioner", "debugger", "planner", "yolo", "parallelist"}
    for m in mods:
        assert "threshold" in m and m["threshold"] > 0
        # With an empty cache every signal is 0 -> every modifier misses.
        assert m["met"] is False

    assert isinstance(b["reasoning_effort_distribution"], dict)


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


def test_scan_result_exposes_supported_clients_and_breakdown(tmp_path, monkeypatch):
    """The empty-state UI relies on supported_clients + by_client in the scan
    job result so it can tell users which clients we looked at and which ones
    found data."""
    monkeypatch.setenv("AIANALYZER_CACHE_DIR", str(tmp_path))
    from aianalyzer.web import services

    monkeypatch.setattr(services, "discover_all_sessions", lambda: [])
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
    assert j and j["status"] == "done"
    result = j["result"]
    assert result["discovered"] == 0
    assert result["by_client"] == {}
    assert "copilot-cli" in result["supported_clients"]
    assert "vscode-copilot" in result["supported_clients"]


def _stub_profile(monkeypatch):
    from aianalyzer.web import services

    monkeypatch.setattr(services, "load_profile_payload", lambda: {
        "primary_archetype": "architect",
        "secondary_archetype": None,
        "macro_label": "Architect",
        "tags": [],
        "confidence": 0.5,
        "axes": {"planning": 0.3, "control": 0.4},
        "totals": {"sessions": 1, "turns": 1, "hours": 0.1, "days_active": 1, "longest_streak_days": 1},
        "averages": {},
        "top_tools": [], "top_projects": [], "top_models": [],
        "top_file_extensions": [], "session_type_counts": {},
        "hour_histogram": [0] * 24, "weekday_histogram": [0] * 7,
        "activity_per_day_last_90": [],
        "first_session_at": None, "last_session_at": None,
    })


def test_narrative_start_returns_job_and_completes(monkeypatch):
    _stub_profile(monkeypatch)
    from aianalyzer import narrative as nar
    monkeypatch.setattr(nar, "generate_narrative", lambda facts, **_: "# Your AI Profile\n\nfake")

    client = TestClient(create_app())
    r = client.post("/api/narrative/start")
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
    assert j["result"]["markdown"].startswith("# Your AI Profile")


def test_narrative_job_reports_failure(monkeypatch):
    _stub_profile(monkeypatch)
    from aianalyzer import narrative as nar

    def boom(*_a, **_kw):
        raise nar.NarrativeError("copilot exited 2")

    monkeypatch.setattr(nar, "generate_narrative", boom)

    client = TestClient(create_app())
    r = client.post("/api/narrative/start")
    job_id = r.json()["job_id"]

    deadline = time.time() + 5
    j = None
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert j is not None and j["status"] == "failed", j
    assert "copilot exited" in j["error"]
