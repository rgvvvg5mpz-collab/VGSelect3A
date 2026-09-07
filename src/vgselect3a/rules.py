"""Scoring rules: each rule looks at the profile and adds/subtracts fit for one
or more topologies, recording a rationale and a citation key.

Citation keys map to docs/industry_guidance.md:
  ANTHROPIC_BEA   Anthropic, "Building effective agents"
  ANTHROPIC_MAR   Anthropic, "How we built our multi-agent research system"
  ANTHROPIC_CTX   Anthropic, "Effective context engineering for AI agents"
  ANTHROPIC_MA    Anthropic Managed Agents multiagent guidance
  OPENAI_PG       OpenAI, "A practical guide to building agents"
  COGNITION       Cognition, "Don't build multi-agents"
  MAST            Cemri et al., "Why do multi-agent LLM systems fail?"
  LANGGRAPH       LangGraph multi-agent concepts
  GOOGLE_ADK      Google ADK multi-agent patterns
  MS_AF           Microsoft Azure / Agent Framework orchestration patterns
  SCALING         Google/MIT, "Towards a Science of Scaling Agent Systems"
  RAG             Agentic vs classic RAG sources (see docs)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .profile import WorkloadProfile


@dataclass(frozen=True)
class Signal:
    rule_id: str
    topology_id: str
    delta: float
    rationale: str
    citation: str


Rule = Callable[[WorkloadProfile], list[Signal]]
_RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    _RULES.append(fn)
    return fn


def _sig(rule_id: str, topo: str, delta: float, why: str, cite: str) -> Signal:
    return Signal(rule_id, topo, delta, why, cite)


# ---------------------------------------------------------------- simplicity first

@rule
def simplest_thing_that_works(p: WorkloadProfile) -> list[Signal]:
    out: list[Signal] = []
    c = p.complexity_score
    if c <= 1 and not p.uses_tools:
        out.append(_sig("R01", "single_call", +3.0, "Trivial/simple task with no tools: one optimised call is the right starting point.", "ANTHROPIC_BEA"))
        out.append(_sig("R01", "single_agent", -1.0, "No tools to loop over.", "ANTHROPIC_BEA"))
    if c <= 1 and p.uses_tools:
        out.append(_sig("R01b", "single_agent", +2.0, "Simple task with a few tools: a single agent loop is enough.", "OPENAI_PG"))
    if c <= 2:
        for t in ("orchestrator_workers", "hierarchical"):
            out.append(_sig("R02", t, -3.0, "Multi-agent coordination is not justified below complex/open-ended tasks; it costs ~15x tokens and adds failure modes.", "ANTHROPIC_MAR"))
    return out


@rule
def workflow_vs_agent(p: WorkloadProfile) -> list[Signal]:
    out: list[Signal] = []
    c = p.complexity_score
    if p.steps_predictable and c >= 2:
        out.append(_sig("R03", "prompt_chain", +2.5, "Steps are predictable: a code-defined chain with gates beats an agent deciding the path (more predictable, cheaper, easier to test).", "ANTHROPIC_BEA"))
        out.append(_sig("R03", "single_agent", -0.5, "Predictable steps do not need run-time planning.", "ANTHROPIC_BEA"))
        out.append(_sig("R03", "orchestrator_workers", -1.0, "Dynamic decomposition adds nothing when sub-tasks are known in advance; prefer code-defined parallel sectioning.", "ANTHROPIC_BEA"))
    if not p.steps_predictable:
        out.append(_sig("R04", "single_agent", +2.0, "Unpredictable path: the model must choose steps at run time, which is the definition of an agent.", "ANTHROPIC_BEA"))
        out.append(_sig("R04", "prompt_chain", -2.0, "A fixed chain cannot handle a path that varies per request.", "ANTHROPIC_BEA"))
        if c >= 3:
            out.append(_sig("R04b", "orchestrator_workers", +1.5, "Complex and unpredictable: a lead agent that plans and delegates handles sub-tasks that cannot be enumerated ahead of time.", "ANTHROPIC_BEA"))
    if p.task_complexity == "open_ended":
        out.append(_sig("R05", "orchestrator_workers", +2.0, "Open-ended problems are where multi-agent systems earn their cost: the number of steps cannot be predicted and paths must be explored.", "ANTHROPIC_MAR"))
        out.append(_sig("R05", "single_call", -3.0, "One call cannot explore an open-ended problem.", "ANTHROPIC_BEA"))
    return out


# ---------------------------------------------------------------- parallelism & breadth

@rule
def parallelism(p: WorkloadProfile) -> list[Signal]:
    out: list[Signal] = []
    n = p.parallel_subtasks
    if n >= 2:
        strength = min(3.0, 1.0 + 0.4 * n)
        if p.steps_predictable:
            out.append(_sig("R06", "parallel_sectioning", +strength, f"~{n} independent sub-tasks known in advance: fan them out in code and run concurrently; wall-clock ~ slowest branch.", "ANTHROPIC_BEA"))
            out.append(_sig("R06", "orchestrator_workers", +strength * 0.5, "Independent sub-tasks also suit dynamic subagents, but code-defined fan-out is cheaper when the split is known.", "ANTHROPIC_BEA"))
        else:
            out.append(_sig("R06b", "orchestrator_workers", +strength, f"~{n} independent sub-tasks discovered at run time: orchestrator spawns parallel subagents, each in its own context.", "ANTHROPIC_MAR"))
            out.append(_sig("R06b", "parallel_sectioning", +strength * 0.4, "Some of the fan-out can still be code-defined if a stable first split exists.", "ANTHROPIC_BEA"))
        out.append(_sig("R06c", "single_agent", -min(2.5, 0.5 * n), "A single agent serialises independent work, so latency grows with the number of sub-tasks.", "ANTHROPIC_MAR"))
    if n >= 8:
        out.append(_sig("R07", "hierarchical", +1.5, "Many parallel sub-tasks strain one orchestrator's roster and context; a second level of leads can absorb them.", "LANGGRAPH"))
    return out


@rule
def breadth_of_scope(p: WorkloadProfile) -> list[Signal]:
    out: list[Signal] = []
    b = p.scope_breadth
    if b >= 2:
        out.append(_sig("R08", "router", +1.5 + 0.3 * min(b, 6), f"{b} distinct domains: route each request to a specialist prompt/agent instead of one prompt carrying every domain's instructions and tools.", "OPENAI_PG"))
        out.append(_sig("R08", "single_agent", -0.5 * min(b, 5), "One agent with many domains' tools and instructions becomes hard to prompt and evaluate; split when it needs more than ~10-15 well-defined tools or overlapping instructions.", "OPENAI_PG"))
    if b >= 3:
        out.append(_sig("R09", "orchestrator_workers", +1.0 + 0.3 * min(b, 6), "Several domains inside one request: a lead delegates to domain specialists with narrow prompts and tool sets.", "ANTHROPIC_MA"))
        if p.interaction == "multi_turn" and p.output_type in ("short_answer", "action"):
            out.append(_sig("R10", "handoff_network", +2.0, "Multi-turn conversation crossing specialist domains: decentralised handoffs let the right specialist own the user at each moment.", "OPENAI_PG"))
    if b >= 5 and p.parallel_subtasks >= 4:
        out.append(_sig("R11", "hierarchical", +2.0, "Many domains each with several sub-tasks: hierarchy keeps each roster small and each brief focused.", "GOOGLE_ADK"))
    if b == 1:
        out.append(_sig("R12", "hierarchical", -3.0, "Single domain: no reason for a second delegation level.", "COGNITION"))
        out.append(_sig("R12", "handoff_network", -2.0, "Single domain: nothing to hand off between.", "OPENAI_PG"))
        out.append(_sig("R12", "router", -1.0, "Single domain: nothing to route between (unless routing by difficulty for cost).", "ANTHROPIC_BEA"))
    return out


# ---------------------------------------------------------------- knowledge & context

@rule
def knowledge_retrieval(p: WorkloadProfile) -> list[Signal]:
    out: list[Signal] = []
    d = p.retrieval_depth
    k = p.knowledge_sources
    if d == "single_lookup":
        out.append(_sig("R13", "single_call", +1.5, "One retrieval answers the question: do the retrieval in code (classic RAG) and make one call.", "ANTHROPIC_BEA"))
    if d == "multi_hop":
        out.append(_sig("R14", "single_agent", +2.0, "Multi-hop retrieval: the model must decide follow-up queries from earlier results (agentic retrieval).", "ANTHROPIC_CTX"))
        out.append(_sig("R14", "single_call", -2.0, "Follow-up queries cannot be fixed in advance.", "ANTHROPIC_CTX"))
    if d == "exhaustive":
        out.append(_sig("R15", "orchestrator_workers", +3.0, "Breadth-first research across many documents is the canonical multi-agent win: subagents search in parallel with separate context windows; Anthropic measured ~90% wall-clock reduction on such queries.", "ANTHROPIC_MAR"))
        out.append(_sig("R15", "single_agent", -1.5, "Exhaustive reading in one context window fills it and serialises the searches.", "ANTHROPIC_MAR"))
        out.append(_sig("R15", "single_call", -3.0, "Cannot cover a topic exhaustively in one call.", "ANTHROPIC_MAR"))
    if k >= 3 and d in ("multi_hop", "exhaustive"):
        out.append(_sig("R16", "orchestrator_workers", +0.5 * min(k, 6), f"{k} knowledge sources: one worker per source keeps each context focused and searches concurrent.", "ANTHROPIC_MA"))
    pressure = p.context_pressure
    if pressure in ("high", "extreme"):
        out.append(_sig("R17", "orchestrator_workers", +2.0 if pressure == "high" else +3.0, f"{p.context_tokens_per_task:,} tokens of reading per task ({pressure} context pressure): delegate reading to subagents so only their reports return to the lead.", "ANTHROPIC_MA"))
        out.append(_sig("R17", "single_agent", -1.5 if pressure == "high" else -3.0, "Reading load would fill one context window; quality degrades as context grows.", "ANTHROPIC_CTX"))
        out.append(_sig("R17", "single_call", -3.0, "Reading load exceeds what one prompt should carry.", "ANTHROPIC_CTX"))
        if p.steps_predictable:
            out.append(_sig("R17b", "parallel_sectioning", +2.0, "If the corpus splits predictably (per document / per source), code-defined map-reduce over chunks is the cheaper way to isolate contexts.", "ANTHROPIC_BEA"))
    return out


# ---------------------------------------------------------------- accuracy & verification

@rule
def accuracy_and_verification(p: WorkloadProfile) -> list[Signal]:
    out: list[Signal] = []
    a = p.accuracy_priority
    v = p.verifiability
    if a >= 4 and v == "strong":
        out.append(_sig("R18", "evaluator_optimizer", +2.5, "High accuracy priority and an objective check: generate -> evaluate -> refine converts test/rubric feedback into measurable gains.", "ANTHROPIC_BEA"))
    elif a >= 3 and v in ("partial", "strong") and p.output_type in ("code_change", "long_document", "structured_data"):
        out.append(_sig("R18b", "evaluator_optimizer", +1.5, "Reviewable output with clear criteria: a separate evaluator pass catches errors the generator cannot see in its own draft.", "ANTHROPIC_BEA"))
    if v == "none":
        out.append(_sig("R19", "evaluator_optimizer", -2.5, "Without evaluation criteria the evaluator loop adds cost and latency but little accuracy.", "ANTHROPIC_BEA"))
        out.append(_sig("R19", "parallel_voting", -2.0, "Nothing objective to vote on.", "ANTHROPIC_BEA"))
    if a >= 4 and p.output_type in ("short_answer", "structured_data") and p.complexity_score <= 2:
        out.append(_sig("R20", "parallel_voting", +2.5, "High-stakes bounded decision: several independent votes/judges raise confidence at parallel (not serial) latency cost.", "ANTHROPIC_BEA"))
    if a <= 2:
        out.append(_sig("R21", "parallel_voting", -1.5, "Best-effort accuracy does not justify ensembles.", "ANTHROPIC_BEA"))
        out.append(_sig("R21", "evaluator_optimizer", -1.0, "Best-effort accuracy does not justify a critique loop.", "ANTHROPIC_BEA"))
    if p.tool_side_effects == "irreversible" and p.error_recoverability == "hard":
        out.append(_sig("R22", "orchestrator_workers", -1.0, "Irreversible actions amplify multi-agent coordination failures (duplicated or conflicting actions); keep action-taking in one accountable agent behind an approval gate.", "MAST"))
        out.append(_sig("R22", "hierarchical", -1.5, "Same: irreversible actions and deep delegation are a poor mix.", "MAST"))
        out.append(_sig("R22", "handoff_network", -1.0, "Handoffs lose state; irreversible actions need one owner.", "COGNITION"))
    return out


# ---------------------------------------------------------------- latency & cost

@rule
def latency_budget(p: WorkloadProfile) -> list[Signal]:
    out: list[Signal] = []
    L = p.latency_budget_s
    if L <= 5:
        out.append(_sig("R23", "single_call", +2.0, "Sub-5s budget: only a single call (streamed, small model where possible) fits reliably.", "ANTHROPIC_BEA"))
        out.append(_sig("R23", "router", +0.5, "A fast router (small model) adds well under a second and can send easy requests to a faster path.", "ANTHROPIC_BEA"))
        for t, d in (("single_agent", -1.5), ("prompt_chain", -1.5), ("evaluator_optimizer", -3.0), ("orchestrator_workers", -4.0), ("hierarchical", -5.0), ("handoff_network", -2.0)):
            out.append(_sig("R23", t, d, "Serial round trips do not fit an interactive budget.", "ANTHROPIC_BEA"))
    elif L <= 30:
        for t, d in (("evaluator_optimizer", -1.0), ("orchestrator_workers", -1.5), ("hierarchical", -3.0)):
            out.append(_sig("R24", t, d, "Tight budget: extra serial hops (planning, synthesis, critique) are expensive in wall-clock time.", "ANTHROPIC_MAR"))
    elif L >= 300:
        out.append(_sig("R25", "orchestrator_workers", +1.0, "Minutes-scale budget can absorb planning + synthesis hops in exchange for accuracy and coverage.", "ANTHROPIC_MAR"))
        out.append(_sig("R25", "evaluator_optimizer", +0.5, "Budget allows an extra refinement iteration.", "ANTHROPIC_BEA"))
    return out


@rule
def cost_and_volume(p: WorkloadProfile) -> list[Signal]:
    out: list[Signal] = []
    if p.cost_sensitivity >= 4:
        for t, d in (("orchestrator_workers", -2.0), ("hierarchical", -3.0), ("parallel_voting", -1.5), ("evaluator_optimizer", -1.0)):
            out.append(_sig("R26", t, d, "Cost-sensitive: token multipliers of 3-25x over a single call must be justified by task value.", "ANTHROPIC_MAR"))
        out.append(_sig("R26", "router", +1.0, "Routing easy requests to a small model is the cheapest accuracy-preserving lever.", "ANTHROPIC_BEA"))
    if p.requests_per_day >= 100_000:
        for t, d in (("orchestrator_workers", -1.0), ("hierarchical", -2.0)):
            out.append(_sig("R27", t, d, "At very high volume, multi-agent token multipliers dominate spend; reserve multi-agent for high-value requests behind a router.", "ANTHROPIC_MAR"))
    return out


# ---------------------------------------------------------------- tool surface

@rule
def tool_surface(p: WorkloadProfile) -> list[Signal]:
    out: list[Signal] = []
    if p.tool_overlap:
        out.append(_sig("R28", "single_agent", -1.5, "Overlapping tools are OpenAI's split trigger (systems fail with <10 overlapping tools yet manage 15+ distinct ones): first consolidate/rename tools; if that fails, give each specialist a disjoint tool set.", "OPENAI_PG"))
        out.append(_sig("R28", "router", +1.5, "Routing to specialists gives each a small, non-overlapping tool set.", "OPENAI_PG"))
        out.append(_sig("R28", "orchestrator_workers", +0.5, "Workers with narrow tool sets also remove overlap, at higher cost than routing.", "ANTHROPIC_MA"))
    elif p.tool_count >= 15 and p.scope_breadth >= 2:
        out.append(_sig("R28b", "router", +1.0, "Large tool surface across domains: route to specialists so each carries a small, well-defined tool set.", "OPENAI_PG"))
        out.append(_sig("R28b", "orchestrator_workers", +0.5, "Alternatively give each worker only its tools; the lead needs only delegation tools.", "ANTHROPIC_MA"))
    if p.tool_count >= 16 and p.tool_calls_per_task >= 10:
        for t in ("orchestrator_workers", "hierarchical"):
            out.append(_sig("R28c", t, -1.0, "Tool-heavy workflows (~16 tools) showed multi-agent coordination overhead outweighing gains in the scaling study.", "SCALING"))
    if p.tool_calls_per_task >= 15 and p.tool_dependency == "sequential":
        out.append(_sig("R29", "single_agent", -1.0, "Long sequential tool chains make latency and context growth linear; consider programmatic tool calling to collapse round trips.", "ANTHROPIC_CTX"))
    if p.tool_calls_per_task >= 10 and p.tool_dependency == "independent":
        out.append(_sig("R30", "parallel_sectioning", +1.0, "Many independent tool calls: issue them concurrently (parallel tool use) or fan out in code.", "ANTHROPIC_BEA"))
    if p.uses_tools and p.complexity_score >= 2 and p.scope_breadth == 1:
        out.append(_sig("R31", "single_agent", +1.5, "Single-domain multi-step tool use is what a single agent loop is for; split only after measuring that one agent fails.", "OPENAI_PG"))
    if p.uses_tools:
        out.append(_sig("R32", "single_call", -2.0, "Tools imply at least one loop iteration.", "ANTHROPIC_BEA"))
    return out


# ---------------------------------------------------------------- interaction shape

@rule
def interaction_shape(p: WorkloadProfile) -> list[Signal]:
    out: list[Signal] = []
    if p.interaction == "long_running":
        out.append(_sig("R33", "single_agent", +0.5, "Long-running single task: one agent with context editing/compaction and memory can go far; add subagents only for reading-heavy or parallel pieces.", "ANTHROPIC_CTX"))
        if p.complexity_score >= 3:
            out.append(_sig("R33b", "orchestrator_workers", +1.0, "Long, complex tasks benefit from isolating sub-tasks in fresh contexts to keep the lead's context small.", "ANTHROPIC_MA"))
    if p.interaction == "multi_turn" and p.scope_breadth == 1:
        out.append(_sig("R34", "handoff_network", -1.0, "Conversational but single-domain: one agent owning the conversation is simpler.", "COGNITION"))
    if p.output_type == "long_document" and p.complexity_score >= 2:
        out.append(_sig("R35", "prompt_chain", +1.0, "Long documents benefit from outline -> sections -> edit stages with checks between them.", "ANTHROPIC_BEA"))
        if p.parallel_subtasks >= 2 or p.scope_breadth >= 2:
            out.append(_sig("R35b", "orchestrator_workers", +0.5, "Sections can be drafted by workers and unified by a single writer to keep one voice; keep final synthesis in one agent.", "COGNITION"))
    if p.output_type == "code_change":
        out.append(_sig("R36", "single_agent", +1.0, "Code changes need shared, consistent context (one agent editing one tree); parallel writers conflict.", "COGNITION"))
        out.append(_sig("R36", "orchestrator_workers", -1.0, "Parallel code-writing subagents make conflicting decisions; use subagents for read-only review/tests, not concurrent edits.", "COGNITION"))
    return out


@rule
def evidence_from_measurements(p: WorkloadProfile) -> list[Signal]:
    """Rules that fire only when the user has measured something."""
    out: list[Signal] = []
    b = p.single_agent_baseline
    if b >= 0:
        if b > 0.45:
            for t, d in (("orchestrator_workers", -3.0), ("hierarchical", -4.0), ("handoff_network", -2.0)):
                out.append(_sig("R37", t, d, f"Single-agent baseline is {b:.0%}: above ~45% the scaling study found negative returns from adding agents (capability saturation). Improve the model/prompt/tools instead.", "SCALING"))
            out.append(_sig("R37", "single_agent", +2.0, f"A {b:.0%} single-agent baseline is the regime where one agent plus a better model/effort/tools wins.", "SCALING"))
        elif b < 0.25 and p.parallel_subtasks >= 2:
            out.append(_sig("R38", "orchestrator_workers", +1.5, f"Low single-agent baseline ({b:.0%}) on a decomposable task is where centralised multi-agent showed its largest gains (up to +80% on decomposable benchmarks).", "SCALING"))
    return out


@rule
def sequential_dependency(p: WorkloadProfile) -> list[Signal]:
    out: list[Signal] = []
    if p.tool_dependency == "sequential" and p.parallel_subtasks <= 1 and p.complexity_score >= 3:
        out.append(_sig("R39", "orchestrator_workers", -2.0, "Strictly sequential, inter-dependent work: multi-agent lost 39-70% on sequential planning benchmarks; workers cannot see each other's decisions.", "SCALING"))
        out.append(_sig("R39", "hierarchical", -2.0, "Same: sequential dependency defeats delegation.", "SCALING"))
        out.append(_sig("R39", "single_agent", +1.0, "One agent with full context handles dependent steps consistently (share context, share traces).", "COGNITION"))
    if p.accuracy_priority >= 4 and p.error_recoverability == "hard":
        out.append(_sig("R40", "handoff_network", -1.5, "Decentralised topologies amplified errors 7.8x vs. 4.4x for a centralised orchestrator; with costly, hard-to-undo errors keep one accountable agent.", "SCALING"))
        out.append(_sig("R40", "parallel_sectioning", -0.5, "Independent branches with no central check amplified errors most (17x); require a verification/merge step.", "SCALING"))
    return out


@rule
def retrieval_latency(p: WorkloadProfile) -> list[Signal]:
    out: list[Signal] = []
    if p.retrieval_depth in ("multi_hop", "exhaustive") and p.latency_budget_s <= 5:
        out.append(_sig("R41", "single_agent", -1.5, "Agentic retrieval loops run 3-20x the latency of single-pass RAG; an interactive budget forces single-pass retrieval with escalation only on failure signals (adaptive RAG).", "RAG"))
        out.append(_sig("R41", "router", +1.0, "Adaptive RAG: classify the query, single-pass by default, escalate to the multi-hop path only when needed.", "RAG"))
    return out


def evaluate_rules(p: WorkloadProfile) -> list[Signal]:
    signals: list[Signal] = []
    for r in _RULES:
        signals.extend(r(p))
    return signals
