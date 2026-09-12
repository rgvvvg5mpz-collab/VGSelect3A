import json
from pathlib import Path

import pytest

from vgselect3a import WorkloadProfile, recommend
from vgselect3a.report_card import build_report_card, design_level, letter, task_level
from vgselect3a.scanner import merge_profile, scan_repository
from vgselect3a.traces import compute_behaviour, load_traces, parse_records, synthesize_traces, traces_to_jsonl

EXAMPLES = Path(__file__).resolve().parents[1] / "src" / "vgselect3a" / "examples"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_repo"


def _profile(name, **over):
    return WorkloadProfile.from_dict({**json.loads((EXAMPLES / f"{name}.json").read_text()), **over})


# ------------------------------------------------------------------ traces

def test_native_traces_round_trip_and_metrics(tmp_path):
    ts = synthesize_traces("orchestrator_workers", n_tasks=12, runs_per_task=2, seed=3)
    path = tmp_path / "t.jsonl"
    path.write_text(traces_to_jsonl(ts))
    loaded = load_traces(path)
    assert len(loaded) == 24 and loaded.agents()[0] == "lead"
    b = compute_behaviour(loaded)
    assert b.runs == 24 and b.tasks == 12 and b.spawns_per_run > 0 and b.success_rate is not None
    assert b.consistency is not None and b.trajectory_diversity is not None
    assert b.steps["p95"] >= b.steps["p50"] > 0
    lead = compute_behaviour(loaded, agent="lead")
    assert lead.runs == 24 and lead.tool_calls["mean"] == 0
    worker = compute_behaviour(loaded, agent="worker_1")
    assert worker.tool_calls["mean"] > 0


def test_langsmith_and_otel_adapters():
    ls = [{"id": "r1", "name": "agent", "run_type": "chain", "outputs": {}, "error": None,
           "child_runs": [{"name": "ChatAnthropic", "run_type": "llm", "usage_metadata": {"input_tokens": 1200, "output_tokens": 80}},
                          {"name": "search_kb", "run_type": "tool", "inputs": {"q": "x"}},
                          {"name": "ChatAnthropic", "run_type": "llm", "usage_metadata": {"input_tokens": 2000, "output_tokens": 200}}]}]
    ts = parse_records(ls)
    assert len(ts) == 1 and [s.type for s in ts.runs[0].steps] == ["llm", "tool", "llm"] and ts.runs[0].success is True
    otel = [{"trace_id": "t1", "name": "chat", "duration_ms": 900, "attributes": {"gen_ai.operation.name": "chat", "gen_ai.usage.input_tokens": 500, "gen_ai.usage.output_tokens": 50}},
            {"trace_id": "t1", "name": "tool", "duration_ms": 200, "attributes": {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "lookup"}}]
    ts2 = parse_records(otel)
    assert len(ts2) == 1 and ts2.runs[0].steps[1].name == "lookup"
    assert any("OpenTelemetry" in w for w in ts2.warnings)


def test_unrecognised_records_are_reported():
    ts = parse_records([{"foo": 1}, "x"])
    assert len(ts) == 0 and len(ts.warnings) >= 2


# ------------------------------------------------------------------ complexity + card

def test_complexity_levels():
    assert task_level(_profile("faq_bot")) == 1
    assert task_level(_profile("deep_research")) == 5
    assert design_level({"tool_count": 0}) == 1
    assert design_level({"tool_count": 8, "delegation_depth": 1, "handoffs": False}) == 4
    assert design_level({"tool_count": 40, "delegation_depth": 2}) == 5
    assert letter(95) == "A" and letter(61) == "D" and letter(None) == "n/a"


def test_design_time_card_from_scan():
    scan = scan_repository(FIXTURE)
    assert scan.design["tool_count"] == 5 and scan.design["tool_overlap_count"] == 3
    p = WorkloadProfile.from_dict(merge_profile(scan, {"latency_budget_s": 8, "accuracy_priority": 4}))
    rec = recommend(p, scan=scan)
    card = rec.report_card
    assert card is not None and card.mode == "design-time" and card.behaviour is None
    assert card.dimension("quality").score is None and card.dimension("governance").score is not None
    assert any(m.id == "tool_overlap" for m in card.mismatches)
    assert "## Agent report card" in rec.to_markdown()
    assert rec.to_dict()["report_card"]["complexity"]["behaviour"] is None


def test_full_card_grades_and_flags_loops():
    scan = scan_repository(FIXTURE)
    p = WorkloadProfile.from_dict(merge_profile(scan, {"latency_budget_s": 8, "accuracy_priority": 4}))
    good = synthesize_traces("single_agent", n_tasks=30, runs_per_task=2, seed=1, quality=0.95, chaos=0.0, tools=["lookup_order", "search_kb"])
    bad = synthesize_traces("single_agent", n_tasks=30, runs_per_task=2, seed=2, quality=0.5, chaos=0.6, tools=["lookup_order", "search_kb"])
    rec_good = recommend(p, scan=scan, traces=good)
    rec_bad = recommend(p, scan=scan, traces=bad)
    cg, cb = rec_good.report_card, rec_bad.report_card
    assert cg.mode == "full" and cb.mode == "full"
    assert cg.overall_score > cb.overall_score
    assert cg.dimension("quality").score > cb.dimension("quality").score
    assert cb.dimension("reliability").score < cg.dimension("reliability").score
    assert cb.behaviour.repetition_rate > 0 and cb.behaviour.termination_limit_rate > 0
    assert cg.agents and cg.agents[0].agent == "agent" and cg.agents[0].role in ("Plans and executes the whole task in one tool-use loop.", None) or cg.agents[0].model
    md = cb.to_markdown()
    assert "Per-agent cards" in md and "Behavioural metrics" in md


def test_multi_agent_card_has_per_agent_rows_and_coordination_flag():
    p = _profile("deep_research")
    ts = synthesize_traces("orchestrator_workers", n_tasks=20, runs_per_task=1, seed=5, workers=14)
    rec = recommend(p, traces=ts)
    card = rec.report_card
    assert card is not None and len(card.agents) >= 3
    names = {a.agent for a in card.agents}
    assert "lead" in names and any(n.startswith("worker_") for n in names)
    assert any(m.id == "coordination_waste" for m in card.mismatches)


def test_pdf_includes_report_card():
    pytest.importorskip("reportlab")
    scan = scan_repository(FIXTURE)
    p = WorkloadProfile.from_dict(merge_profile(scan, {"latency_budget_s": 8}))
    ts = synthesize_traces("single_agent", n_tasks=10, runs_per_task=1, seed=9)
    pdf = recommend(p, scan=scan, traces=ts).to_pdf()
    assert pdf.startswith(b"%PDF") and len(pdf) > 8_000


# ------------------------------------------------------------------ service

@pytest.fixture()
def client(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from vgselect3a.service.app import app
    monkeypatch.setenv("VGSELECT_SCAN_ROOTS", str(FIXTURE.parent))
    return TestClient(app)


def test_report_card_endpoint_and_traces_in_recommend(client):
    profile = json.loads((EXAMPLES / "customer_support.json").read_text())
    ts = synthesize_traces("router", n_tasks=8, runs_per_task=2, seed=4)
    records = [json.loads(l) for l in traces_to_jsonl(ts).splitlines()]
    r = client.post("/api/v1/report-card", json={"profile": profile, "traces": records})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "full" and body["overall_grade"] in "ABCDF" and "markdown" in body and body["agents"]
    r2 = client.post("/api/v1/recommend", json={"profile": profile, "traces": records, "include_markdown": False})
    assert r2.status_code == 200 and r2.json()["report_card"]["mode"] == "full"
    r3 = client.post("/api/v1/scan", json={"path": str(FIXTURE), "traces": records})
    assert r3.status_code == 200 and r3.json()["recommendation"]["report_card"]["mode"] == "full"
