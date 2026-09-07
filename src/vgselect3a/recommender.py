"""Combine rule fit, latency fit and cost fit into a ranked recommendation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .catalog import Catalog, ModelSpec
from .decomposition import Plan, build_plan
from .estimator import Estimate, estimate
from .model_selector import Selection, SelectionPolicy, select_models
from .profile import WorkloadProfile
from .rules import Signal, evaluate_rules
from .scanner import ScanResult
from .topologies import MODEL_TIERS, TOPOLOGIES, ModelTier, Topology

LATENCY_RULES = {"R23", "R24", "R25"}
COST_RULES = {"R26", "R27"}


def viability(p: WorkloadProfile, topology_id: str) -> tuple[bool, str]:
    """Hard constraints: a topology that cannot do the job is ranked last whatever its score."""
    if topology_id == "single_call":
        if p.uses_tools:
            return False, "needs tool calls; a single call cannot act"
        if p.retrieval_depth in ("multi_hop", "exhaustive"):
            return False, "follow-up retrieval must be decided by the model"
        if p.task_complexity == "open_ended":
            return False, "open-ended task cannot be solved in one call"
    if topology_id == "prompt_chain" and p.task_complexity == "open_ended":
        return False, "a fixed chain cannot follow an open-ended path"
    if topology_id in ("parallel_sectioning",) and p.parallel_subtasks < 2 and p.context_pressure == "low":
        return False, "nothing to fan out"
    if topology_id == "handoff_network" and p.scope_breadth < 2:
        return False, "no second specialist to hand off to"
    if topology_id == "hierarchical" and p.scope_breadth < 2 and p.parallel_subtasks < 8:
        return False, "no domains or sub-task volume to justify two levels"
    return True, ""


@dataclass
class Candidate:
    topology: Topology
    fit: float                 # sum of rule deltas
    quality_proxy: float       # fit excluding latency/cost rules: structural + accuracy fit only
    latency_adj: float
    cost_adj: float
    score: float
    estimate: Estimate
    signals: list[Signal] = field(default_factory=list)
    viable: bool = True
    infeasible_reason: str = ""

    @property
    def latency_verdict(self) -> str:
        r = self.estimate.latency_s / max(0.1, self.budget)
        if r <= 0.7:
            return "fits"
        if r <= 1.0:
            return "tight"
        if r <= 2.0:
            return "exceeds"
        return "far over"

    budget: float = 0.0


@dataclass
class Recommendation:
    profile: WorkloadProfile
    candidates: list[Candidate]      # ranked, best first
    plan: Plan                       # for the primary candidate
    frontier: list[Candidate]        # Pareto set over (latency, quality_proxy)
    fastest_viable: Candidate | None
    most_accurate: Candidate | None
    headline: str
    scan: ScanResult | None = None
    selection: Selection | None = None
    selected_estimate: Estimate | None = None
    tiers: dict[str, ModelTier] = field(default_factory=lambda: dict(MODEL_TIERS))

    @property
    def primary(self) -> Candidate:
        return self.candidates[0]

    def to_dict(self) -> dict:
        from .render import to_dict
        return to_dict(self)

    def to_json(self, indent: int = 2) -> str:
        from .render import to_json
        return to_json(self, indent)

    def to_markdown(self) -> str:
        from .render import to_markdown
        return to_markdown(self)

    def to_mermaid(self) -> str:
        from .render import to_mermaid
        return to_mermaid(self.plan)

    def to_svg(self) -> str:
        from .render import to_svg
        return to_svg(self.plan)

    def to_pdf(self) -> bytes:
        """Architecture document (needs the `pdf` extra)."""
        from .pdf_report import build_pdf
        return build_pdf(self)

    def to_skeleton(self, framework: str = "langgraph") -> bytes:
        """Zip archive of a runnable agent project for the recommended topology."""
        from .scaffold import build_skeleton
        return build_skeleton(self, framework)


# ---------------------------------------------------------------- scoring

def _latency_adjustment(p: WorkloadProfile, est: Estimate) -> float:
    ratio = est.latency_s / max(0.1, p.latency_budget_s)
    if ratio <= 0.5:
        base = 1.0
    elif ratio <= 1.0:
        base = 0.5 - (ratio - 0.5) * 1.0          # 0.5 .. 0
    elif ratio <= 2.0:
        base = -1.5 - (ratio - 1.0) * 2.0         # -1.5 .. -3.5
    else:
        base = -3.5 - min(4.0, math.log2(ratio))  # -4.5 .. -7.5
    # Accuracy priority buys latency tolerance; cost of an over-budget answer is
    # smaller when correctness matters more than speed.
    tolerance = 1.0 + 0.3 * (3 - p.accuracy_priority)   # 1.6 (acc=1) .. 0.4 (acc=5)
    if base < 0:
        base *= max(0.4, min(1.6, tolerance))
    return round(base, 2)


def _cost_adjustment(p: WorkloadProfile, est: Estimate, cheapest: float) -> float:
    rel = max(1.0, est.cost_usd / max(cheapest, 1e-6))
    return round(-(p.cost_sensitivity / 3.0) * 0.6 * math.log2(rel), 2)


def _spec_to_tier(tier: str, m: ModelSpec) -> ModelTier:
    return ModelTier(tier, m.id, m.input_price, m.output_price, m.ttft_s, m.tokens_per_s, m.notes or MODEL_TIERS[tier].role)


def tiers_from_catalog(p: WorkloadProfile, catalog: Catalog, policy: SelectionPolicy) -> dict[str, ModelTier]:
    """Reference model per capability level (5/4/3 -> opus/sonnet/haiku) that the
    ecosystem and policy actually allow, so every topology is estimated on models
    you could deploy. Cheapest eligible model per level; a missing level borrows
    the nearest level above (then below)."""
    def eligible(m: ModelSpec) -> bool:
        if policy.require_approved and not m.approved:
            return False
        if policy.allowed_providers and m.provider not in policy.allowed_providers:
            return False
        if m.provider in policy.blocked_providers:
            return False
        if policy.allowed_platforms and not set(m.platforms) & set(policy.allowed_platforms):
            return False
        if policy.regions and not set(m.regions) & set(policy.regions):
            return False
        if policy.require_verified and m.illustrative:
            return False
        return p.data_sensitivity in m.data_classes
    ok = [m for m in catalog.models if eligible(m)]
    by_level: dict[int, list[ModelSpec]] = {}
    for m in ok:
        by_level.setdefault(m.reasoning_tier, []).append(m)
    out: dict[str, ModelTier] = {}
    for tier, level in (("opus", 5), ("sonnet", 4), ("haiku", 3)):
        pick = None
        for lv in (level, level + 1, level - 1, level + 2, level - 2):
            if by_level.get(lv):
                pick = min(by_level[lv], key=lambda m: m.input_price + m.output_price)
                break
        out[tier] = _spec_to_tier(tier, pick) if pick else MODEL_TIERS[tier]
    return out


def recommend(p: WorkloadProfile, scan: ScanResult | None = None, catalog: Catalog | None = None,
              policy: SelectionPolicy | None = None) -> Recommendation:
    """Rank topologies for a profile. Pass the ScanResult the profile was derived
    from so the report can show the current-vs-recommended gap. `catalog` and
    `policy` describe the model ecosystem; the bundled catalog is used otherwise."""
    catalog = catalog or Catalog.default()
    policy = policy or SelectionPolicy()
    tiers = tiers_from_catalog(p, catalog, policy)
    signals = evaluate_rules(p)
    by_topo: dict[str, list[Signal]] = {tid: [] for tid in TOPOLOGIES}
    for s in signals:
        by_topo[s.topology_id].append(s)

    estimates = {tid: estimate(p, tid, tiers) for tid in TOPOLOGIES}
    cheapest = min(e.cost_usd for e in estimates.values())

    cands: list[Candidate] = []
    for tid, topo in TOPOLOGIES.items():
        sigs = by_topo[tid]
        fit = sum(s.delta for s in sigs)
        quality = sum(s.delta for s in sigs if s.rule_id.rstrip("abc") not in LATENCY_RULES | COST_RULES)
        est = estimates[tid]
        lat = _latency_adjustment(p, est)
        cost = _cost_adjustment(p, est, cheapest)
        ok, why = viability(p, tid)
        cands.append(Candidate(topo, round(fit, 2), round(quality, 2), lat, cost, round(fit + lat + cost, 2), est, sigs, budget=p.latency_budget_s, viable=ok, infeasible_reason=why))

    cands.sort(key=lambda c: (not c.viable, -c.score, c.estimate.latency_s, c.topology.build_complexity))
    plan = build_plan(p, cands[0].topology.id)

    # Pareto frontier over (latency asc, quality desc)
    frontier: list[Candidate] = []
    best_q = -math.inf
    for c in sorted((c for c in cands if c.viable), key=lambda c: (c.estimate.latency_s, -c.quality_proxy)):
        if c.quality_proxy > best_q:
            frontier.append(c)
            best_q = c.quality_proxy

    in_budget = [c for c in cands if c.viable and c.estimate.latency_s <= p.latency_budget_s]
    fastest = min(in_budget, key=lambda c: c.estimate.latency_s) if in_budget else None
    accurate = max((c for c in cands if c.viable), key=lambda c: (c.quality_proxy, -c.estimate.latency_s))

    selection = select_models(plan, p, catalog, policy)
    for c in plan.components:
        ch = selection.choice(c.id)
        if ch and ch.model_id:
            spec = catalog.get(ch.model_id)
            c.chosen_model, c.provider, c.fallback_model, c.effort = ch.model_id, spec.provider if spec else None, ch.fallback_model_id, ch.effort
    sel_tiers = dict(tiers)
    for c in plan.components:
        spec = catalog.get(c.chosen_model) if c.chosen_model else None
        if spec and c.tier in sel_tiers and sel_tiers[c.tier].model_id != spec.id and not getattr(sel_tiers[c.tier], "_selected", False):
            sel_tiers[c.tier] = _spec_to_tier(c.tier, spec)
            object.__setattr__(sel_tiers[c.tier], "_selected", True) if False else None
    selected_estimate = estimate(p, cands[0].topology.id, sel_tiers)
    rec = Recommendation(p, cands, plan, frontier, fastest, accurate, _headline(p, cands[0], fastest, accurate), scan, selection, selected_estimate, tiers)
    if scan is not None and scan.current_topology not in ("none", cands[0].topology.id):
        cur = next((c for c in cands if c.topology.id == scan.current_topology), None)
        if cur is not None:
            rec.headline += (f" The repository currently implements **{cur.topology.name}** (score {cur.score:+.1f}, ~{cur.estimate.latency_s:.0f}s);"
                             f" the recommendation changes the topology.")
    elif scan is not None and scan.current_topology == cands[0].topology.id:
        rec.headline += " This matches the topology the repository already implements; focus on the cross-cutting recommendations."
    return rec


def _headline(p: WorkloadProfile, best: Candidate, fastest: Candidate | None, accurate: Candidate) -> str:
    t = best.topology
    parts = [f"Recommended: **{t.name}** (score {best.score:+.1f}; est. p50 latency ~{best.estimate.latency_s:.0f}s vs budget {p.latency_budget_s:.0f}s, ~{best.estimate.token_multiplier:.0f}x tokens of one call)."]
    ratio = best.estimate.latency_s / max(0.1, p.latency_budget_s)
    if best.latency_verdict in ("exceeds", "far over") and ratio <= 1.3:
        parts.append(f"It is marginally over budget (~{best.estimate.latency_s:.1f}s vs {p.latency_budget_s:.0f}s at list-price serving assumptions); streaming, prompt caching, a shorter output, or a smaller model closes the gap.")
    elif best.latency_verdict in ("exceeds", "far over"):
        if fastest:
            parts.append(f"It {best.latency_verdict} the latency budget; the fastest viable alternative within budget is **{fastest.topology.name}** (~{fastest.estimate.latency_s:.0f}s).")
        else:
            parts.append(f"It {best.latency_verdict} the latency budget and no viable topology fits it: relax the budget, cut tool calls/reading per request, use a smaller model, or move work off the request path.")
    if accurate.topology.id != t.id and accurate.quality_proxy > best.quality_proxy + 1.0:
        parts.append(f"If accuracy outweighs everything else, **{accurate.topology.name}** has the strongest structural fit but costs ~{accurate.estimate.latency_s:.0f}s and ~{accurate.estimate.token_multiplier:.0f}x tokens.")
    return " ".join(parts)
