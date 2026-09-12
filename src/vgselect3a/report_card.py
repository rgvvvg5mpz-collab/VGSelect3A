"""Agent report card: task, design and behavioural complexity, graded dimensions,
mismatch flags, and per-agent cards for multi-agent systems.

    card = build_report_card(profile, scan=scan, traces=traces, recommendation=rec)
    card.to_markdown(); card.to_dict()

Grades are computed from explicit formulas documented in docs/REPORT_CARD.html.
Design metrics come from the repository scan (static); behavioural metrics from
run-time traces (see traces.py). Without traces the card is design-time only.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import TYPE_CHECKING, Any

from .profile import WorkloadProfile
from .scanner import ScanResult
from .traces import BehaviourMetrics, TraceSet, compute_behaviour

if TYPE_CHECKING:
    from .recommender import Recommendation

LEVEL_NAMES = {1: "trivial", 2: "simple", 3: "moderate", 4: "complex", 5: "open-ended"}


def letter(score: float | None) -> str:
    if score is None:
        return "n/a"
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"


@dataclass
class Dimension:
    id: str
    name: str
    score: float | None          # 0..100, None when not measurable
    grade: str
    findings: list[str]
    metrics: dict[str, Any]
    weight: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Mismatch:
    id: str
    severity: str                # info | warn | high
    title: str
    detail: str
    action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentCard:
    agent: str
    role: str | None
    model: str | None
    behaviour: BehaviourMetrics | None
    grade: str
    score: float | None
    findings: list[str]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["behaviour"] = self.behaviour.to_dict() if self.behaviour else None
        return d


@dataclass
class ReportCard:
    name: str
    mode: str                                    # "design-time" | "full"
    task_level: int
    design_level: int
    behaviour_level: int | None
    design_metrics: dict[str, Any]
    behaviour: BehaviourMetrics | None
    dimensions: list[Dimension]
    mismatches: list[Mismatch]
    agents: list[AgentCard]
    overall_score: float | None
    overall_grade: str
    summary: str
    trace_warnings: list[str] = field(default_factory=list)

    def dimension(self, did: str) -> Dimension | None:
        return next((d for d in self.dimensions if d.id == did), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "mode": self.mode, "overall_score": self.overall_score, "overall_grade": self.overall_grade, "summary": self.summary,
            "complexity": {"task": {"level": self.task_level, "label": LEVEL_NAMES[self.task_level]},
                           "design": {"level": self.design_level, "label": LEVEL_NAMES[self.design_level]},
                           "behaviour": {"level": self.behaviour_level, "label": LEVEL_NAMES.get(self.behaviour_level or 0)} if self.behaviour_level else None},
            "design_metrics": self.design_metrics, "behaviour": self.behaviour.to_dict() if self.behaviour else None,
            "dimensions": [d.to_dict() for d in self.dimensions], "mismatches": [m.to_dict() for m in self.mismatches],
            "agents": [a.to_dict() for a in self.agents], "trace_warnings": self.trace_warnings,
        }

    def to_markdown(self) -> str:
        return report_card_markdown(self)


# ------------------------------------------------------------------ complexity levels

def task_level(p: WorkloadProfile) -> int:
    lvl = p.complexity_score + 1
    if p.scope_breadth >= 3 or p.knowledge_sources >= 3 or p.parallel_subtasks >= 3 or p.context_pressure in ("high", "extreme"):
        lvl += 1
    return max(1, min(5, lvl))


def design_level(d: dict[str, Any]) -> int:
    tools = d.get("tool_count", 0)
    lvl = 1 if tools == 0 else 2 if tools <= 5 else 3 if tools <= 15 else 4
    if d.get("delegation_depth", 0) >= 2:
        lvl += 2
    elif d.get("delegation_depth", 0) == 1:
        lvl += 1
    lvl += 1 if d.get("handoffs") else 0
    lvl += 1 if d.get("tool_overlap_count", 0) >= 3 else 0
    if d.get("tool_loop") and tools == 0:
        lvl = max(lvl, 2)
    return max(1, min(5, lvl))


def behaviour_level(b: BehaviourMetrics) -> int:
    p95 = b.steps["p95"]
    lvl = 1 if p95 <= 2 else 2 if p95 <= 6 else 3 if p95 <= 15 else 4 if p95 <= 40 else 5
    if b.branching_factor > 2.0:
        lvl += 1
    if b.steps["cv"] > 0.6:
        lvl += 1
    if b.spawns_per_run > 0 or b.handoffs_per_run > 0:
        lvl += 1
    return max(1, min(5, lvl))


# ------------------------------------------------------------------ dimensions

def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def _quality(b: BehaviourMetrics | None, p: WorkloadProfile) -> Dimension:
    f: list[str] = []
    if b is None or b.success_rate is None:
        return Dimension("quality", "Outcome quality", None, "n/a", ["No success labels in traces (set `success` per run) or no traces."], {}, 30)
    score = b.success_rate * 100
    if b.consistency is not None:
        score = 0.7 * score + 0.3 * b.consistency * 100
        if b.consistency < 0.8:
            f.append(f"Only {b.consistency:.0%} of repeated tasks agree on outcome across runs: reliability across runs is low (Galileo reports 60% single-run falling to 25% over eight runs).")
    if p.single_agent_baseline >= 0 and b.success_rate < p.single_agent_baseline - 0.05:
        f.append(f"Measured success {b.success_rate:.0%} is below the stated single-agent baseline {p.single_agent_baseline:.0%}: the added structure is not paying for itself.")
    if b.success_rate >= 0.45 and p.complexity_score >= 3:
        f.append(f"Success {b.success_rate:.0%} is above the ~45% capability-saturation threshold: adding agents is unlikely to help; improve model, prompt or tools instead.")
    m = {"success_rate": b.success_rate, "consistency": b.consistency, "pass_all_runs": b.pass_all_runs, "tasks": b.tasks, "runs": b.runs}
    return Dimension("quality", "Outcome quality", round(_clamp(score), 1), letter(score), f, m, 30)


def _reliability(b: BehaviourMetrics | None, d: dict[str, Any], p: WorkloadProfile) -> Dimension:
    f: list[str] = []
    if b is None:
        return Dimension("reliability", "Reliability and control", None, "n/a", ["Needs traces."], {}, 20)
    score = 100.0
    score -= min(30, b.repetition_rate * 100)            # loops
    score -= min(25, b.termination_limit_rate * 150)     # hitting caps
    score -= min(20, b.timeout_error_rate * 100)
    score -= min(15, b.tool_error_rate * 100)
    if b.repetition_rate > 0.1:
        f.append(f"{b.repetition_rate:.0%} of runs repeat an identical tool call (step repetition is 15.7% of multi-agent failures in MAST). Add a result cache or a rule against re-calling with the same arguments.")
    if b.termination_limit_rate > 0.05:
        f.append(f"{b.termination_limit_rate:.0%} of runs end by hitting a step or recursion limit: the agent does not know when it is done ('unaware of termination', 12.4% of failures). Add explicit stop criteria to the prompt and check the limit is not too low.")
    elif not d.get("termination_limits") and (b.steps["p95"] > 10 or b.repetition_rate > 0):
        f.append("No termination limits found in code while runs are long or loop: every loop needs a cap.")
        score -= 10
    if b.tool_error_rate > 0.05:
        f.append(f"Tool error rate {b.tool_error_rate:.0%}: return `is_error` results the model can act on, and add retries with backoff in the harness.")
    if p.accuracy_priority >= 4 and b.verify_rate < 0.5 and not d.get("evals"):
        f.append("High-stakes workload with little verification in traces and no eval harness in code (verification failures are ~25% of multi-agent failures).")
        score -= 10
    m = {"repetition_rate": b.repetition_rate, "termination_limit_rate": b.termination_limit_rate, "timeout_error_rate": b.timeout_error_rate,
         "tool_error_rate": b.tool_error_rate, "verify_rate": b.verify_rate, "termination_limits_in_code": d.get("termination_limits", False)}
    return Dimension("reliability", "Reliability and control", round(_clamp(score), 1), letter(score), f, m, 20)


def _efficiency(b: BehaviourMetrics | None, p: WorkloadProfile, rec: "Recommendation | None") -> Dimension:
    f: list[str] = []
    if b is None:
        return Dimension("efficiency", "Cost and token efficiency", None, "n/a", ["Needs traces."], {}, 15)
    score = 100.0
    expected = None
    if rec is not None:
        cur = next((c for c in rec.candidates if rec.scan and c.topology.id == rec.scan.current_topology), None) or rec.primary
        expected = cur.estimate.total_tokens
    ratio = (b.tokens_per_run["mean"] / expected) if expected else None
    if ratio is not None:
        if ratio > 1.5:
            score -= min(40, (ratio - 1.5) * 40)
            f.append(f"Measured {b.tokens_per_run['mean']:,.0f} tokens per run is {ratio:.1f}x the estimate for this topology: look for redundant reading, missing caching, or over-long tool results.")
        elif ratio < 0.5:
            f.append(f"Measured tokens per run are {ratio:.1f}x the estimate: the estimate assumptions are conservative for this workload; recalibrate.")
    if b.tokens_per_run["cv"] > 0.8:
        score -= 10
        f.append("Token use varies widely between runs (CV > 0.8): some requests are much more expensive than others; consider a difficulty router.")
    if b.context_growth_per_step > 3000:
        score -= 10
        f.append(f"Context grows ~{b.context_growth_per_step:,.0f} tokens per step: clear or summarise tool results, or delegate reading to subagents.")
    if b.successes_per_1k_tokens is not None and b.successes_per_1k_tokens < 0.01:
        score -= 10
    m = {"tokens_per_run": b.tokens_per_run, "expected_tokens": expected, "ratio_to_estimate": round(ratio, 2) if ratio else None,
         "cost_per_run": b.cost_per_run, "cost_per_completed_task": b.cost_per_completed_task, "successes_per_1k_tokens": b.successes_per_1k_tokens,
         "peak_context": b.peak_context, "context_growth_per_step": b.context_growth_per_step}
    return Dimension("efficiency", "Cost and token efficiency", round(_clamp(score), 1), letter(score), f, m, 15)


def _latency(b: BehaviourMetrics | None, p: WorkloadProfile) -> Dimension:
    f: list[str] = []
    if b is None or not b.latency_ms["p95"]:
        return Dimension("latency", "Latency", None, "n/a", ["Needs traces with step or run latency."], {}, 15)
    budget = p.latency_budget_s * 1000
    r50, r95 = b.latency_ms["p50"] / budget, b.latency_ms["p95"] / budget
    score = 100.0
    if r50 > 1:
        score -= min(50, (r50 - 1) * 50)
        f.append(f"Median latency {b.latency_ms['p50'] / 1000:.1f}s exceeds the {p.latency_budget_s:.0f}s budget.")
    if r95 > 1:
        score -= min(40, (r95 - 1) * 25)
        f.append(f"p95 latency {b.latency_ms['p95'] / 1000:.1f}s is {r95:.1f}x the budget: the tail is driven by long tool chains or loops.")
    m = {"p50_s": round(b.latency_ms["p50"] / 1000, 2), "p95_s": round(b.latency_ms["p95"] / 1000, 2), "max_s": round(b.latency_ms["max"] / 1000, 2), "budget_s": p.latency_budget_s}
    return Dimension("latency", "Latency", round(_clamp(score), 1), letter(score), f, m, 15)


def _governance(d: dict[str, Any], p: WorkloadProfile, b: BehaviourMetrics | None) -> Dimension:
    f: list[str] = []
    score = 100.0
    if not d.get("evals") and not d.get("tests"):
        score -= 25; f.append("No eval harness or tests found: build a ~20-query eval before changing structure.")
    elif not d.get("evals"):
        score -= 10; f.append("Tests exist but no eval harness for model behaviour.")
    if d.get("irreversible_side_effects") and not d.get("approval_gate"):
        score -= 25; f.append("Irreversible integrations without an approval or confirmation gate in code.")
    if (d.get("tool_loop") or d.get("delegation_depth")) and not d.get("termination_limits"):
        score -= 15; f.append("Loops or delegation without termination limits in code.")
    if not d.get("tracing"):
        score -= 10; f.append("No tracing/observability library detected; multi-agent failures cannot be diagnosed without per-turn traces.")
    if p.accuracy_priority >= 4 and not d.get("structured_output"):
        score -= 5; f.append("High-stakes outputs without schema-validated structured output.")
    if b is not None and d.get("irreversible_side_effects") and b.human_rate == 0:
        score -= 10; f.append("Traces show no human approval steps despite irreversible tools.")
    m = {k: d.get(k) for k in ("evals", "tests", "approval_gate", "termination_limits", "tracing", "structured_output", "memory", "context_management", "prompt_caching", "irreversible_side_effects")}
    return Dimension("governance", "Governance and guardrails", round(_clamp(score), 1), letter(score), f, m, 10)


def _fit(task: int, design: int, behaviour: int | None, mismatches: list[Mismatch]) -> Dimension:
    score = 100.0 - sum({"high": 25, "warn": 12, "info": 4}[m.severity] for m in mismatches)
    f = [f"{m.title}" for m in mismatches]
    m = {"task_level": task, "design_level": design, "behaviour_level": behaviour}
    return Dimension("fit", "Complexity fit", round(_clamp(score), 1), letter(score), f, m, 10)


# ------------------------------------------------------------------ mismatches

def find_mismatches(task: int, design: int, behaviour: int | None, d: dict[str, Any], b: BehaviourMetrics | None, p: WorkloadProfile, rec: "Recommendation | None") -> list[Mismatch]:
    out: list[Mismatch] = []
    if design >= task + 2:
        out.append(Mismatch("over_built", "warn", "Over-built for the task",
                            f"Design complexity is level {design} ({LEVEL_NAMES[design]}) for a level-{task} ({LEVEL_NAMES[task]}) task.",
                            "Collapse structure: fewer roles, a single agent or a code-defined workflow; multi-agent costs ~15x chat tokens."))
    if task >= design + 2 and (b is None or (b.success_rate is not None and b.success_rate < 0.6)):
        out.append(Mismatch("under_built", "warn", "Under-built for the task",
                            f"Task is level {task} but the design is level {design}.",
                            "Add the structure the recommendation names (routing, verification, or subagents for breadth)."))
    if b is not None:
        if b.steps["cv"] > 0.8 or (b.trajectory_diversity is not None and b.trajectory_diversity > 0.5):
            out.append(Mismatch("unpredictable_path", "warn", "Unpredictable execution path",
                                f"Step count CV {b.steps['cv']}, trajectory diversity {b.trajectory_diversity}: the same task takes different routes each run.",
                                "Tighten instructions and tool descriptions; move fixed steps into code; measure consistency across repeated runs."))
        if (b.repetition_rate > 0.1 or b.termination_limit_rate > 0.05) and not d.get("termination_limits"):
            out.append(Mismatch("under_controlled", "high", "Loops without limits",
                                f"Repetition in {b.repetition_rate:.0%} of runs, {b.termination_limit_rate:.0%} hit a limit, and no termination limits are in code.",
                                "Add max turns/tool calls/iterations and explicit stop criteria; cache identical tool calls."))
        if behaviour is not None and behaviour >= design + 2:
            out.append(Mismatch("behaviour_exceeds_design", "high", "Behaviour more complex than the design assumes",
                                f"Run-time complexity is level {behaviour} against a level-{design} design.",
                                "The agent is improvising structure at run time: add the missing control flow (router, evaluator, sub-tasks) explicitly."))
        if rec is not None:
            planned = len([c for c in rec.plan.components if c.parallel_group in ("workers", "fanout", "votes")])
            if planned and b.spawns_per_run > planned * 1.5:
                out.append(Mismatch("coordination_waste", "warn", "Spawning more subagents than planned",
                                    f"{b.spawns_per_run:.1f} subagents per run against {planned} planned.",
                                    "Brief the orchestrator with the expected count and effort per sub-task (Anthropic: simple fact-finding 1 agent, comparisons 2-4)."))
        if b.handoffs_per_run > 2:
            out.append(Mismatch("handoff_pingpong", "warn", "Frequent handoffs", f"{b.handoffs_per_run:.1f} handoffs per run.",
                                "Route on the initial input where the specialist is identifiable; cap handoffs."))
        if p.accuracy_priority >= 4 and b.verify_rate < 0.5:
            out.append(Mismatch("under_verified", "warn", "High stakes, little verification",
                                f"Only {b.verify_rate:.0%} of runs include a verification step for a stakes-{p.accuracy_priority} workload.",
                                "Add an evaluator/verifier step (tests, schema checks, or an independent model) before returning."))
    else:
        if p.accuracy_priority >= 4 and not d.get("evaluator_loop") and not d.get("evals"):
            out.append(Mismatch("under_verified", "info", "High stakes, no verification in code",
                                "No evaluator/critic pattern or eval harness detected.", "Add verification before returning; build the eval set."))
    if d.get("tool_overlap_count", 0) >= 3:
        out.append(Mismatch("tool_overlap", "info", "Overlapping tools", f"{d['tool_overlap_count']} tools share a name stem ({', '.join(d.get('overlapping_tools', [])[:4])}).",
                            "Consolidate or namespace tools; overlap, not count, is what confuses agents (OpenAI)."))
    return out


# ------------------------------------------------------------------ build

def build_report_card(p: WorkloadProfile, scan: ScanResult | None = None, traces: TraceSet | None = None, rec: "Recommendation | None" = None) -> ReportCard:
    d = dict(scan.design) if scan and scan.design else {}
    if not d and rec is not None:
        d = {"tool_count": p.tool_count, "tool_overlap_count": 3 if p.tool_overlap else 0, "delegation_depth": 0}
    t_lvl = task_level(p)
    d_lvl = design_level(d) if d else max(1, min(5, (2 if p.uses_tools else 1)))
    b = compute_behaviour(traces) if traces and len(traces) else None
    b_lvl = behaviour_level(b) if b else None
    mismatches = find_mismatches(t_lvl, d_lvl, b_lvl, d, b, p, rec)
    dims = [_quality(b, p), _reliability(b, d, p), _efficiency(b, p, rec), _latency(b, p), _governance(d, p, b), _fit(t_lvl, d_lvl, b_lvl, mismatches)]
    scored = [x for x in dims if x.score is not None]
    overall = round(sum(x.score * x.weight for x in scored) / sum(x.weight for x in scored), 1) if scored else None
    agents = _agent_cards(traces, rec, p) if traces and len(traces) else []
    mode = "full" if b else "design-time"
    summary = _summary(p, mode, t_lvl, d_lvl, b_lvl, overall, dims, mismatches, agents)
    return ReportCard(p.name, mode, t_lvl, d_lvl, b_lvl, d, b, dims, mismatches, agents, overall, letter(overall), summary,
                      list(traces.warnings) if traces else [])


def _agent_cards(traces: TraceSet, rec: "Recommendation | None", p: WorkloadProfile) -> list[AgentCard]:
    cards = []
    roles = {c.id: c for c in rec.plan.components} if rec else {}
    for a in traces.agents():
        b = compute_behaviour(traces, agent=a)
        comp = roles.get(a) or next((c for cid, c in roles.items() if a.startswith(cid.split("_")[0])), None)
        f: list[str] = []
        score = 100.0
        if b.tool_error_rate > 0.05:
            score -= 15; f.append(f"tool error rate {b.tool_error_rate:.0%}")
        if b.repetition_rate > 0.1:
            score -= 20; f.append(f"repeats identical tool calls in {b.repetition_rate:.0%} of runs")
        if b.steps["cv"] > 0.8:
            score -= 15; f.append(f"step count varies widely (CV {b.steps['cv']})")
        if b.context_growth_per_step > 3000:
            score -= 10; f.append(f"context grows {b.context_growth_per_step:,.0f} tokens/step")
        if b.peak_context["max"] > 150_000:
            score -= 10; f.append(f"peak context {b.peak_context['max']:,.0f} tokens")
        if not f:
            f.append("stable: no loops, low variance, no tool errors")
        cards.append(AgentCard(a, comp.role if comp else None, comp.model_id if comp else None, b, letter(score), round(score, 1), f))
    return cards


def _summary(p, mode, t, d, b, overall, dims, mismatches, agents) -> str:
    parts = [f"{'Design-time' if mode == 'design-time' else 'Full'} report card for **{p.name}**: overall **{letter(overall)}** ({overall if overall is not None else 'n/a'}/100)."
             if overall is not None else f"Design-time report card for **{p.name}** (no traces: quality, reliability, efficiency and latency are not graded)."]
    parts.append(f"Task complexity {t} ({LEVEL_NAMES[t]}), design {d} ({LEVEL_NAMES[d]})" + (f", behaviour {b} ({LEVEL_NAMES[b]})." if b else "."))
    high = [m for m in mismatches if m.severity == "high"]
    if high:
        parts.append("Priority: " + "; ".join(m.title for m in high) + ".")
    worst = sorted([x for x in dims if x.score is not None], key=lambda x: x.score)[:1]
    if worst and worst[0].score < 70:
        parts.append(f"Weakest dimension: {worst[0].name} ({worst[0].grade}).")
    if agents:
        weak = [a for a in agents if a.grade in ("D", "F")]
        if weak:
            parts.append("Agents needing attention: " + ", ".join(a.agent for a in weak) + ".")
    return " ".join(parts)


# ------------------------------------------------------------------ markdown

def report_card_markdown(c: ReportCard) -> str:
    out = [f"## Agent report card: {c.name}\n", c.summary, ""]
    out.append("| Dimension | Grade | Score | Weight |\n|---|---|---|---|")
    for d in c.dimensions:
        out.append(f"| {d.name} | **{d.grade}** | {d.score if d.score is not None else 'n/a'} | {d.weight:.0f} |")
    out.append(f"| **Overall** | **{c.overall_grade}** | {c.overall_score if c.overall_score is not None else 'n/a'} | |\n")
    out.append("### Complexity\n")
    out.append("| Axis | Level | Basis |\n|---|---|---|")
    out.append(f"| Task | {c.task_level} ({LEVEL_NAMES[c.task_level]}) | profile: complexity, breadth, sources, parallel sub-tasks, context pressure |")
    dm = c.design_metrics
    out.append(f"| Design | {c.design_level} ({LEVEL_NAMES[c.design_level]}) | {dm.get('tool_count', 0)} tools ({dm.get('tool_overlap_count', 0)} overlapping), delegation depth {dm.get('delegation_depth', 0)}, "
               f"{'handoffs, ' if dm.get('handoffs') else ''}{'router, ' if dm.get('router') else ''}{'evaluator loop, ' if dm.get('evaluator_loop') else ''}{'fan-out, ' if dm.get('parallel_fanout') else ''}"
               f"{dm.get('prompt_definitions', 0)} prompt definitions (~{dm.get('prompt_chars', 0):,} chars) |")
    if c.behaviour_level:
        b = c.behaviour
        out.append(f"| Behaviour | {c.behaviour_level} ({LEVEL_NAMES[c.behaviour_level]}) | steps p50 {b.steps['p50']}, p95 {b.steps['p95']}, CV {b.steps['cv']}; branching {b.branching_factor}; "
                   f"{b.spawns_per_run} spawns and {b.handoffs_per_run} handoffs per run |")
    out.append("")
    if c.mismatches:
        out.append("### Mismatches\n")
        for m in c.mismatches:
            out.append(f"- **{m.title}** ({m.severity}): {m.detail} _Action: {m.action}_")
        out.append("")
    out.append("### Findings by dimension\n")
    for d in c.dimensions:
        if d.findings:
            out.append(f"**{d.name}** ({d.grade})")
            for f in d.findings:
                out.append(f"- {f}")
            out.append("")
    if c.behaviour:
        b = c.behaviour
        out.append("### Behavioural metrics\n")
        out.append("| Metric | Value |\n|---|---|")
        rows = [("Runs / tasks", f"{b.runs} / {b.tasks}"), ("Success rate", f"{b.success_rate:.0%}" if b.success_rate is not None else "n/a"),
                ("Consistency across repeated runs", f"{b.consistency:.0%}" if b.consistency is not None else "n/a"),
                ("All runs pass (repeated tasks)", f"{b.pass_all_runs:.0%}" if b.pass_all_runs is not None else "n/a"),
                ("Steps per run (p50 / p95 / CV)", f"{b.steps['p50']} / {b.steps['p95']} / {b.steps['cv']}"),
                ("LLM calls per run (mean)", b.llm_calls["mean"]), ("Tool calls per run (mean)", b.tool_calls["mean"]), ("Distinct tools used", b.distinct_tools),
                ("Tool error rate", f"{b.tool_error_rate:.1%}"), ("Runs with repeated identical calls", f"{b.repetition_rate:.0%}"),
                ("Runs ended by a limit", f"{b.termination_limit_rate:.0%}"), ("Runs ended by error/timeout", f"{b.timeout_error_rate:.0%}"),
                ("Handoffs / spawns per run", f"{b.handoffs_per_run} / {b.spawns_per_run}"), ("Runs with verification / human step", f"{b.verify_rate:.0%} / {b.human_rate:.0%}"),
                ("Branching factor", b.branching_factor), ("Trajectory diversity", b.trajectory_diversity if b.trajectory_diversity is not None else "n/a"),
                ("Tokens per run (mean / p95)", f"{b.tokens_per_run['mean']:,.0f} / {b.tokens_per_run['p95']:,.0f}"), ("Peak context (max)", f"{b.peak_context['max']:,.0f}"),
                ("Context growth per step", f"{b.context_growth_per_step:,.0f}"), ("Latency p50 / p95", f"{b.latency_ms['p50'] / 1000:.1f}s / {b.latency_ms['p95'] / 1000:.1f}s"),
                ("Cost per run / per completed task", f"${b.cost_per_run:.4f} / " + (f"${b.cost_per_completed_task:.4f}" if b.cost_per_completed_task is not None else "n/a")),
                ("Successes per 1k tokens", b.successes_per_1k_tokens if b.successes_per_1k_tokens is not None else "n/a")]
        for k, v in rows:
            out.append(f"| {k} | {v} |")
        out.append("")
    if c.agents:
        out.append("### Per-agent cards\n")
        out.append("| Agent | Role | Model | Grade | Steps p50/p95 | Tool calls | Tool errors | Loops | Tokens/run | Latency p50 | Findings |\n|---|---|---|---|---|---|---|---|---|---|---|")
        for a in c.agents:
            b = a.behaviour
            out.append(f"| {a.agent} | {a.role or '-'} | {a.model or '-'} | **{a.grade}** | {b.steps['p50']}/{b.steps['p95']} | {b.tool_calls['mean']} | {b.tool_error_rate:.0%} | {b.repetition_rate:.0%} | {b.tokens_per_run['mean']:,.0f} | {b.latency_ms['p50'] / 1000:.1f}s | {'; '.join(a.findings)} |")
        out.append("")
    if c.trace_warnings:
        out.append("Trace notes: " + "; ".join(c.trace_warnings) + "\n")
    return "\n".join(out)
