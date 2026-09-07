"""Latency and cost estimates per topology.

These are order-of-magnitude heuristics, not benchmarks. Every number is
derived from a small set of published assumptions (model serving speeds,
Anthropic's reported token multipliers) plus the user's own profile, and the
breakdown is returned so it can be inspected and overridden.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .profile import WorkloadProfile
from .topologies import MODEL_TIERS, ModelTier

BASE_PROMPT_TOKENS = 3_000        # system prompt + tool schemas + user request
TOOL_CALL_OUTPUT_TOKENS = 150     # tokens the model emits to make one tool call
MAX_CONTEXT_READ = 150_000        # do not assume more than this is read in one context
MAX_PARALLEL_WORKERS = 10         # concurrent worker wave size

OUTPUT_TOKENS = {
    "short_answer": 300,
    "structured_data": 400,
    "long_document": 3_000,
    "code_change": 1_500,
    "action": 250,
}


@dataclass
class Call:
    tier: str
    input_tokens: float
    output_tokens: float
    label: str = ""

    @property
    def model(self) -> ModelTier:
        return MODEL_TIERS[self.tier]

    @property
    def latency_s(self) -> float:
        m = self.model
        return m.ttft_s + self.output_tokens / m.tokens_per_s

    @property
    def cost_usd(self) -> float:
        m = self.model
        return (self.input_tokens * m.input_price_per_mtok + self.output_tokens * m.output_price_per_mtok) / 1e6


@dataclass
class Segment:
    """A unit of work; `parallel` segments contribute their max to latency."""
    label: str
    calls: list[Call] = field(default_factory=list)
    tool_rounds: int = 0          # sequential tool round trips on this segment
    children: list["Segment"] = field(default_factory=list)
    parallel: bool = False        # children run concurrently
    waves: int = 1                # if parallel, number of sequential waves

    def latency(self, tool_latency_s: float) -> float:
        own = sum(c.latency_s for c in self.calls) + self.tool_rounds * tool_latency_s
        if not self.children:
            return own
        child = [c.latency(tool_latency_s) for c in self.children]
        if self.parallel:
            return own + max(child) * self.waves
        return own + sum(child)

    def cost(self) -> float:
        return sum(c.cost_usd for c in self.calls) + sum(c.cost() for c in self.children)

    def call_count(self) -> int:
        return len(self.calls) + sum(c.call_count() for c in self.children)

    def total_tokens(self) -> float:
        return sum(c.input_tokens + c.output_tokens for c in self.calls) + sum(c.total_tokens() for c in self.children)


@dataclass
class Estimate:
    topology_id: str
    latency_s: float
    cost_usd: float
    llm_calls: int
    total_tokens: float
    token_multiplier: float
    assumptions: list[str]
    tree: Segment


# ---------------------------------------------------------------- building blocks

OUTPUT_SCALE = {0: 0.25, 1: 0.6, 2: 1.0, 3: 1.3, 4: 1.6}


def _out_tokens(p: WorkloadProfile) -> int:
    return max(40, int(OUTPUT_TOKENS[p.output_type] * OUTPUT_SCALE[p.complexity_score]))


def pick_tier(p: WorkloadProfile, output_tokens: int | None = None, floor: str = "haiku") -> str:
    """Most capable tier whose single-call latency fits ~70% of the budget.

    Accuracy-critical or complex work refuses to drop below Sonnet; trivial work
    with a relaxed budget still gets Opus (quality first, speed only when forced).
    """
    out = output_tokens or _out_tokens(p)
    order = ["opus", "sonnet", "haiku"]
    if p.accuracy_priority >= 4 or p.complexity_score >= 2:
        floor = "sonnet" if order.index(floor) > order.index("sonnet") else floor
    for tier in order:
        m = MODEL_TIERS[tier]
        if m.ttft_s + out / m.tokens_per_s <= 0.7 * p.latency_budget_s or tier == floor:
            return tier
    return floor


def agent_tier(p: WorkloadProfile) -> str:
    """Tier for a tool-using agent loop: Opus unless the budget is interactive."""
    if p.latency_budget_s <= 3:
        return "haiku" if p.accuracy_priority <= 3 else "sonnet"
    if p.is_interactive:
        return "sonnet"
    return "opus"


def _read_tokens(p: WorkloadProfile, share: float = 1.0) -> float:
    return min(p.context_tokens_per_task * share, MAX_CONTEXT_READ)


def _single_call(p: WorkloadProfile, tier: str, label: str, read_share: float = 1.0, out: int | None = None) -> Segment:
    call = Call(tier, BASE_PROMPT_TOKENS + _read_tokens(p, read_share), out or _out_tokens(p), label)
    return Segment(label, calls=[call])


def _agent_loop(p: WorkloadProfile, tier: str, label: str, tool_calls: float, read_share: float = 1.0, out: int | None = None) -> Segment:
    """One agent iterating over `tool_calls` tool invocations."""
    if tool_calls <= 0:
        return _single_call(p, tier, label, read_share, out)
    batch = {"independent": 4.0, "mixed": 2.0, "sequential": 1.0}[p.tool_dependency]
    rounds = int(math.ceil(tool_calls / batch))
    reading = _read_tokens(p, read_share)
    per_round_results = reading / rounds
    calls: list[Call] = []
    accumulated = 0.0
    for i in range(rounds):
        calls.append(Call(tier, BASE_PROMPT_TOKENS + accumulated, TOOL_CALL_OUTPUT_TOKENS * min(batch, tool_calls - i * batch), f"{label}: tool round {i + 1}"))
        accumulated += per_round_results
    calls.append(Call(tier, BASE_PROMPT_TOKENS + accumulated, out or _out_tokens(p), f"{label}: final answer"))
    return Segment(label, calls=calls, tool_rounds=rounds)


def worker_count(p: WorkloadProfile) -> int:
    """How many subagents an orchestrator should spawn (Anthropic research-system heuristic:
    simple fact-finding 1, comparisons 2-4, complex research 10+; roster max 20)."""
    n = max(p.parallel_subtasks, p.knowledge_sources if p.retrieval_depth in ("multi_hop", "exhaustive") else 0, p.scope_breadth if p.scope_breadth >= 3 else 0)
    if p.task_complexity == "open_ended":
        n = max(n, 4)
    if p.retrieval_depth == "exhaustive":
        n = max(n, 5)
    if p.context_pressure in ("high", "extreme"):
        n = max(n, int(math.ceil(min(p.context_tokens_per_task, 2_000_000) / 100_000)))
    return max(2, min(n, 20))


# ---------------------------------------------------------------- per-topology estimators

def estimate(p: WorkloadProfile, topology_id: str) -> Estimate:
    notes: list[str] = []
    T = float(p.tool_calls_per_task)
    tl = p.tool_latency_s

    if topology_id == "single_call":
        tier = pick_tier(p)
        tree = _single_call(p, tier, "single call")
        notes.append(f"One {MODEL_TIERS[tier].model_id} call; retrieval (if any) done in code before the call.")

    elif topology_id == "single_agent":
        tree = _agent_loop(p, agent_tier(p), "agent", T)
        notes.append(f"{tree.tool_rounds} sequential tool round(s) for {int(T)} tool calls (batching by dependency={p.tool_dependency}).")

    elif topology_id == "prompt_chain":
        stages = 2 if p.complexity_score <= 1 else (3 if p.complexity_score == 2 else 4)
        segs = [_single_call(p, "opus" if i == stages - 1 else "sonnet", f"stage {i + 1}", read_share=1.0 / stages, out=(_out_tokens(p) if i == stages - 1 else 600)) for i in range(stages)]
        if T > 0:
            segs[1] = _agent_loop(p, "sonnet", "stage 2 (tools)", T, read_share=1.0 / stages, out=600)
        tree = Segment("chain", children=segs)
        notes.append(f"{stages} sequential stages with programmatic gates between them.")

    elif topology_id == "router":
        route = Segment("router", calls=[Call("haiku", BASE_PROMPT_TOKENS, 20, "route")])
        handler = _agent_loop(p, agent_tier(p), "specialist", T) if p.uses_tools else _single_call(p, pick_tier(p), "specialist")
        tree = Segment("router+handler", children=[route, handler])
        notes.append("Small-model router (~20 output tokens) then one specialist handler.")

    elif topology_id == "parallel_sectioning":
        branches = max(2, min(p.parallel_subtasks, 20))
        per_branch_calls = T / branches
        kids = [_agent_loop(p, "sonnet", f"section {i + 1}", per_branch_calls, read_share=1.0 / branches, out=500) for i in range(branches)]
        fan = Segment("fan-out", children=kids, parallel=True, waves=int(math.ceil(branches / MAX_PARALLEL_WORKERS)))
        synth = _single_call(p, "opus", "aggregate", read_share=0.0)
        synth.calls[0].input_tokens += 500 * branches
        tree = Segment("sectioning", children=[fan, synth])
        notes.append(f"{branches} code-defined branches run concurrently, then one aggregation call.")

    elif topology_id == "parallel_voting":
        votes = 5 if p.accuracy_priority >= 5 else 3
        vt = agent_tier(p) if p.uses_tools else pick_tier(p, _out_tokens(p) + 100)
        kids = [_agent_loop(p, vt, f"vote {i + 1}", T, out=_out_tokens(p) + 100) for i in range(votes)]
        discrete = p.output_type in ("short_answer", "structured_data")
        children = [Segment("votes", children=kids, parallel=True)]
        if not discrete:
            children.append(Segment("judge", calls=[Call("opus", BASE_PROMPT_TOKENS + votes * (_out_tokens(p) + 100), _out_tokens(p), "judge/merge")]))
        tree = Segment("voting", children=children)
        notes.append(f"{votes} parallel {MODEL_TIERS[vt].model_id} samples; " + ("majority vote in code (no judge call)." if discrete else "one Opus judge/merge call."))

    elif topology_id == "evaluator_optimizer":
        iters = 3 if p.accuracy_priority >= 5 else 2
        segs = []
        for i in range(iters):
            gen = _agent_loop(p, agent_tier(p), f"generate {i + 1}", T if i == 0 else T * 0.3, read_share=1.0 if i == 0 else 0.2)
            ev = Segment(f"evaluate {i + 1}", calls=[Call("opus", BASE_PROMPT_TOKENS + _out_tokens(p), 400, "evaluate")])
            ev.tool_rounds = 1 if p.verifiability == "strong" else 0
            segs += [gen, ev]
        tree = Segment("evaluator-optimizer", children=segs)
        notes.append(f"{iters} generate/evaluate iterations (worst case); most requests exit after the first accepted evaluation.")

    elif topology_id == "orchestrator_workers":
        n = worker_count(p)
        plan = Segment("plan", calls=[Call("opus", BASE_PROMPT_TOKENS, 800, "orchestrator plans & briefs workers")])
        per_worker_calls = max(3.0, T / n) if p.uses_tools or p.retrieval_depth != "none" else 0.0
        kids = [_agent_loop(p, "sonnet", f"worker {i + 1}", per_worker_calls, read_share=1.0 / n, out=700) for i in range(n)]
        fan = Segment("workers", children=kids, parallel=True, waves=int(math.ceil(n / MAX_PARALLEL_WORKERS)))
        synth = Segment("synthesis", calls=[Call("opus", BASE_PROMPT_TOKENS + 700 * n, _out_tokens(p) + 400, "orchestrator verifies & synthesises")])
        tree = Segment("orchestrator-workers", children=[plan, fan, synth])
        notes.append(f"{n} Sonnet-tier workers in {fan.waves} wave(s) of <= {MAX_PARALLEL_WORKERS}, each with ~{per_worker_calls:.0f} tool calls; Opus-tier lead plans and synthesises.")

    elif topology_id == "hierarchical":
        leads = max(2, min(p.scope_breadth, 6))
        n = worker_count(p)
        per_lead_workers = max(2, int(math.ceil(n / leads)))
        per_worker_calls = max(3.0, T / max(n, 1))
        lead_segs = []
        for j in range(leads):
            kids = [_agent_loop(p, "sonnet", f"lead {j + 1} worker {i + 1}", per_worker_calls, read_share=1.0 / (leads * per_lead_workers), out=700) for i in range(per_lead_workers)]
            lead_segs.append(Segment(f"lead {j + 1}", children=[
                Segment("lead plan", calls=[Call("opus", BASE_PROMPT_TOKENS, 600, "lead plans")]),
                Segment("lead workers", children=kids, parallel=True),
                Segment("lead synth", calls=[Call("opus", BASE_PROMPT_TOKENS + 700 * per_lead_workers, 800, "lead synthesises")]),
            ]))
        tree = Segment("hierarchical", children=[
            Segment("top plan", calls=[Call("opus", BASE_PROMPT_TOKENS, 800, "top orchestrator plans")]),
            Segment("leads", children=lead_segs, parallel=True),
            Segment("top synth", calls=[Call("opus", BASE_PROMPT_TOKENS + 800 * leads, _out_tokens(p) + 400, "top orchestrator synthesises")]),
        ])
        notes.append(f"{leads} leads x {per_lead_workers} workers; two delegation levels add two extra plan/synthesis hops.")

    elif topology_id == "handoff_network":
        at = agent_tier(p)
        agent = _agent_loop(p, at, "specialist A", T * 0.6)
        handoff = Segment("handoff", calls=[Call(at, BASE_PROMPT_TOKENS, 100, "transfer")])
        agent_b = _agent_loop(p, at, "specialist B", T * 0.4, read_share=0.4)
        tree = Segment("handoffs", children=[agent, handoff, agent_b])
        notes.append("One handoff per request assumed (specialist A -> B); each handoff re-briefs the next agent.")

    else:
        raise KeyError(topology_id)

    base = Call("opus", BASE_PROMPT_TOKENS + _read_tokens(p), _out_tokens(p)).input_tokens + _out_tokens(p)
    total = tree.total_tokens()
    return Estimate(
        topology_id=topology_id,
        latency_s=round(tree.latency(tl), 1),
        cost_usd=round(tree.cost(), 4),
        llm_calls=tree.call_count(),
        total_tokens=round(total),
        token_multiplier=round(total / base, 1),
        assumptions=notes,
        tree=tree,
    )
