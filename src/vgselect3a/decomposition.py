"""Turn a chosen topology + profile into a concrete component plan:
which agents exist, what each owns, which model tier runs it, what runs in
parallel, and the cross-cutting augmentations (caching, context management,
approval gates, ...) that apply regardless of topology.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .estimator import agent_tier, pick_tier, worker_count
from .profile import WorkloadProfile
from .topologies import MODEL_TIERS


@dataclass
class Component:
    id: str
    name: str
    role: str
    tier: str                      # opus | sonnet | haiku | code
    effort: str = "high"           # low | medium | high | xhigh | max | n/a
    tools: str = ""
    parallel_group: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def model_id(self) -> str:
        return MODEL_TIERS[self.tier].model_id if self.tier in MODEL_TIERS else "code"


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""


@dataclass
class Augmentation:
    id: str
    title: str
    why: str
    citation: str


@dataclass
class Plan:
    topology_id: str
    components: list[Component]
    edges: list[Edge]
    augmentations: list[Augmentation]
    briefing_rules: list[str]


# ---------------------------------------------------------------- naming helpers

def _names(p: WorkloadProfile, key: str, n: int, fallback: str) -> list[str]:
    given = p.extra.get(key) if isinstance(p.extra.get(key), list) else []
    names = [str(x) for x in given][:n]
    while len(names) < n:
        names.append(f"{fallback} {len(names) + 1}")
    return names


def _worker_effort(p: WorkloadProfile) -> str:
    return "medium" if p.accuracy_priority >= 4 else "low"


def _lead_effort(p: WorkloadProfile) -> str:
    if p.accuracy_priority >= 5:
        return "max"
    if p.accuracy_priority == 4 or p.complexity_score >= 3:
        return "xhigh"
    return "high"


# ---------------------------------------------------------------- plans per topology

def build_plan(p: WorkloadProfile, topology_id: str) -> Plan:
    comps: list[Component] = []
    edges: list[Edge] = []
    briefs: list[str] = []
    tool_desc = _tool_summary(p)

    if topology_id == "single_call":
        tier = pick_tier(p)
        if p.retrieval_depth != "none":
            comps.append(Component("retrieve", "Retrieval (code)", "Query the knowledge source(s) in code and assemble context.", "code", "n/a"))
            edges.append(Edge("retrieve", "llm", "context"))
        comps.append(Component("llm", "Model call", "Answer from the assembled prompt; structured output if the result is data.", tier, "medium" if p.is_interactive else "high"))

    elif topology_id == "single_agent":
        comps.append(Component("agent", "Agent", "Plans and executes the whole task in one tool-use loop.", agent_tier(p), _lead_effort(p), tool_desc))
        if p.context_pressure in ("medium", "high", "extreme") and p.retrieval_depth in ("multi_hop", "exhaustive"):
            comps.append(Component("explorer", "Read-only explorer subagent (optional)", "Searches/reads on the agent's behalf and returns a short summary, keeping raw material out of the main context. Spawn several in parallel for independent questions.", _worker_tier(p), "low", "read/search tools only", parallel_group="explorers"))
            edges += [Edge("agent", "explorer", "question"), Edge("explorer", "agent", "summary")]
        if p.tool_side_effects == "irreversible":
            comps.append(Component("gate", "Approval gate (code)", "Intercepts irreversible tool calls for human/automated approval.", "code", "n/a"))
            edges.append(Edge("agent", "gate", "irreversible actions"))

    elif topology_id == "prompt_chain":
        stages = _chain_stages(p)
        prev = None
        for i, (sid, name, role, tier) in enumerate(stages):
            comps.append(Component(sid, name, role, tier, "medium" if tier != "opus" else _lead_effort(p), tool_desc if "tool" in role.lower() else ""))
            if prev:
                edges.append(Edge(prev, sid, "gate: validate output"))
            prev = sid

    elif topology_id == "router":
        comps.append(Component("router", "Router", "Classifies the request into one category (small model, structured output).", "haiku", "low"))
        domains = _names(p, "domains", max(2, min(p.scope_breadth, 8)), "Domain")
        for i, d in enumerate(domains):
            cid = f"handler_{i + 1}"
            role = f"Handles '{d}' requests with only that domain's instructions and tools."
            tier = agent_tier(p) if p.uses_tools else pick_tier(p)
            comps.append(Component(cid, f"{d} specialist", role, tier, "high", tool_desc))
            edges.append(Edge("router", cid, d))
        if p.scope_breadth == 1:
            comps[1].name, comps[1].role = "Fast path", "Easy requests: small model, short prompt."
            comps[1].tier = "haiku"
            comps[2].name, comps[2].role = "Full path", "Hard requests: large model with full context/tools."
            edges[0].label, edges[1].label = "easy", "hard"

    elif topology_id == "parallel_sectioning":
        n = max(2, min(p.parallel_subtasks, 20))
        comps.append(Component("split", "Splitter (code)", "Divides the request into independent sections deterministically.", "code", "n/a"))
        for i, name in enumerate(_names(p, "sections", n, "Section")):
            cid = f"section_{i + 1}"
            comps.append(Component(cid, f"{name} worker", "Processes one section independently.", "sonnet", _worker_effort(p), tool_desc, parallel_group="fanout"))
            edges += [Edge("split", cid), Edge(cid, "merge", "result")]
        comps.append(Component("merge", "Aggregator", "Merges section outputs (in code when possible; one synthesis call when prose is needed).", "opus", "high"))

    elif topology_id == "parallel_voting":
        votes = 5 if p.accuracy_priority >= 5 else 3
        vt = agent_tier(p) if p.uses_tools else pick_tier(p)
        for i in range(votes):
            cid = f"vote_{i + 1}"
            comps.append(Component(cid, f"Voter {i + 1}", "Independent attempt at the task" + (" (each an agent loop with its own tool calls)" if p.uses_tools else "") + "; vary prompt/temperature/model for diversity.", vt, "high", tool_desc, parallel_group="votes"))
            edges.append(Edge(cid, "judge", "answer"))
        comps.append(Component("judge", "Judge / majority (code)", "Majority vote in code for discrete answers; a judge call for free-form ones.", "code" if p.output_type in ("short_answer", "structured_data") else "opus", "n/a" if p.output_type in ("short_answer", "structured_data") else "high"))

    elif topology_id == "evaluator_optimizer":
        comps.append(Component("generator", "Generator", "Produces the candidate (agent loop if tools are needed).", agent_tier(p) if p.uses_tools else pick_tier(p), _lead_effort(p), tool_desc))
        comps.append(Component("evaluator", "Evaluator", "Scores the candidate against explicit criteria; runs tests/validators when available; returns actionable feedback.", "opus" if p.accuracy_priority >= 4 else "sonnet", "high", "tests / validators / rubric"))
        edges += [Edge("generator", "evaluator", "candidate"), Edge("evaluator", "generator", "feedback (until accepted or budget)")]

    elif topology_id == "orchestrator_workers":
        n = worker_count(p)
        comps.append(Component("lead", "Orchestrator (lead agent)", "Understands the request, decides how many workers and what each owns, writes self-contained briefs, verifies reports, synthesises the final answer. Keeps final synthesis to itself.", "opus", _lead_effort(p), "delegate / spawn_worker; final verification tools"))
        for i, name in enumerate(_worker_names(p, n)):
            cid = f"worker_{i + 1}"
            comps.append(Component(cid, name, "Owns one well-scoped sub-task in a fresh context; returns a concise report with evidence, not raw material.", _worker_tier(p), _worker_effort(p), tool_desc, parallel_group="workers"))
            edges += [Edge("lead", cid, "brief"), Edge(cid, "lead", "report")]
        if p.verifiability != "none" and p.accuracy_priority >= 4:
            comps.append(Component("critic", "Verifier", "Independent read-only check of the synthesised answer against sources/tests before it is returned.", "opus", "high"))
            edges += [Edge("lead", "critic", "draft"), Edge("critic", "lead", "issues")]
        briefs += [
            "Each brief must carry: objective, output format, tools/sources to use, boundaries (what NOT to do), and the effort expected (Anthropic: simple fact-finding ~3-10 tool calls; comparisons ~10-15).",
            "Workers see none of the lead's conversation: include every path, constraint and definition in the brief.",
            f"Spawn all {n} workers in one turn so they run concurrently; cap concurrent threads (platform limits ~25).",
            "Workers return compressed findings with citations; the lead never re-reads raw sources unless verifying.",
            "Keep decisions that need shared context (final wording, code edits) in the lead, not in parallel workers.",
        ]

    elif topology_id == "hierarchical":
        leads = max(2, min(p.scope_breadth, 6))
        n = worker_count(p)
        per = max(2, -(-n // leads))
        comps.append(Component("top", "Top orchestrator", "Assigns domains to leads; integrates lead reports into the final deliverable.", "opus", _lead_effort(p), "delegate"))
        for j, dom in enumerate(_names(p, "domains", leads, "Domain")):
            lid = f"lead_{j + 1}"
            comps.append(Component(lid, f"{dom} lead", f"Plans and verifies work within '{dom}'; runs its own workers.", "opus", "high", "delegate", parallel_group="leads"))
            edges += [Edge("top", lid, "domain brief"), Edge(lid, "top", "domain report")]
            for i in range(per):
                wid = f"{lid}_w{i + 1}"
                comps.append(Component(wid, f"{dom} worker {i + 1}", "One sub-task, fresh context, concise report.", _worker_tier(p), _worker_effort(p), tool_desc, parallel_group=f"{lid}_workers"))
                edges += [Edge(lid, wid, "brief"), Edge(wid, lid, "report")]
        briefs.append("Two delegation levels: many platforms allow only one (Managed Agents). Implement the second level in code or flatten to orchestrator-workers if the platform cannot nest.")

    elif topology_id == "handoff_network":
        domains = _names(p, "domains", max(2, min(p.scope_breadth, 6)), "Domain")
        ids = []
        for i, d in enumerate(domains):
            cid = f"spec_{i + 1}"
            ids.append(cid)
            comps.append(Component(cid, f"{d} specialist", f"Owns the conversation while it is about '{d}'; can transfer to any peer with a state summary.", agent_tier(p), "high", tool_desc + "; transfer_to_<peer>"))
        for a in ids:
            for b in ids:
                if a != b:
                    edges.append(Edge(a, b, "handoff"))
        briefs.append("Pass an explicit state object on every handoff (user goal, facts gathered, actions taken); never rely on the next agent inferring it from the transcript.")

    else:
        raise KeyError(topology_id)

    return Plan(topology_id, comps, edges, augmentations(p, topology_id), briefs)


# ---------------------------------------------------------------- helpers

def _tool_summary(p: WorkloadProfile) -> str:
    tools = p.extra.get("tools")
    if isinstance(tools, list) and tools:
        return ", ".join(str(t) for t in tools[:12]) + (" ..." if len(tools) > 12 else "")
    return f"{p.tool_count} tools" if p.tool_count else ""


def _worker_tier(p: WorkloadProfile) -> str:
    # Reading-heavy, low-judgment work goes to Haiku; judgment-heavy to Sonnet.
    if p.retrieval_depth in ("single_lookup", "exhaustive") and p.complexity_score <= 2 and p.accuracy_priority <= 3:
        return "haiku"
    return "sonnet"


def _worker_names(p: WorkloadProfile, n: int) -> list[str]:
    if p.retrieval_depth in ("multi_hop", "exhaustive") and p.knowledge_sources >= 2:
        given = p.extra.get("sources") if isinstance(p.extra.get("sources"), list) else []
        names = [f"Researcher: {s}" for s in given[:n]]
        names += [f"Researcher: subtopic {i + 1}" for i in range(n - len(names))]
        return names
    if p.scope_breadth >= 3:
        return [f"Specialist: {d}" for d in _names(p, "domains", n, "domain")]
    return _names(p, "subtasks", n, "Worker")


def _chain_stages(p: WorkloadProfile) -> list[tuple[str, str, str, str]]:
    if p.output_type == "long_document":
        return [("outline", "Outline", "Produce an outline and acceptance criteria.", "sonnet"),
                ("draft", "Draft", "Write each section from the outline (tool calls for facts if needed).", "opus"),
                ("check", "Check", "Validate against criteria/gates in code (length, required sections, facts).", "sonnet"),
                ("polish", "Polish", "Final edit into one voice.", "opus")]
    if p.output_type == "structured_data":
        return [("extract", "Extract", "Pull candidate fields from the input (tools if needed).", "sonnet"),
                ("validate", "Validate (code)", "Schema and business-rule checks in code; reject or route back.", "code"),
                ("finalize", "Finalize", "Resolve ambiguities and emit the final structured record.", "opus")]
    stages = [("understand", "Understand", "Restate the task and gather what is needed (tool calls if needed).", "sonnet"),
              ("solve", "Solve", "Produce the answer.", "opus")]
    if p.complexity_score >= 3:
        stages.append(("review", "Review", "Check the answer against the task statement; fix or escalate.", "opus"))
    return stages


def augmentations(p: WorkloadProfile, topology_id: str) -> list[Augmentation]:
    a: list[Augmentation] = []
    add = lambda i, t, w, c: a.append(Augmentation(i, t, w, c))  # noqa: E731
    add("evals", "Build a ~20-query eval before adding any structure", "Every source agrees: measure a single agent/call first, then add topology only where the eval shows it failing. Above a ~45% single-agent baseline, adding agents tended to hurt in the scaling study. Keep the eval to compare latency and accuracy across topologies.", "SCALING")
    if topology_id in ("single_agent", "evaluator_optimizer", "orchestrator_workers", "hierarchical", "handoff_network"):
        add("termination", "Explicit termination limits on every loop", "Max turns/tool calls per agent, max evaluator iterations, max handoffs, max concurrent subagents. 'Unaware of termination' and 'step repetition' account for ~28% of multi-agent failures in MAST.", "MAST")
    if p.is_interactive or p.output_type == "long_document":
        add("streaming", "Stream responses", "Perceived latency drops to time-to-first-token; long outputs must stream to avoid timeouts.", "ANTHROPIC_CTX")
    add("caching", "Prompt caching on the stable prefix (system prompt, tool schemas, reference docs)", "Multi-turn and multi-call topologies re-send the same prefix on every call; caching cuts cost up to ~90% and time-to-first-token.", "ANTHROPIC_CTX")
    if p.output_type == "structured_data" or topology_id in ("router", "parallel_voting"):
        add("structured_outputs", "Structured outputs (JSON schema) for routers, extractors and votes", "Removes parsing failures and makes code-side gates and majority votes trivial.", "ANTHROPIC_BEA")
    if p.tool_dependency in ("independent", "mixed") and p.tool_calls_per_task >= 2:
        add("parallel_tools", "Parallel tool use inside each agent turn", "Independent tool calls issued in one assistant turn cut rounds by 2-4x; return all results in one message.", "ANTHROPIC_CTX")
    if p.tool_calls_per_task >= 8 and p.tool_dependency != "independent":
        add("ptc", "Programmatic tool calling for long sequential tool chains", "Let the model write a script that calls tools; intermediate results never enter context, collapsing many round trips into one.", "ANTHROPIC_CTX")
    if p.tool_count >= 20:
        add("tool_search", "Tool search / deferred tool loading", f"{p.tool_count} tool schemas in every prompt waste context and degrade selection; load relevant schemas on demand.", "ANTHROPIC_CTX")
    if p.tool_calls_per_task >= 10 or p.interaction != "single_turn":
        add("context_editing", "Context editing (clear stale tool results/thinking)", "Keeps long loops lean without summarisation losses.", "ANTHROPIC_CTX")
    if p.interaction == "long_running" or p.context_pressure in ("high", "extreme"):
        add("compaction", "Server-side compaction near the context limit", "Summarises earlier context so a long task can continue; preserve compaction blocks on every turn.", "ANTHROPIC_CTX")
    if p.interaction in ("multi_turn", "long_running"):
        add("memory", "Memory across sessions (file/DB-backed)", "State that must outlive one conversation should be written to memory, not carried in context.", "ANTHROPIC_CTX")
    if p.tool_side_effects == "irreversible":
        add("gate", "Dedicated, gated tools for irreversible actions" + (" with human approval" if p.human_in_loop else " with checkpoints/rollback"), "Promote side-effecting actions to typed tools so the harness can intercept, confirm, audit and roll back; never let them run through a generic shell tool.", "ANTHROPIC_BEA")
    if topology_id in ("orchestrator_workers", "hierarchical", "parallel_sectioning", "router"):
        add("tiering", "Model tiering: large model for planning/synthesis, smaller models for reading/routing", "Reading-heavy workers and routers need many input tokens and little judgment; run them on Sonnet/Haiku and keep Opus for the lead.", "ANTHROPIC_MA")
    if p.retrieval_depth == "single_lookup":
        add("rag", "Retrieval in code (classic RAG), not by the model", "One deterministic query is cheaper and faster than an agent deciding to search.", "ANTHROPIC_BEA")
    if p.retrieval_depth in ("multi_hop", "exhaustive"):
        add("agentic_rag", "Agentic retrieval capped at ~4 iterations: start broad, then narrow", "Multi-hop retrieval buys accuracy (27% -> 43% EM on HotpotQA) at 3-20x latency; cap the loop and prefer short broad queries first, narrowing progressively.", "RAG")
    if p.retrieval_depth == "multi_hop" and (p.is_interactive or p.requests_per_day >= 50_000):
        add("adaptive_rag", "Adaptive RAG: single-pass by default, escalate on failure signals", "Route simple queries to one retrieval; escalate to the multi-hop loop only on missing citations, low retrieval confidence, contradictions or repeated follow-ups.", "RAG")
    if p.latency_budget_s >= 3600 and p.requests_per_day >= 1000:
        add("batch", "Message Batches API for the offline share of traffic", "Asynchronous processing at 50% cost when no one is waiting.", "ANTHROPIC_BEA")
    if p.scope_breadth == 1 and p.cost_sensitivity >= 4 and topology_id != "router":
        add("difficulty_router", "Consider a difficulty router in front", "Send easy requests to a small model and hard ones to the full path; the largest cost lever after caching.", "ANTHROPIC_BEA")
    if topology_id in ("orchestrator_workers", "hierarchical"):
        add("verification", "Verification step at the orchestrator before returning", "Task-verification failures are ~25% of multi-agent failures; a centralised check is also why centralised topologies amplify errors least (4.4x vs 7.8x-17x).", "MAST")
        add("observability", "Full tracing of every subagent turn and brief", "Multi-agent failures are mostly specification and coordination failures; you cannot debug them without traces of what each agent was told.", "MAST")
        add("effort", "Effort tuning per role", "Lead at high/xhigh (or max when correctness dominates); workers at low/medium for fewer, more consolidated tool calls.", "ANTHROPIC_MA")
    return a
