import io
import json
import py_compile
import tempfile
import zipfile
from pathlib import Path

import pytest

from vgselect3a import TOPOLOGIES, WorkloadProfile, recommend
from vgselect3a.catalog import Catalog, ModelSpec
from vgselect3a.decomposition import build_plan
from vgselect3a.estimator import estimate
from vgselect3a.model_selector import SelectionPolicy, select_models
from vgselect3a.requirements import derive_requirements
from vgselect3a.scaffold import skeleton_files

EXAMPLES = Path(__file__).resolve().parents[1] / "src" / "vgselect3a" / "examples"


def _profile(name, **over):
    return WorkloadProfile.from_dict({**json.loads((EXAMPLES / f"{name}.json").read_text()), **over})


# ------------------------------------------------------------------ catalog

def test_default_catalog_loads_and_validates():
    cat = Catalog.default()
    assert len(cat.models) >= 5
    assert {"anthropic", "openai", "google", "self_hosted"} <= set(cat.providers())
    verified = [m for m in cat.models if not m.illustrative]
    assert {m.id for m in verified} == {"claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"}
    assert cat.get("claude-opus-5").reasoning_tier == 5


def test_catalog_rejects_bad_entries_and_duplicates():
    with pytest.raises(ValueError):
        ModelSpec(id="x", display_name="x", provider="other", family="f", platforms=["other"], reasoning_tier=9)
    with pytest.raises(ValueError):
        Catalog.from_dict([{"id": "a", "display_name": "a", "provider": "other", "family": "f", "platforms": ["other"]}] * 2)
    merged = Catalog.default().merged([ModelSpec(id="claude-opus-5", display_name="override", provider="anthropic", family="claude-5", platforms=["bedrock"], reasoning_tier=5)])
    assert merged.get("claude-opus-5").display_name == "override" and len(merged.models) == len(Catalog.default().models)


# ------------------------------------------------------------------ requirements

def test_requirements_derive_role_types_and_levels():
    p = _profile("deep_research")
    plan = build_plan(p, "orchestrator_workers")
    reqs = {r.component_id: r for r in derive_requirements(p, plan)}
    assert reqs["lead"].role_type == "orchestrator" and reqs["lead"].reasoning_level == 5
    assert reqs["worker_1"].role_type == "worker" and reqs["worker_1"].reasoning_level <= 4
    assert reqs["critic"].independent_of == "lead"
    assert reqs["lead"].latency_share_s + reqs["worker_1"].latency_share_s + reqs["critic"].latency_share_s == pytest.approx(p.latency_budget_s, rel=0.01)
    router = {r.component_id: r for r in derive_requirements(_profile("customer_support"), build_plan(_profile("customer_support"), "router"))}["router"]
    assert router.needs_structured_output and router.reasoning_level <= 2 and router.latency_share_s <= 1.5


# ------------------------------------------------------------------ selection

def test_default_selection_tiers_roles_on_verified_models():
    rec = recommend(_profile("deep_research"))
    sel = rec.selection
    assert sel.choice("lead").model_id == "claude-opus-5"
    assert sel.choice("worker_1").model_id in ("claude-sonnet-5", "claude-haiku-4-5")
    assert sel.choice("worker_1").fallback_model_id is not None
    assert sel.providers_used == ["anthropic"]
    assert rec.plan.components[0].model_id == "claude-opus-5" and rec.plan.components[0].provider == "anthropic"
    assert rec.selected_estimate is not None and rec.selected_estimate.tiers_used["opus"] == "claude-opus-5"
    assert "## Model selection per role" in rec.to_markdown()
    assert rec.to_dict()["selection"]["choices"][0]["component_id"] == "lead"


def test_policy_allows_unverified_and_prefers_cheaper_equal_tier():
    rec = recommend(_profile("deep_research"), policy=SelectionPolicy(require_verified=False))
    chosen = {c.component_id: c.model_id for c in rec.selection.choices}
    assert any(m in ("gemini-pro", "gpt-frontier") for m in chosen.values())
    assert any("illustrative" in w for w in rec.selection.warnings)


def test_orchestrator_never_weaker_than_staffed_models():
    cat = Catalog.default().merged([ModelSpec(id="cheap-genius", display_name="x", provider="other", family="x", platforms=["other"],
                                              data_classes=["public", "internal"], reasoning_tier=5, tool_use=3, strict_schema=True,
                                              context_window=1_000_000, max_output=64_000, input_price=0.1, output_price=0.5)])
    rec = recommend(_profile("deep_research"), catalog=cat)
    lead = cat.get(rec.selection.choice("lead").model_id)
    for c in rec.selection.choices:
        if c.model_id and c.role_type != "orchestrator":
            assert cat.get(c.model_id).reasoning_tier <= lead.reasoning_tier


def test_restricted_data_limits_to_cleared_models_and_reports_unfilled():
    rec = recommend(_profile("deep_research", data_sensitivity="restricted"), policy=SelectionPolicy(require_verified=False))
    sel = rec.selection
    assert "lead" in sel.unfilled
    assert any("not cleared for restricted data" in j.reason for j in sel.choice("lead").rejected)
    assert any("no model in the catalog satisfies" in w for w in sel.warnings)


def test_provider_and_region_filters():
    p = _profile("customer_support")
    sel = recommend(p, policy=SelectionPolicy(allowed_providers=["openai"], require_verified=False)).selection
    assert {Catalog.default().get(c.model_id).provider for c in sel.choices if c.model_id} == {"openai"}
    sel2 = recommend(p, policy=SelectionPolicy(regions=["on_prem"], require_verified=False)).selection
    assert all((not c.model_id) or c.model_id == "llama-self-hosted" for c in sel2.choices)


def test_measured_evidence_lifts_lower_tier_model():
    cat = Catalog.default().merged([ModelSpec(id="small-but-proven", display_name="x", provider="other", family="x", platforms=["other"],
                                              data_classes=["public", "internal"], reasoning_tier=3, tool_use=2, strict_schema=True,
                                              context_window=200_000, max_output=32_000, input_price=0.2, output_price=1.0,
                                              evidence={"classification": 0.97})])
    p = _profile("content_moderation")
    rec = recommend(p, catalog=cat)
    llm = rec.selection.choice("llm")
    assert llm.model_id == "small-but-proven"
    assert any("measured classification accuracy 97%" in n for n in llm.rationale)


def test_verifier_independence_switches_family_when_available():
    cat = Catalog.default().merged([ModelSpec(id="other-frontier", display_name="x", provider="other", family="otherfam", platforms=["other"],
                                              data_classes=["public", "internal"], reasoning_tier=5, tool_use=3, strict_schema=True,
                                              context_window=1_000_000, max_output=64_000, input_price=5.0, output_price=25.0, ttft_s=1.5, tokens_per_s=55)])
    rec = recommend(_profile("deep_research"), catalog=cat)
    lead, critic = rec.selection.choice("lead"), rec.selection.choice("critic")
    assert lead.model_id and critic.model_id and cat.get(lead.model_id).family != cat.get(critic.model_id).family


def test_ranking_estimates_use_catalog_reference_tiers():
    p = _profile("deep_research")
    rec = recommend(p, policy=SelectionPolicy(regions=["on_prem"], require_verified=False))
    assert set(rec.tiers[t].model_id for t in rec.tiers) == {"llama-self-hosted"}
    e = estimate(p, "orchestrator_workers", rec.tiers)
    assert e.tiers_used["opus"] == "llama-self-hosted"


# ------------------------------------------------------------------ skeleton with mixed providers

def test_skeleton_uses_provider_aware_factory_and_packages():
    rec = recommend(_profile("customer_support"), policy=SelectionPolicy(require_verified=False))
    rec._catalog = Catalog.default()
    files = skeleton_files(rec)
    assert "init_chat_model" in files["app/agents.py"]
    assert "provider=" in files["app/config.py"] and "fallback=" in files["app/config.py"]
    provs = {c.provider for c in rec.plan.components if c.provider}
    if "openai" in provs:
        assert "langchain-openai" in files["requirements.txt"] and "OPENAI_API_KEY" in files[".env.example"]
    with tempfile.TemporaryDirectory() as d:
        for name, content in files.items():
            if name.endswith(".py"):
                fp = Path(d) / name
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content)
                py_compile.compile(str(fp), doraise=True)


# ------------------------------------------------------------------ service

@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from vgselect3a.service.app import app
    return TestClient(app)


def test_catalog_endpoints_and_policy_in_recommend(client):
    cat = client.get("/api/v1/catalog").json()
    assert cat["name"] == "vgselect-default" and "anthropic" in cat["providers"]
    ok = client.post("/api/v1/catalog/validate", json=[cat["models"][0]])
    assert ok.status_code == 200 and ok.json()["ok"]
    bad = client.post("/api/v1/catalog/validate", json=[{"id": "x"}])
    assert bad.status_code == 422
    profile = json.loads((EXAMPLES / "deep_research.json").read_text())
    r = client.post("/api/v1/recommend", json={"profile": profile, "include_markdown": False, "policy": {"allowed_providers": ["anthropic"]}})
    assert r.status_code == 200
    body = r.json()
    assert body["selection"]["providers_used"] == ["anthropic"]
    assert body["selected_estimate"]["tiers_used"]["opus"] == "claude-opus-5"
    assert body["plan"]["components"][0]["chosen_model"] == "claude-opus-5"
    r2 = client.post("/api/v1/recommend", json={"profile": profile, "include_markdown": False,
                                                 "catalog_models": [{"id": "my-model", "display_name": "m", "provider": "other", "family": "f", "platforms": ["other"],
                                                                     "reasoning_tier": 5, "tool_use": 3, "strict_schema": True, "context_window": 1000000, "max_output": 64000,
                                                                     "input_price": 0.5, "output_price": 1.0}]})
    assert r2.status_code == 200 and any(c["model_id"] == "my-model" for c in r2.json()["selection"]["choices"])
    assert client.get("/health").json()["catalog_models"] >= 5
    pytest.importorskip("reportlab")
    pdf = client.post("/api/v1/recommend/pdf", json={"profile": profile, "policy": {"require_verified": False}})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    zipr = client.post("/api/v1/recommend/skeleton", json={"profile": profile, "policy": {"require_verified": False}})
    with zipfile.ZipFile(io.BytesIO(zipr.content)) as zf:
        cfg = next(zf.read(n).decode() for n in zf.namelist() if n.endswith("app/config.py"))
        assert "provider=" in cfg
