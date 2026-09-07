"""Per-role requirements derived from the plan and profile.

The selector matches these against the model catalog. Nothing here is asked
from the user; everything is derived from the workload profile, the topology
and the role a component plays.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any

from .decomposition import Component, Plan
from .estimator import BASE_PROMPT_TOKENS, MAX_CONTEXT_READ, OUTPUT_SCALE, OUTPUT_TOKENS, worker_count
from .profile import WorkloadProfile

ROLE_TYPES = ("orchestrator", "synthesizer", "responder", "single_agent", "worker", "reader", "router", "evaluator", "coder", "handler", "specialist", "stage", "code")


@dataclass
class RoleRequirements:
    component_id: str
    role_type: str
    reasoning_level: int            # 1..5 required capability
    context_tokens: int             # tokens the role must hold per call
    output_tokens: int
    needs_tools: bool
    tool_count: int
    needs_parallel_tools: bool
    needs_structured_output: bool
    needs_strict_schema: bool
    latency_share_s: float          # share of the end-to-end budget allotted to this role
    tool_rounds: int                # sequential tool round trips inside the role
    stakes: int                     # 1..5 error cost for this role
    calls_per_day: float
    data_class: str
    modalities: list[str]
    task_family: str
    effort_hint: str
    independent_of: str | None = None   # component whose model this role should differ from (verification independence)
    cache_group: str | None = None      # components sharing a loop should share a model
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _role_type(c: Component, topology_id: str) -> str:
    cid = c.id
    if c.tier == "code":
        return "code"
    if cid in ("lead", "top") or cid.startswith("lead_") and "_w" not in cid:
        return "orchestrator"
    if cid == "llm":
        return "responder"
    if cid in ("merge", "judge", "synth", "polish", "finalize", "solve", "review"):
        return "synthesizer"
    if cid == "agent":
        return "coder" if topology_id == "single_agent" and c.tools and "edit" in c.tools else "single_agent"
    if cid == "explorer":
        return "reader"
    if cid == "router":
        return "router"
    if cid in ("critic", "evaluator"):
        return "evaluator"
    if cid.startswith("worker_") or "_w" in cid:
        return "worker"
    if cid.startswith("section_") or cid.startswith("vote_"):
        return "worker"
    if cid.startswith("handler_"):
        return "handler"
    if cid.startswith("spec_"):
        return "specialist"
    if cid == "generator":
        return "single_agent"
    return "stage"


def _task_family(p: WorkloadProfile, role: str) -> str:
    if role == "router":
        return "classification"
    if role == "evaluator":
        return "evaluation"
    if role == "orchestrator":
        return "planning"
    if p.output_type == "code_change":
        return "coding"
    if p.complexity_score <= 1 and p.output_type in ("short_answer", "structured_data") and role in ("responder", "stage", "worker"):
        return "classification"
    if p.output_type == "structured_data":
        return "extraction"
    if p.retrieval_depth in ("multi_hop", "exhaustive") and role in ("worker", "reader"):
        return "research"
    if p.output_type == "long_document" and role in ("synthesizer", "stage", "single_agent"):
        return "writing"
    if p.interaction == "multi_turn" and role in ("handler", "specialist", "single_agent"):
        return "conversation"
    return "general"


def _reasoning_level(p: WorkloadProfile, role: str) -> int:
    c = p.complexity_score
    a = p.accuracy_priority
    if role == "orchestrator":
        lvl = max(3, c + 2)
    elif role == "synthesizer":
        lvl = max(3, c + 1)
    elif role in ("single_agent", "coder", "handler", "specialist"):
        lvl = max(2, c + 2)
    elif role == "responder":
        lvl = max(2, c + 1) + (1 if a >= 4 else 0)
    elif role == "worker":
        lvl = {0: 2, 1: 2, 2: 3, 3: 3, 4: 4}[c] + (1 if a >= 5 else 0)
        lvl = min(lvl, 4)
    elif role == "reader":
        lvl = 2 if c <= 2 else 3
    elif role == "router":
        lvl = 2 if p.scope_breadth >= 4 else 1
    elif role == "evaluator":
        lvl = 5 if a >= 4 else max(3, c + 1)
    elif role == "stage":
        lvl = max(2, c + 1)
    else:
        lvl = 1
    return max(1, min(5, lvl))


def _effort(p: WorkloadProfile, role: str, level: int) -> str:
    if role == "code":
        return "n/a"
    if role in ("router", "reader"):
        return "low"
    if role == "worker":
        return "medium" if p.accuracy_priority >= 4 else "low"
    if p.accuracy_priority >= 5 and role in ("orchestrator", "evaluator", "synthesizer", "responder", "single_agent", "coder"):
        return "max"
    if level >= 5 or p.complexity_score >= 3:
        return "xhigh"
    return "high"


def _latency_shares(p: WorkloadProfile, plan: Plan) -> dict[str, float]:
    """Fraction of the end-to-end budget allotted to each component (critical-path aware)."""
    B = p.latency_budget_s
    t = plan.topology_id
    share: dict[str, float] = {}
    for c in plan.components:
        cid = c.id
        if t == "single_call":
            share[cid] = 0.9 if cid == "llm" else 0.1
        elif t == "single_agent":
            share[cid] = 1.0 if cid == "agent" else 0.5
        elif t == "prompt_chain":
            n = max(1, len([x for x in plan.components if x.tier != "code"]))
            share[cid] = 1.0 / n if c.tier != "code" else 0.02
        elif t == "router":
            share[cid] = min(1.5 / B, 0.12) if cid == "router" else 0.85
        elif t == "parallel_sectioning":
            share[cid] = 0.25 if cid == "merge" else (0.02 if cid == "split" else 0.6)
        elif t == "parallel_voting":
            share[cid] = 0.25 if cid == "judge" else 0.7
        elif t == "evaluator_optimizer":
            share[cid] = 0.35 if cid == "generator" else 0.15
        elif t == "orchestrator_workers":
            share[cid] = 0.3 if cid == "lead" else (0.15 if cid == "critic" else 0.55)
        elif t == "hierarchical":
            share[cid] = 0.2 if cid == "top" else (0.25 if "_w" not in cid else 0.45)
        elif t == "handoff_network":
            share[cid] = 0.45
        else:
            share[cid] = 0.5
    return {k: round(v * B, 2) for k, v in share.items()}


def derive_requirements(p: WorkloadProfile, plan: Plan) -> list[RoleRequirements]:
    t = plan.topology_id
    shares = _latency_shares(p, plan)
    out_base = int(OUTPUT_TOKENS[p.output_type] * OUTPUT_SCALE[p.complexity_score])
    comps = plan.components
    n_workers = len([c for c in comps if c.parallel_group in ("workers", "fanout", "votes")]) or 1
    reqs: list[RoleRequirements] = []
    for c in comps:
        role = _role_type(c, t)
        if role == "code":
            continue
        level = _reasoning_level(p, role)
        # reading share and tool share per role
        if role in ("worker", "reader"):
            read = min(p.context_tokens_per_task / n_workers, MAX_CONTEXT_READ)
            tool_calls = max(3.0, p.tool_calls_per_task / n_workers) if (p.uses_tools or p.retrieval_depth != "none") else 0.0
            out = 700
        elif role == "router":
            read, tool_calls, out = 0, 0.0, 30
        elif role == "orchestrator":
            read, tool_calls, out = 700 * n_workers, 0.0, max(800, out_base + 400)
        elif role == "evaluator":
            read, tool_calls, out = out_base, (1.0 if p.verifiability == "strong" else 0.0), 400
        elif role == "synthesizer":
            read, tool_calls, out = min(p.context_tokens_per_task * 0.3, MAX_CONTEXT_READ), 0.0, out_base
        elif role == "responder":
            read, tool_calls, out = min(p.context_tokens_per_task, MAX_CONTEXT_READ), 0.0, out_base
        elif role in ("handler", "specialist"):
            read, tool_calls, out = min(p.context_tokens_per_task, MAX_CONTEXT_READ), float(p.tool_calls_per_task) * (0.6 if role == "specialist" else 1.0), out_base
        else:  # single_agent, coder, stage
            read, tool_calls, out = min(p.context_tokens_per_task, MAX_CONTEXT_READ), float(p.tool_calls_per_task), out_base
        batch = {"independent": 4.0, "mixed": 2.0, "sequential": 1.0}[p.tool_dependency]
        rounds = int(math.ceil(tool_calls / batch)) if tool_calls > 0 else 0
        needs_tools = tool_calls > 0
        needs_structured = role in ("router", "evaluator") or p.output_type == "structured_data" and role in ("stage", "synthesizer", "single_agent")
        multiplicity = {"evaluator": 2.0, "worker": 1.0}.get(role, 1.0)
        iterations = 2.0 if t == "evaluator_optimizer" and role in ("single_agent", "evaluator") else 1.0
        calls_per_day = p.requests_per_day * multiplicity * iterations * max(1, rounds + 1)
        stakes = p.accuracy_priority if role in ("orchestrator", "evaluator", "synthesizer", "responder", "single_agent", "coder", "handler", "specialist") else max(1, p.accuracy_priority - 1)
        if p.tool_side_effects == "irreversible" and role in ("single_agent", "handler", "specialist", "coder"):
            stakes = max(stakes, 4)
        modalities = list(p.extra.get("modalities", ["text"])) if isinstance(p.extra.get("modalities"), list) else ["text"]
        independent_of = None
        if c.id == "critic":
            independent_of = "lead"
        elif c.id == "evaluator":
            independent_of = "generator"
        elif c.id == "judge":
            independent_of = "vote_1"
        cache_group = c.parallel_group or ("loop" if t in ("single_agent", "evaluator_optimizer") and role != "evaluator" else None)
        notes = []
        if role == "router":
            notes.append("Must answer in well under a second; structured output; smallest capable model.")
        if role == "orchestrator":
            notes.append("Must be at least as capable as any worker it briefs and verifies.")
        if independent_of:
            notes.append(f"Prefer a different model or family from '{independent_of}' for independent verification.")
        reqs.append(RoleRequirements(
            component_id=c.id, role_type=role, reasoning_level=level,
            context_tokens=int(BASE_PROMPT_TOKENS + read + 150 * p.tool_count), output_tokens=int(out),
            needs_tools=needs_tools, tool_count=p.tool_count if needs_tools else 0,
            needs_parallel_tools=needs_tools and p.tool_dependency != "sequential",
            needs_structured_output=needs_structured, needs_strict_schema=needs_structured and p.accuracy_priority >= 4,
            latency_share_s=shares.get(c.id, p.latency_budget_s * 0.5), tool_rounds=rounds,
            stakes=int(stakes), calls_per_day=float(calls_per_day), data_class=p.data_sensitivity,
            modalities=modalities, task_family=_task_family(p, role), effort_hint=_effort(p, role, level),
            independent_of=independent_of, cache_group=cache_group, notes=notes,
        ))
    return reqs
