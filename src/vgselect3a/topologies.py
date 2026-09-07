"""Catalog of candidate topologies and model tiers.

The descriptive text here follows the vocabulary of Anthropic's "Building
effective agents" (prompt chaining, routing, parallelization, orchestrator-
workers, evaluator-optimizer), OpenAI's "A practical guide to building agents"
(single agent, manager, decentralized handoffs), and LangGraph / Google ADK
(supervisor, hierarchical). See docs/industry_guidance.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Topology:
    id: str
    name: str
    family: str  # "single" | "workflow" | "multi_agent"
    summary: str
    when_to_use: str
    drawbacks: str
    # Baseline token multiplier vs. one plain chat completion. Anthropic reports
    # agents ~4x chat and multi-agent research systems ~15x chat.
    token_multiplier: float
    # Relative implementation/operational complexity, 1 (trivial) .. 5 (hard).
    build_complexity: int


TOPOLOGIES: dict[str, Topology] = {
    t.id: t
    for t in (
        Topology(
            id="single_call",
            name="Single model call",
            family="single",
            summary="One prompt, one response; optionally with structured output and retrieval-augmented context assembled in code.",
            when_to_use="Classification, extraction, summarisation, Q&A over a bounded context where the steps need no tools and no iteration.",
            drawbacks="Cannot act on the world or gather information it was not given; quality is capped by what fits in one prompt.",
            token_multiplier=1.0,
            build_complexity=1,
        ),
        Topology(
            id="single_agent",
            name="Single agent with tools",
            family="single",
            summary="One model in a tool-use loop: it decides which tools to call, reads results, and iterates until done.",
            when_to_use="Multi-step tasks in one domain where the path is not fully known in advance but one context window can hold the work. The industry default: start here and only split when measured to be necessary.",
            drawbacks="Latency grows linearly with sequential tool calls; context fills up on long tasks; a single prompt carrying many tools and instructions degrades.",
            token_multiplier=4.0,
            build_complexity=2,
        ),
        Topology(
            id="prompt_chain",
            name="Prompt chain (sequential workflow)",
            family="workflow",
            summary="Fixed sequence of model steps defined in code, each consuming the previous output, with programmatic gates/checks between steps.",
            when_to_use="The task decomposes cleanly into fixed sub-steps (draft -> check -> translate; extract -> validate -> format). Trades a little latency for higher per-step accuracy.",
            drawbacks="Rigid: any variation in the path must be handled in code; each step adds a round trip.",
            token_multiplier=1.8,
            build_complexity=2,
        ),
        Topology(
            id="router",
            name="Router / classifier dispatch",
            family="workflow",
            summary="A cheap classification step assigns each request to one of several specialised prompts, agents or models.",
            when_to_use="Distinct request categories that are better handled separately (billing vs. technical support; easy vs. hard questions routed to small vs. large models).",
            drawbacks="Misrouting is a hard failure; categories must be separable; adds one small hop of latency.",
            token_multiplier=1.3,
            build_complexity=2,
        ),
        Topology(
            id="parallel_sectioning",
            name="Parallel sectioning (code-defined fan-out)",
            family="workflow",
            summary="Code splits the task into independent sections, runs a model call or agent for each concurrently, then aggregates programmatically or with a final synthesis call.",
            when_to_use="Independent sub-tasks known in advance (review a PR for security, style and tests in parallel; process N documents). Wall-clock latency approximates the slowest branch.",
            drawbacks="Sections must be independent; total token cost multiplies with branches; aggregation quality depends on the merge step.",
            token_multiplier=3.0,
            build_complexity=3,
        ),
        Topology(
            id="parallel_voting",
            name="Parallel voting / ensemble",
            family="workflow",
            summary="The same task is run several times (different prompts, samples or models) and the answers are voted, merged, or judged.",
            when_to_use="High-stakes decisions with a verifiable or majority-able answer (vulnerability triage, moderation, medical/legal classification) where a few extra parallel calls buy confidence.",
            drawbacks="Multiplies cost by the number of votes; no help on tasks without a comparable answer.",
            token_multiplier=3.0,
            build_complexity=2,
        ),
        Topology(
            id="evaluator_optimizer",
            name="Evaluator-optimizer loop",
            family="workflow",
            summary="A generator produces an answer, a separate evaluator critiques it against explicit criteria, and the loop repeats until accepted or a budget is hit.",
            when_to_use="Clear evaluation criteria and measurable iterative gains: code that must pass tests, translations, writing to a rubric.",
            drawbacks="Each iteration is a full extra round trip; without objective criteria the evaluator adds cost without accuracy.",
            token_multiplier=3.0,
            build_complexity=3,
        ),
        Topology(
            id="orchestrator_workers",
            name="Orchestrator + worker subagents",
            family="multi_agent",
            summary="A lead agent plans, dynamically spawns worker subagents with self-contained briefs (each in its own context window), runs them in parallel, then verifies and synthesises their reports.",
            when_to_use="Open-ended tasks whose sub-tasks cannot be predicted in advance, breadth-first research across many sources, or work that would overflow one context window. Anthropic's research system cut time by up to 90% on breadth queries versus a single agent.",
            drawbacks="Roughly 15x the tokens of a chat interaction; coordination bugs (duplicated work, gaps, inconsistent assumptions); sub-agents share no context, so briefs must be explicit.",
            token_multiplier=15.0,
            build_complexity=4,
        ),
        Topology(
            id="hierarchical",
            name="Hierarchical teams (orchestrator -> leads -> workers)",
            family="multi_agent",
            summary="Two levels of delegation: a top orchestrator assigns domains to team leads, each of which runs its own worker roster.",
            when_to_use="Very broad scope spanning many domains with many subtasks each, where a single orchestrator's roster or context would be overwhelmed.",
            drawbacks="The most expensive and slowest to build and debug; extra hop of latency and briefing loss at each level. Most platforms cap delegation depth (Managed Agents allows one level).",
            token_multiplier=25.0,
            build_complexity=5,
        ),
        Topology(
            id="handoff_network",
            name="Specialist handoffs (decentralised)",
            family="multi_agent",
            summary="Peer specialist agents transfer the conversation to one another as the topic changes; no central manager keeps control.",
            when_to_use="Multi-turn conversations that move between distinct specialist domains (triage -> orders -> refunds) where one specialist should own the user at a time.",
            drawbacks="Harder to observe and test than a router; loops and ping-pong between agents; state must be passed explicitly on each handoff.",
            token_multiplier=4.5,
            build_complexity=3,
        ),
    )
}


@dataclass(frozen=True)
class ModelTier:
    tier: str
    model_id: str
    input_price_per_mtok: float
    output_price_per_mtok: float
    # Rough serving characteristics used only for latency estimates.
    ttft_s: float
    tokens_per_s: float
    role: str


MODEL_TIERS: dict[str, ModelTier] = {
    "opus": ModelTier("opus", "claude-opus-5", 5.0, 25.0, 1.5, 55.0, "Orchestrator, synthesis, hard reasoning, final answers."),
    "sonnet": ModelTier("sonnet", "claude-sonnet-5", 2.0, 10.0, 1.0, 85.0, "Workers that need judgment; high-volume production paths."),
    "haiku": ModelTier("haiku", "claude-haiku-4-5", 1.0, 5.0, 0.6, 140.0, "Routers, classifiers, bulk reading/extraction workers."),
}
