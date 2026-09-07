import io
import json
import py_compile
import tempfile
import zipfile
from pathlib import Path

import pytest

from vgselect3a import TOPOLOGIES, WorkloadProfile, recommend
from vgselect3a.decomposition import build_plan
from vgselect3a.scaffold import build_skeleton, skeleton_files
from vgselect3a.scanner import merge_profile, scan_repository

EXAMPLES = Path(__file__).resolve().parents[1] / "src" / "vgselect3a" / "examples"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_repo"


def _rec(name):
    return recommend(WorkloadProfile.from_dict(json.loads((EXAMPLES / f"{name}.json").read_text())))


def _rec_for(topology_id):
    """A recommendation whose primary is forced to `topology_id` (for template coverage)."""
    base = _rec("deep_research")
    base.candidates = sorted(base.candidates, key=lambda c: c.topology.id != topology_id)
    base.plan = build_plan(base.profile, topology_id)
    return base


# ------------------------------------------------------------------ PDF

@pytest.mark.parametrize("name", ["deep_research", "faq_bot", "pr_review", "customer_support"])
def test_pdf_builds_for_examples(name):
    pytest.importorskip("reportlab")
    pdf = _rec(name).to_pdf()
    assert pdf.startswith(b"%PDF") and len(pdf) > 5_000
    assert b"/Page" in pdf


def test_pdf_includes_scan_section():
    pytest.importorskip("reportlab")
    scan = scan_repository(FIXTURE)
    rec = recommend(WorkloadProfile.from_dict(merge_profile(scan, {"latency_budget_s": 8})), scan=scan)
    pdf = rec.to_pdf()
    assert pdf.startswith(b"%PDF") and len(pdf) > 5_000


# ------------------------------------------------------------------ skeleton

@pytest.mark.parametrize("topology_id", sorted(TOPOLOGIES))
def test_skeleton_generated_code_compiles(topology_id):
    files = skeleton_files(_rec_for(topology_id))
    assert {"README.md", "ARCHITECTURE.md", "requirements.txt", "app/graph.py", "app/agents.py", "app/tools.py", "app/config.py", "app/state.py", "main.py", "tests/test_graph.py"} <= set(files)
    assert "build_graph" in files["app/graph.py"] and "StateGraph" in files["app/graph.py"]
    with tempfile.TemporaryDirectory() as d:
        for name, content in files.items():
            if name.endswith(".py"):
                fp = Path(d) / name
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content)
                py_compile.compile(str(fp), doraise=True)


def test_skeleton_zip_layout_and_tools():
    rec = _rec("deep_research")
    data = build_skeleton(rec)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert all(n.startswith("deep_research-agent/") for n in names)
        tools = zf.read("deep_research-agent/app/tools.py").decode()
        assert "def web_search(" in tools and "TOOLS = [" in tools
        config = zf.read("deep_research-agent/app/config.py").decode()
        assert "claude-opus-5" in config and "MAX_WORKERS" in config
        readme = zf.read("deep_research-agent/README.md").decode()
        assert "Orchestrator + worker subagents" in readme


def test_skeleton_rejects_unknown_framework():
    with pytest.raises(ValueError):
        skeleton_files(_rec("faq_bot"), framework="crewai")


# ------------------------------------------------------------------ service

@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from vgselect3a.service.app import app
    return TestClient(app)


def test_pdf_and_skeleton_endpoints(client):
    pytest.importorskip("reportlab")
    profile = json.loads((EXAMPLES / "pr_review.json").read_text())
    r = client.post("/api/v1/recommend/pdf", json={"profile": profile})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf") and r.content.startswith(b"%PDF")
    assert "pr_review-architecture.pdf" in r.headers["content-disposition"]
    r = client.post("/api/v1/recommend/skeleton", json={"profile": profile, "framework": "langgraph"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert any(n.endswith("app/graph.py") for n in zf.namelist())
    # scan round-trip into the PDF
    scan = client.post("/api/v1/scan/upload", files={"archive": ("r.zip", _zip_fixture(), "application/zip")}, data={"recommend": "false"}).json()
    r = client.post("/api/v1/recommend/pdf", json={"profile": scan["profile"], "scan": scan["scan"]})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert client.get("/health").json()["pdf_enabled"] is True


def _zip_fixture() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in FIXTURE.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                zf.write(p, f"sample_repo/{p.relative_to(FIXTURE)}")
    return buf.getvalue()
