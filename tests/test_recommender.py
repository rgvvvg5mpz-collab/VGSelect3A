import json
import subprocess
import sys
from pathlib import Path

import pytest

from vgselect3a import TOPOLOGIES, WorkloadProfile, recommend
from vgselect3a.cli import main
from vgselect3a.estimator import estimate, worker_count
from vgselect3a.profile import json_schema

EXAMPLES = Path(__file__).resolve().parents[1] / "src" / "vgselect3a" / "examples"


def load(name: str) -> WorkloadProfile:
    return WorkloadProfile.from_dict(json.loads((EXAMPLES / f"{name}.json").read_text()))


# --------------------------------------------------------------- canonical scenarios

@pytest.mark.parametrize(
    "example, expected_primary",
    [
        ("faq_bot", {"single_call"}),
        ("content_moderation", {"single_call", "parallel_voting"}),
        ("customer_support", {"router", "single_agent", "handoff_network"}),
        ("coding_agent", {"single_agent", "evaluator_optimizer"}),
        ("deep_research", {"orchestrator_workers"}),
        ("document_extraction", {"prompt_chain", "evaluator_optimizer", "parallel_voting"}),
        ("pr_review", {"parallel_sectioning", "prompt_chain"}),
        ("enterprise_analyst", {"orchestrator_workers", "hierarchical"}),
    ],
)
def test_examples_pick_expected_topology(example, expected_primary):
    rec = recommend(load(example))
    assert rec.primary.topology.id in expected_primary, [(c.topology.id, c.score) for c in rec.candidates[:3]]
    assert rec.primary.viable


def test_every_example_renders_all_formats():
    for path in EXAMPLES.glob("*.json"):
        rec = recommend(WorkloadProfile.from_dict(json.loads(path.read_text())))
        md = rec.to_markdown()
        assert "## Ranked candidates" in md and "```mermaid" in md
        assert rec.to_mermaid().startswith("flowchart TD")
        data = json.loads(rec.to_json())
        assert data["primary"] == rec.primary.topology.id
        assert len(data["candidates"]) == len(TOPOLOGIES)


# --------------------------------------------------------------- viability and ordering

def test_single_call_not_viable_with_tools():
    rec = recommend(WorkloadProfile(tool_count=5, tool_calls_per_task=3))
    single = next(c for c in rec.candidates if c.topology.id == "single_call")
    assert not single.viable
    assert rec.primary.topology.id != "single_call"
    # non-viable candidates sort last regardless of score
    viable_flags = [c.viable for c in rec.candidates]
    assert viable_flags == sorted(viable_flags, reverse=True)


def test_open_ended_forbids_fixed_chain():
    rec = recommend(WorkloadProfile(task_complexity="open_ended", steps_predictable=False))
    chain = next(c for c in rec.candidates if c.topology.id == "prompt_chain")
    assert not chain.viable


# --------------------------------------------------------------- latency / accuracy balance

def test_tighter_budget_moves_toward_faster_topology():
    base = load("deep_research").to_dict()
    slow = recommend(WorkloadProfile.from_dict({**base, "latency_budget_s": 900}))
    fast = recommend(WorkloadProfile.from_dict({**base, "latency_budget_s": 60}))
    assert fast.primary.estimate.latency_s <= slow.primary.estimate.latency_s
    # the orchestrator's latency penalty must be larger under the tight budget
    o_slow = next(c for c in slow.candidates if c.topology.id == "orchestrator_workers")
    o_fast = next(c for c in fast.candidates if c.topology.id == "orchestrator_workers")
    assert o_fast.latency_adj < o_slow.latency_adj


def test_accuracy_priority_buys_latency_tolerance():
    base = load("deep_research").to_dict()
    base["latency_budget_s"] = 60
    lax = recommend(WorkloadProfile.from_dict({**base, "accuracy_priority": 1}))
    strict = recommend(WorkloadProfile.from_dict({**base, "accuracy_priority": 5}))
    o_lax = next(c for c in lax.candidates if c.topology.id == "orchestrator_workers")
    o_strict = next(c for c in strict.candidates if c.topology.id == "orchestrator_workers")
    assert o_strict.latency_adj > o_lax.latency_adj  # smaller penalty when accuracy matters


def test_parallel_research_is_faster_as_orchestrator_than_single_agent():
    p = load("deep_research")
    assert estimate(p, "orchestrator_workers").latency_s < estimate(p, "single_agent").latency_s


def test_orchestrator_costs_more_tokens_than_single_call():
    p = load("deep_research")
    assert estimate(p, "orchestrator_workers").token_multiplier > 5 * estimate(p, "single_call").token_multiplier


def test_capability_saturation_penalises_multi_agent():
    base = load("deep_research").to_dict()
    unmeasured = recommend(WorkloadProfile.from_dict(base))
    saturated = recommend(WorkloadProfile.from_dict({**base, "single_agent_baseline": 0.7}))
    o1 = next(c for c in unmeasured.candidates if c.topology.id == "orchestrator_workers")
    o2 = next(c for c in saturated.candidates if c.topology.id == "orchestrator_workers")
    assert o2.fit < o1.fit
    assert any(s.rule_id == "R37" for s in o2.signals)


def test_frontier_is_pareto():
    rec = recommend(load("coding_agent"))
    f = rec.frontier
    assert f, "frontier must not be empty"
    lat = [c.estimate.latency_s for c in f]
    q = [c.quality_proxy for c in f]
    assert lat == sorted(lat)
    assert q == sorted(q)
    assert all(c.viable for c in f)


# --------------------------------------------------------------- decomposition

def test_worker_count_follows_anthropic_heuristic():
    assert worker_count(WorkloadProfile(parallel_subtasks=3, task_complexity="complex", steps_predictable=False)) == 3
    assert worker_count(load("deep_research")) >= 5
    assert worker_count(load("enterprise_analyst")) <= 20


def test_orchestrator_plan_uses_named_sources_and_tiers_models():
    rec = recommend(load("deep_research"))
    names = [c.name for c in rec.plan.components]
    assert any("Researcher: web" in n for n in names)
    lead = rec.plan.components[0]
    assert lead.tier == "opus"
    workers = [c for c in rec.plan.components if c.parallel_group == "workers"]
    assert workers and all(c.tier in ("sonnet", "haiku") for c in workers)
    assert any(a.id == "verification" for a in rec.plan.augmentations)
    assert any(a.id == "termination" for a in rec.plan.augmentations)


def test_irreversible_actions_get_a_gate():
    rec = recommend(load("customer_support"))
    assert any(a.id == "gate" for a in rec.plan.augmentations)


def test_sectioning_plan_uses_named_sections():
    rec = recommend(load("pr_review"))
    assert rec.primary.topology.id == "parallel_sectioning"
    assert any("security" in c.name for c in rec.plan.components)


# --------------------------------------------------------------- profile

def test_profile_validation_rejects_bad_enum_and_range():
    with pytest.raises(ValueError):
        WorkloadProfile(task_complexity="huge")
    with pytest.raises(ValueError):
        WorkloadProfile(accuracy_priority=9)


def test_from_dict_coerces_and_keeps_extras():
    p = WorkloadProfile.from_dict({"tool_count": "3", "latency_budget_s": "12", "steps_predictable": "no", "domains": ["a", "b"]})
    assert p.tool_count == 3 and p.latency_budget_s == 12.0 and p.steps_predictable is False
    assert p.extra["domains"] == ["a", "b"]
    assert WorkloadProfile.from_json(p.to_json()).to_dict() == p.to_dict()


def test_json_schema_is_strict():
    schema = json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["task_complexity"]["enum"] == ["trivial", "simple", "moderate", "complex", "open_ended"]


# --------------------------------------------------------------- CLI

def test_cli_recommend_json(capsys):
    main(["recommend", "--example", "faq_bot", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["primary"] == "single_call"


def test_cli_set_overrides(capsys):
    main(["recommend", "--example", "faq_bot", "--set", "tool_count=4", "--set", "tool_calls_per_task=2", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["primary"] != "single_call"


def test_cli_module_entrypoint():
    out = subprocess.run([sys.executable, "-m", "vgselect3a.cli", "examples"], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": str(EXAMPLES.parents[1])})
    assert "deep_research" in out.stdout
