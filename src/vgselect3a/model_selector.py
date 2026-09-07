"""Match each role's requirements against the model catalog.

    selection = select_models(plan, profile, catalog, policy)

Steps per role: hard filters -> capability floor (measured evidence overrides
the tier when present) -> score (quality, latency against the role's share,
cost weighted by the role's volume) -> cross-role constraints (orchestrator at
least as capable as workers, independent verifier, one model per loop/group,
family consistency) -> fallback (prefer another provider) -> warnings that feed
back to the topology decision when a role cannot be staffed.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field, asdict
from typing import Any

from .catalog import Catalog, ModelSpec
from .decomposition import Plan
from .profile import WorkloadProfile
from .requirements import RoleRequirements, derive_requirements


@dataclass
class SelectionPolicy:
    allowed_providers: list[str] | None = None
    blocked_providers: list[str] = field(default_factory=list)
    allowed_platforms: list[str] | None = None
    regions: list[str] | None = None            # model must serve at least one
    require_verified: bool = True               # exclude illustrative (placeholder) entries until their numbers are verified
    require_approved: bool = True
    prefer_provider: str | None = None
    family_consistency_bonus: float = 0.25
    deprecation_horizon_days: int = 180
    max_alternatives: int = 4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "SelectionPolicy":
        d = d or {}
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Rejection:
    model_id: str
    reason: str


@dataclass
class Scored:
    model_id: str
    score: float
    quality: float
    latency_adj: float
    cost_adj: float
    est_latency_s: float
    est_cost_per_call: float
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoleChoice:
    component_id: str
    role_type: str
    requirements: RoleRequirements
    model_id: str | None
    effort: str
    fallback_model_id: str | None
    score: float | None
    est_latency_s: float | None
    est_cost_per_call: float | None
    est_cost_per_day: float | None
    rationale: list[str]
    alternatives: list[Scored]
    rejected: list[Rejection]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["requirements"] = self.requirements.to_dict()
        return d


@dataclass
class Selection:
    policy: SelectionPolicy
    catalog_name: str
    choices: list[RoleChoice]
    warnings: list[str]
    unfilled: list[str]
    providers_used: list[str]
    families_used: list[str]
    est_cost_per_day: float          # sum of per-role call costs x calls/day (roles priced independently)

    def choice(self, component_id: str) -> RoleChoice | None:
        return next((c for c in self.choices if c.component_id == component_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy.to_dict(), "catalog": self.catalog_name,
            "choices": [c.to_dict() for c in self.choices], "warnings": self.warnings, "unfilled": self.unfilled,
            "providers_used": self.providers_used, "families_used": self.families_used,
            "est_cost_per_day": round(self.est_cost_per_day, 2),
        }


# ---------------------------------------------------------------- filters

def hard_filter(m: ModelSpec, r: RoleRequirements, policy: SelectionPolicy, tool_latency_s: float) -> str | None:
    """Return a rejection reason, or None if the model may serve the role."""
    if policy.require_approved and not m.approved:
        return "not approved by the platform team"
    if policy.allowed_providers and m.provider not in policy.allowed_providers:
        return f"provider {m.provider} not in allowed providers"
    if m.provider in policy.blocked_providers:
        return f"provider {m.provider} is blocked"
    if policy.allowed_platforms and not set(m.platforms) & set(policy.allowed_platforms):
        return "not available on an allowed platform"
    if policy.regions and not set(m.regions) & set(policy.regions):
        return f"not served in {', '.join(policy.regions)}"
    if policy.require_verified and m.illustrative:
        return "illustrative catalog entry: verify its numbers (set illustrative=false) or set policy.require_verified=false"
    if r.data_class not in m.data_classes:
        return f"not cleared for {r.data_class} data"
    if m.context_window < r.context_tokens:
        return f"context window {m.context_window:,} < required {r.context_tokens:,}"
    if m.max_output < r.output_tokens:
        return f"max output {m.max_output:,} < required {r.output_tokens:,}"
    if r.needs_tools and m.tool_use < 1:
        return "no tool use"
    if r.needs_tools and r.tool_count >= 10 and m.tool_use < 2:
        return "tool use not reliable enough for a large tool set"
    if r.needs_structured_output and not m.structured_output:
        return "no structured output"
    if r.needs_strict_schema and not m.strict_schema:
        return "no strict schema enforcement (high-stakes structured output)"
    missing = [x for x in r.modalities if x not in m.modalities]
    if missing:
        return f"missing modality {', '.join(missing)}"
    if m.deprecation_date:
        try:
            dep = _dt.date.fromisoformat(m.deprecation_date)
            if dep <= _dt.date.today():
                return f"deprecated on {m.deprecation_date}"
        except ValueError:
            pass
    if m.reasoning_tier < r.reasoning_level:
        ev = m.evidence.get(r.task_family)
        if ev is None or ev < 0.8:
            return f"capability tier {m.reasoning_tier} below required {r.reasoning_level}" + ("" if ev is None else f" and measured {r.task_family} accuracy {ev:.0%} < 80%")
    # concurrency: parallel workers all fire at once
    if m.max_concurrency is not None and r.role_type == "worker" and r.cache_group and m.max_concurrency < 2:
        return "concurrency limit too low for parallel workers"
    return None


# ---------------------------------------------------------------- scoring

def role_latency(m: ModelSpec, r: RoleRequirements, tool_latency_s: float) -> float:
    """Tool rounds (short tool-call outputs) plus the final answer, plus tool time."""
    return r.tool_rounds * (m.call_latency_s(150) + tool_latency_s) + m.call_latency_s(r.output_tokens)


def role_cost(m: ModelSpec, r: RoleRequirements) -> float:
    return r.tool_rounds * m.call_cost_usd(r.context_tokens, 150) + m.call_cost_usd(r.context_tokens, r.output_tokens)


def score_model(m: ModelSpec, r: RoleRequirements, p: WorkloadProfile, policy: SelectionPolicy, cheapest: float, lead_family: str | None) -> Scored:
    notes: list[str] = []
    # quality: capability margin, evidence, over-provisioning
    margin = m.reasoning_tier - r.reasoning_level
    quality = 1.0 + 0.15 * max(0, margin) * (r.stakes / 3.0)
    if margin > 1 and p.cost_sensitivity >= 4 and r.stakes <= 3:
        quality -= 0.1 * (margin - 1)
        notes.append("over-provisioned for a low-stakes role under cost pressure")
    ev = m.evidence.get(r.task_family)
    if ev is not None:
        quality += (ev - 0.6) * 2.0
        notes.append(f"measured {r.task_family} accuracy {ev:.0%}")
    if r.needs_tools and r.needs_parallel_tools and m.tool_use >= 3:
        quality += 0.15
    if r.needs_strict_schema and m.strict_schema:
        quality += 0.1
    if m.effort_control and r.effort_hint in ("high", "xhigh", "max"):
        quality += 0.1
    if m.illustrative:
        quality -= 0.1
        notes.append("illustrative catalog entry: verify numbers")
    if m.deprecation_date:
        try:
            days = (_dt.date.fromisoformat(m.deprecation_date) - _dt.date.today()).days
            if days < policy.deprecation_horizon_days:
                quality -= 0.3
                notes.append(f"deprecated in {days} days")
        except ValueError:
            pass
    # latency vs the role's share
    est = role_latency(m, r, p.tool_latency_s)
    ratio = est / max(0.1, r.latency_share_s)
    if ratio <= 0.7:
        lat = 0.3
    elif ratio <= 1.0:
        lat = 0.3 - (ratio - 0.7)
    elif ratio <= 2.0:
        lat = -0.5 - (ratio - 1.0) * 1.5
    else:
        lat = -2.0 - min(2.0, math.log2(ratio))
    tolerance = max(0.4, min(1.6, 1.0 + 0.3 * (3 - p.accuracy_priority)))
    if lat < 0:
        lat *= tolerance
    # cost vs cheapest passing model, weighted by volume
    cost = role_cost(m, r)
    vol_w = max(0.3, min(1.5, math.log10(max(10.0, r.calls_per_day)) / 5.0))
    cost_adj = -(p.cost_sensitivity / 3.0) * 0.5 * vol_w * math.log2(max(1.0, cost / max(cheapest, 1e-6)))
    # consistency
    if lead_family and m.family == lead_family:
        quality += policy.family_consistency_bonus
    if policy.prefer_provider and m.provider == policy.prefer_provider:
        quality += 0.2
    return Scored(m.id, round(quality + lat + cost_adj, 3), round(quality, 3), round(lat, 3), round(cost_adj, 3), round(est, 1), round(cost, 5), notes)


# ---------------------------------------------------------------- selection

def _pick(r: RoleRequirements, p: WorkloadProfile, catalog: Catalog, policy: SelectionPolicy, lead_family: str | None, min_tier: int = 1) -> tuple[list[Scored], list[Rejection]]:
    passing: list[ModelSpec] = []
    rejected: list[Rejection] = []
    for m in catalog.models:
        why = hard_filter(m, r, policy, p.tool_latency_s)
        if why is None and m.reasoning_tier < min_tier:
            why = f"must be at least tier {min_tier} to orchestrate its workers"
        if why:
            rejected.append(Rejection(m.id, why))
        else:
            passing.append(m)
    if not passing:
        return [], rejected
    cheapest = min(role_cost(m, r) for m in passing)
    scored = sorted((score_model(m, r, p, policy, cheapest, lead_family) for m in passing), key=lambda s: -s.score)
    return scored, rejected


def select_models(plan: Plan, p: WorkloadProfile, catalog: Catalog | None = None, policy: SelectionPolicy | None = None) -> Selection:
    catalog = catalog or Catalog.default()
    policy = policy or SelectionPolicy()
    reqs = derive_requirements(p, plan)
    by_id = {r.component_id: r for r in reqs}
    choices: dict[str, RoleChoice] = {}
    warnings: list[str] = []

    # 1. orchestrators first (floor = the strongest requirement among the roles they brief), then everyone else
    order = sorted(reqs, key=lambda r: 0 if r.role_type == "orchestrator" else 1)
    staffed_levels = [r.reasoning_level for r in reqs if r.role_type in ("worker", "reader", "handler", "specialist", "evaluator")]
    lead_family: str | None = None
    group_choice: dict[str, str] = {}
    for r in order:
        min_tier = max(staffed_levels) if r.role_type == "orchestrator" and staffed_levels else 1
        scored, rejected = _pick(r, p, catalog, policy, lead_family, min_tier)
        if r.cache_group and r.cache_group in group_choice and any(s.model_id == group_choice[r.cache_group] for s in scored):
            top = next(s for s in scored if s.model_id == group_choice[r.cache_group])
            rationale = [f"Same model as the rest of group '{r.cache_group}' to keep one prompt cache and one behaviour."]
        elif scored:
            top = scored[0]
            rationale = []
            if r.cache_group:
                group_choice[r.cache_group] = top.model_id
        else:
            choices[r.component_id] = RoleChoice(r.component_id, r.role_type, r, None, "n/a", None, None, None, None, None,
                                                 ["No catalog model passes the hard filters for this role."], [], rejected)
            continue
        m = catalog.get(top.model_id)
        effort = r.effort_hint if m.effort_control else "n/a"
        rationale.append(f"Tier {m.reasoning_tier} vs required {r.reasoning_level}; est. {top.est_latency_s:.1f}s of a {r.latency_share_s:.1f}s share; ${top.est_cost_per_call:.4f} per call.")
        rationale += top.notes
        if r.role_type == "orchestrator" and min_tier > 1:
            rationale.append(f"Floor raised to tier {min_tier}: the orchestrator must be at least as capable as its workers.")
            lead_family = m.family
        alts = [s for s in scored[1:policy.max_alternatives + 1]]
        fallback = next((s.model_id for s in scored[1:] if catalog.get(s.model_id).provider != m.provider), None) or (scored[1].model_id if len(scored) > 1 else None)
        if fallback and catalog.get(fallback).provider != m.provider:
            rationale.append(f"Fallback {fallback} is on a different provider for outage/refusal resilience.")
        choices[r.component_id] = RoleChoice(r.component_id, r.role_type, r, m.id, effort, fallback, top.score, top.est_latency_s, top.est_cost_per_call,
                                             round(top.est_cost_per_call * r.calls_per_day, 2), rationale, alts, rejected)
        if m.illustrative:
            warnings.append(f"{r.component_id}: chosen model '{m.id}' is an illustrative catalog entry; replace its numbers from your registry before relying on the estimate.")
        if top.est_latency_s > r.latency_share_s * 1.5:
            warnings.append(f"{r.component_id}: even the best model ({m.id}) needs ~{top.est_latency_s:.0f}s against a {r.latency_share_s:.0f}s share; shrink the role or revisit the topology/budget.")

    # 2. orchestrator must not be weaker than any staffed model (evidence can lift a lower-tier worker above the lead)
    for r in reqs:
        if r.role_type != "orchestrator" or not choices.get(r.component_id) or not choices[r.component_id].model_id:
            continue
        lead = choices[r.component_id]
        strongest = max((catalog.get(c.model_id).reasoning_tier for c in choices.values() if c.model_id and c.role_type != "orchestrator"), default=1)
        if catalog.get(lead.model_id).reasoning_tier < strongest:
            scored, rejected = _pick(r, p, catalog, policy, None, strongest)
            if scored:
                top = scored[0]; mm = catalog.get(top.model_id)
                lead.rationale.append(f"Re-selected {mm.id}: a staffed model is tier {strongest}, so the orchestrator was raised to match.")
                lead.model_id, lead.score, lead.est_latency_s, lead.est_cost_per_call = mm.id, top.score, top.est_latency_s, top.est_cost_per_call
                lead.est_cost_per_day = round(top.est_cost_per_call * r.calls_per_day, 2)
                lead.effort = r.effort_hint if mm.effort_control else "n/a"
                lead.alternatives, lead.rejected = scored[1:policy.max_alternatives + 1], rejected

    # 3. independence of verifiers/judges
    for r in reqs:
        c = choices.get(r.component_id)
        if not c or not r.independent_of or not c.model_id:
            continue
        other = choices.get(r.independent_of)
        if other and other.model_id == c.model_id:
            alt = next((a for a in c.alternatives if catalog.get(a.model_id).family != catalog.get(c.model_id).family and a.score >= (c.score or 0) - 1.0), None)
            if alt:
                c.rationale.append(f"Switched from {c.model_id} to {alt.model_id} so the verifier is independent of '{r.independent_of}'.")
                c.model_id, c.score, c.est_latency_s, c.est_cost_per_call = alt.model_id, alt.score, alt.est_latency_s, alt.est_cost_per_call
                c.est_cost_per_day = round(alt.est_cost_per_call * r.calls_per_day, 2)
                c.effort = r.effort_hint if catalog.get(alt.model_id).effort_control else "n/a"
            else:
                warnings.append(f"{r.component_id}: same model as '{r.independent_of}'; no independent alternative within 1.0 score. Vary the prompt/temperature and add a code check.")

    ordered = [choices[r.component_id] for r in reqs]
    unfilled = [c.component_id for c in ordered if not c.model_id]
    for u in unfilled:
        warnings.append(f"{u}: no model in the catalog satisfies this role under the current policy; see rejected reasons.")
    used = [catalog.get(c.model_id) for c in ordered if c.model_id]
    return Selection(policy, catalog.name, ordered, warnings, unfilled, sorted({m.provider for m in used}), sorted({m.family for m in used}),
                     sum(c.est_cost_per_day or 0 for c in ordered))
