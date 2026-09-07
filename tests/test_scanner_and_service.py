import io
import json
import zipfile
from pathlib import Path

import pytest

from vgselect3a import recommend
from vgselect3a.profile import WorkloadProfile
from vgselect3a.scanner import merge_profile, scan_repository

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_repo"


def test_scan_detects_frameworks_tools_sources_and_side_effects():
    scan = scan_repository(FIXTURE)
    assert "anthropic-sdk" in scan.frameworks
    assert {"lookup_order", "search_kb", "search_docs", "search_tickets", "issue_refund"} <= set(scan.tools)
    assert "pinecone" in scan.knowledge_sources
    assert any(s.startswith("payments") for s in scan.side_effects)
    assert scan.current_topology == "single_agent"
    inferred = scan.inferred_profile()
    assert inferred["tool_count"] == 5
    assert inferred["tool_side_effects"] == "irreversible"
    assert inferred["tool_overlap"] is True  # search_kb / search_docs / search_tickets
    assert inferred["latency_budget_s"] <= 10  # FastAPI endpoint
    assert scan.evidence and all(e.path and e.line >= 1 for e in scan.evidence)


def test_merge_profile_overrides_and_recommend_with_scan():
    scan = scan_repository(FIXTURE)
    data = merge_profile(scan, {"accuracy_priority": 5, "latency_budget_s": 8})
    assert data["accuracy_priority"] == 5 and data["tools"]
    rec = recommend(WorkloadProfile.from_dict(data), scan=scan)
    md = rec.to_markdown()
    assert "## Repository scan" in md
    assert rec.primary.viable
    assert rec.scan is not None and rec.to_dict()["scan"]["current_topology"] == "single_agent"
    if rec.primary.topology.id != "single_agent":
        assert "### Gap: current vs. recommended" in md


def test_scan_missing_dir():
    with pytest.raises(NotADirectoryError):
        scan_repository(FIXTURE / "nope")


# ------------------------------------------------------------------ service

@pytest.fixture()
def client(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from vgselect3a.service.app import app

    monkeypatch.setenv("VGSELECT_SCAN_ROOTS", str(FIXTURE.parent))
    monkeypatch.delenv("VGSELECT_ALLOW_GIT_CLONE", raising=False)
    return TestClient(app)


def test_health_and_reference_endpoints(client):
    assert client.get("/health").json()["status"] == "ok"
    fields = client.get("/api/v1/fields").json()
    assert any(f["name"] == "latency_budget_s" for f in fields)
    assert len(client.get("/api/v1/topologies").json()) == 10
    assert "ANTHROPIC_BEA" in client.get("/api/v1/citations").json()
    ex = client.get("/api/v1/examples").json()
    assert any(e["name"] == "deep_research" for e in ex)
    assert "<title>" in client.get("/").text


def test_recommend_endpoint_and_openapi(client):
    r = client.post("/api/v1/recommend", json={"profile": {"task_complexity": "open_ended", "steps_predictable": False, "parallel_subtasks": 6,
                                                            "knowledge_sources": 4, "retrieval_depth": "exhaustive", "tool_count": 5,
                                                            "tool_calls_per_task": 40, "latency_budget_s": 600, "sources": ["web", "wiki"]}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["primary"] == "orchestrator_workers"
    assert body["report_markdown"].startswith("# Architecture recommendation")
    assert any(c["name"].startswith("Researcher: web") for c in body["plan"]["components"])
    spec = client.get("/openapi.json").json()
    assert "/api/v1/recommend" in spec["paths"] and "/api/v1/scan/upload" in spec["paths"]
    assert spec["info"]["title"].startswith("VG Select: 3A")


def test_recommend_rejects_bad_profile(client):
    r = client.post("/api/v1/recommend", json={"profile": {"task_complexity": "gigantic"}})
    assert r.status_code == 422


def test_scan_path_allowlist(client, monkeypatch):
    r = client.post("/api/v1/scan", json={"path": str(FIXTURE)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scan"]["current_topology"] == "single_agent"
    assert body["recommendation"]["primary"]
    assert client.post("/api/v1/scan", json={"path": "/"}).status_code == 403
    monkeypatch.setenv("VGSELECT_SCAN_ROOTS", "")
    assert client.post("/api/v1/scan", json={"path": str(FIXTURE)}).status_code == 403
    assert client.post("/api/v1/scan", json={"git_url": "https://example.com/x.git"}).status_code == 403
    assert client.post("/api/v1/scan", json={}).status_code == 422


def test_scan_upload_zip(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in FIXTURE.rglob("*"):
            if p.is_file():
                zf.write(p, f"sample_repo/{p.relative_to(FIXTURE)}")
    r = client.post("/api/v1/scan/upload", files={"archive": ("repo.zip", buf.getvalue(), "application/zip")},
                    data={"overrides": json.dumps({"latency_budget_s": 8, "accuracy_priority": 5})})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile"]["accuracy_priority"] == 5
    assert "issue_refund" in body["scan"]["tools"]
    bad = client.post("/api/v1/scan/upload", files={"archive": ("x.zip", b"not a zip", "application/zip")})
    assert bad.status_code == 422


def test_describe_disabled_without_credentials(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("VGSELECT_DESCRIBE_ENABLED", raising=False)
    r = client.post("/api/v1/describe", json={"text": "A support bot that refunds orders and looks up shipping."})
    assert r.status_code == 503
