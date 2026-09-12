"""Run-time traces: the input for behavioural complexity and the report card.

Native format: JSON Lines, one record per task run (schema "vgselect-trace/1"):

    {"schema": "vgselect-trace/1", "task_id": "t-42", "run_id": "r-1", "success": true,
     "terminated_by": "end_turn",            # end_turn | limit | error | timeout | human
     "latency_ms": 8400, "cost_usd": 0.031,  # optional; derived from steps when absent
     "steps": [
       {"agent": "lead",     "type": "llm",     "input_tokens": 3100, "output_tokens": 220, "latency_ms": 1800},
       {"agent": "lead",     "type": "spawn",   "name": "worker_1"},
       {"agent": "worker_1", "type": "tool",    "name": "search_kb", "args_hash": "a1", "latency_ms": 300, "error": false},
       {"agent": "worker_1", "type": "llm",     "input_tokens": 4800, "output_tokens": 500, "latency_ms": 2600},
       {"agent": "lead",     "type": "handoff", "name": "billing"},
       {"agent": "lead",     "type": "verify",  "passed": true},
       {"agent": "lead",     "type": "human",   "name": "approval", "approved": true}
     ]}

Step types: llm, tool, spawn, handoff, verify, human, other. `agent` is the role
or agent name that took the step (omit for single-agent systems).

Adapters (best effort, documented in docs/REPORT_CARD.html): LangSmith-style run
exports (nested `child_runs` with `run_type`) and OpenTelemetry GenAI spans
(`gen_ai.*` attributes) are converted to the native shape by `load_traces`.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

STEP_TYPES = ("llm", "tool", "spawn", "handoff", "verify", "human", "other")


@dataclass
class Step:
    type: str
    agent: str = "agent"
    name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    error: bool = False
    args_hash: str = ""
    passed: bool | None = None
    cost_usd: float = 0.0

    @property
    def action(self) -> str:
        return f"{self.type}:{self.name}" if self.name else self.type


@dataclass
class TaskRun:
    task_id: str
    run_id: str
    success: bool | None
    terminated_by: str
    steps: list[Step]
    latency_ms: float
    cost_usd: float

    @property
    def agents(self) -> list[str]:
        seen: list[str] = []
        for s in self.steps:
            if s.agent not in seen:
                seen.append(s.agent)
        return seen


@dataclass
class TraceSet:
    runs: list[TaskRun]
    source: str = ""
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.runs)

    def agents(self) -> list[str]:
        seen: list[str] = []
        for r in self.runs:
            for a in r.agents:
                if a not in seen:
                    seen.append(a)
        return seen


# ------------------------------------------------------------------ parsing

def _step_from_dict(d: dict[str, Any], default_agent: str = "agent") -> Step:
    t = str(d.get("type", "other")).lower()
    if t not in STEP_TYPES:
        t = "other"
    return Step(
        type=t, agent=str(d.get("agent") or default_agent), name=str(d.get("name") or ""),
        input_tokens=int(d.get("input_tokens") or 0), output_tokens=int(d.get("output_tokens") or 0),
        latency_ms=float(d.get("latency_ms") or 0.0), error=bool(d.get("error", False)),
        args_hash=str(d.get("args_hash") or ""), passed=d.get("passed"), cost_usd=float(d.get("cost_usd") or 0.0),
    )


def _run_from_native(d: dict[str, Any], idx: int) -> TaskRun:
    steps = [_step_from_dict(s, str(d.get("agent") or "agent")) for s in d.get("steps", [])]
    latency = float(d.get("latency_ms") or sum(s.latency_ms for s in steps))
    cost = float(d.get("cost_usd") or sum(s.cost_usd for s in steps))
    success = d.get("success")
    return TaskRun(str(d.get("task_id") or f"task-{idx}"), str(d.get("run_id") or f"run-{idx}"),
                   None if success is None else bool(success), str(d.get("terminated_by") or "end_turn"), steps, latency, cost)


def _run_from_langsmith(d: dict[str, Any], idx: int) -> TaskRun:
    """Nested run export: {name, run_type, start_time, end_time, child_runs:[...], outputs, error, extra}."""
    steps: list[Step] = []

    def walk(node: dict[str, Any], agent: str) -> None:
        rt = str(node.get("run_type", "")).lower()
        name = str(node.get("name") or "")
        usage = node.get("usage_metadata") or (node.get("extra") or {}).get("usage") or {}
        lat = 0.0
        try:
            from datetime import datetime
            if node.get("start_time") and node.get("end_time"):
                lat = (datetime.fromisoformat(node["end_time"]) - datetime.fromisoformat(node["start_time"])).total_seconds() * 1000
        except (ValueError, TypeError):
            pass
        if rt == "llm":
            steps.append(Step("llm", agent, name, int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
                              int(usage.get("output_tokens") or usage.get("completion_tokens") or 0), lat, bool(node.get("error"))))
        elif rt == "tool":
            steps.append(Step("tool", agent, name, 0, 0, lat, bool(node.get("error")), _hash(node.get("inputs"))))
        elif rt in ("chain", "agent") and name and name != agent and node.get("child_runs"):
            agent = name  # a nested chain/agent run becomes the agent for its children
        for ch in node.get("child_runs") or []:
            walk(ch, agent)

    walk(d, str(d.get("name") or "agent"))
    lat = sum(s.latency_ms for s in steps)
    return TaskRun(str(d.get("id") or f"task-{idx}"), str(d.get("id") or f"run-{idx}"), None if d.get("error") is None and "outputs" not in d else not d.get("error"),
                   "error" if d.get("error") else "end_turn", steps, lat, 0.0)


def _runs_from_otel(spans: list[dict[str, Any]]) -> list[TaskRun]:
    """Flat span list with `trace_id`, `name`, `attributes` (gen_ai.*), `start_time_unix_nano`/`end_time_unix_nano` or `duration_ms`."""
    by_trace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sp in spans:
        by_trace[str(sp.get("trace_id") or sp.get("traceId") or "trace")].append(sp)
    runs = []
    for i, (tid, sps) in enumerate(by_trace.items()):
        sps.sort(key=lambda s: s.get("start_time_unix_nano") or s.get("start_time") or 0)
        steps = []
        for sp in sps:
            a = sp.get("attributes") or {}
            op = str(a.get("gen_ai.operation.name") or "").lower()
            agent = str(a.get("gen_ai.agent.name") or a.get("agent") or "agent")
            dur = float(sp.get("duration_ms") or 0.0)
            if not dur and sp.get("start_time_unix_nano") and sp.get("end_time_unix_nano"):
                dur = (float(sp["end_time_unix_nano"]) - float(sp["start_time_unix_nano"])) / 1e6
            err = str(sp.get("status", {}).get("code", "")).upper() == "ERROR" if isinstance(sp.get("status"), dict) else False
            if op in ("chat", "text_completion", "generate_content"):
                steps.append(Step("llm", agent, str(a.get("gen_ai.request.model") or ""), int(a.get("gen_ai.usage.input_tokens") or 0), int(a.get("gen_ai.usage.output_tokens") or 0), dur, err))
            elif op == "execute_tool":
                steps.append(Step("tool", agent, str(a.get("gen_ai.tool.name") or sp.get("name") or ""), 0, 0, dur, err, _hash(a.get("gen_ai.tool.call.arguments"))))
            elif op in ("create_agent", "invoke_agent") and a.get("gen_ai.agent.name"):
                steps.append(Step("spawn", agent, str(a.get("gen_ai.agent.name")), 0, 0, dur, err))
        runs.append(TaskRun(tid, tid, None, "end_turn", steps, sum(s.latency_ms for s in steps), 0.0))
    return runs


def _hash(obj: Any) -> str:
    if obj is None:
        return ""
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:10]


def parse_records(records: Iterable[Any], source: str = "") -> TraceSet:
    runs: list[TaskRun] = []
    warnings: list[str] = []
    recs = list(records)
    if recs and all(isinstance(r, dict) and ("attributes" in r or "trace_id" in r or "traceId" in r) and "steps" not in r for r in recs):
        runs = _runs_from_otel(recs)
        warnings.append("Interpreted input as OpenTelemetry GenAI spans; success/termination are unknown unless spans carry them.")
    else:
        for i, r in enumerate(recs):
            if not isinstance(r, dict):
                warnings.append(f"record {i}: not an object, skipped"); continue
            if "steps" in r:
                runs.append(_run_from_native(r, i))
            elif "run_type" in r or "child_runs" in r:
                runs.append(_run_from_langsmith(r, i))
            else:
                warnings.append(f"record {i}: unrecognised shape (no `steps`, `run_type` or span attributes), skipped")
    if not runs:
        warnings.append("No usable trace records.")
    return TraceSet(runs, source, warnings)


def load_traces(path: str | Path) -> TraceSet:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    stripped = text.strip()
    if stripped.startswith("["):
        return parse_records(json.loads(stripped), str(p))
    if stripped.startswith("{") and "\n" not in stripped:
        d = json.loads(stripped)
        return parse_records(d.get("runs") or d.get("spans") or d.get("records") or [d], str(p))
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    return parse_records(records, str(p))


# ------------------------------------------------------------------ metrics

def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


def _dist(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "std": 0.0, "cv": 0.0, "max": 0.0}
    mean = statistics.fmean(values)
    std = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {"mean": round(mean, 2), "p50": round(_pct(values, 0.5), 2), "p95": round(_pct(values, 0.95), 2), "std": round(std, 2),
            "cv": round(std / mean, 2) if mean else 0.0, "max": round(max(values), 2)}


@dataclass
class BehaviourMetrics:
    runs: int
    tasks: int
    success_rate: float | None
    steps: dict[str, float]
    llm_calls: dict[str, float]
    tool_calls: dict[str, float]
    distinct_tools: int
    tool_error_rate: float
    repetition_rate: float          # share of runs with a repeated identical action (loop signal)
    termination_limit_rate: float   # share of runs ended by a step/recursion limit
    timeout_error_rate: float
    handoffs_per_run: float
    spawns_per_run: float
    verify_rate: float              # share of runs with a verification step
    human_rate: float
    branching_factor: float         # mean distinct successors per action
    trajectory_diversity: float | None   # mean Jaccard distance between runs of the same task
    consistency: float | None       # share of repeated tasks whose runs all agree on success
    pass_all_runs: float | None     # share of repeated tasks where every run succeeded
    tokens_per_run: dict[str, float]
    peak_context: dict[str, float]
    context_growth_per_step: float
    latency_ms: dict[str, float]
    cost_per_run: float
    cost_per_completed_task: float | None
    successes_per_1k_tokens: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_behaviour(ts: TraceSet, agent: str | None = None) -> BehaviourMetrics:
    runs = ts.runs
    per_run_steps = []
    for r in runs:
        steps = [s for s in r.steps if agent is None or s.agent == agent]
        per_run_steps.append((r, steps))
    if agent is not None:
        per_run_steps = [(r, s) for r, s in per_run_steps if s]
    n = len(per_run_steps)
    if n == 0:
        return compute_behaviour(TraceSet([]), None) if runs else BehaviourMetrics(0, 0, None, _dist([]), _dist([]), _dist([]), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, None, None, None, _dist([]), _dist([]), 0, _dist([]), 0, None, None)
    step_counts, llm_counts, tool_counts, tokens, peaks, lats, costs = [], [], [], [], [], [], []
    tool_total = tool_err = repeated = limit = toerr = handoffs = spawns = verify = human = 0
    growths: list[float] = []
    successes = []
    transitions: dict[str, Counter] = defaultdict(Counter)
    tools_seen: set[str] = set()
    by_task: dict[str, list[tuple[bool | None, set[str]]]] = defaultdict(list)
    for r, steps in per_run_steps:
        step_counts.append(len(steps))
        llm = [s for s in steps if s.type == "llm"]
        tools = [s for s in steps if s.type == "tool"]
        llm_counts.append(len(llm)); tool_counts.append(len(tools))
        tool_total += len(tools); tool_err += sum(1 for s in tools if s.error)
        tools_seen.update(s.name for s in tools if s.name)
        tk = sum(s.input_tokens + s.output_tokens for s in steps)
        tokens.append(tk)
        inputs = [s.input_tokens for s in llm if s.input_tokens]
        peaks.append(max(inputs) if inputs else 0)
        if len(inputs) >= 2:
            growths.append((inputs[-1] - inputs[0]) / (len(inputs) - 1))
        prev = None
        rep = False
        for s in steps:
            key = (s.type, s.name, s.args_hash)
            if prev is not None:
                transitions[prev[0] + ":" + prev[1]][s.action] += 1
                if key == prev and s.type in ("tool", "llm") and (s.args_hash or s.type == "llm") and s.type == "tool":
                    rep = True
            prev = key
        repeated += 1 if rep else 0
        limit += 1 if r.terminated_by == "limit" else 0
        toerr += 1 if r.terminated_by in ("error", "timeout") else 0
        handoffs += sum(1 for s in steps if s.type == "handoff")
        spawns += sum(1 for s in steps if s.type == "spawn")
        verify += 1 if any(s.type == "verify" for s in steps) else 0
        human += 1 if any(s.type == "human" for s in steps) else 0
        lat = sum(s.latency_ms for s in steps) if agent is not None else (r.latency_ms or sum(s.latency_ms for s in steps))
        lats.append(lat)
        cost = sum(s.cost_usd for s in steps) if agent is not None or not r.cost_usd else r.cost_usd
        costs.append(cost)
        if r.success is not None:
            successes.append(1.0 if r.success else 0.0)
        by_task[r.task_id].append((r.success, {s.action for s in steps}))
    branching_vals = [len(c) for c in transitions.values() if sum(c.values()) >= 3]
    branching = round(statistics.fmean(branching_vals), 2) if branching_vals else 1.0
    repeated_tasks = {t: v for t, v in by_task.items() if len(v) >= 2}
    diversity = consistency = pass_all = None
    if repeated_tasks:
        dists, agree, allpass = [], [], []
        for v in repeated_tasks.values():
            sets = [s for _, s in v]
            for i in range(len(sets)):
                for j in range(i + 1, len(sets)):
                    u = sets[i] | sets[j]
                    dists.append(1 - len(sets[i] & sets[j]) / len(u) if u else 0.0)
            outcomes = [o for o, _ in v if o is not None]
            if outcomes:
                agree.append(1.0 if len(set(outcomes)) == 1 else 0.0)
                allpass.append(1.0 if all(outcomes) else 0.0)
        diversity = round(statistics.fmean(dists), 2) if dists else None
        consistency = round(statistics.fmean(agree), 2) if agree else None
        pass_all = round(statistics.fmean(allpass), 2) if allpass else None
    success_rate = round(statistics.fmean(successes), 3) if successes else None
    total_tokens = sum(tokens)
    completed = sum(successes) if successes else None
    return BehaviourMetrics(
        runs=n, tasks=len(by_task), success_rate=success_rate,
        steps=_dist(step_counts), llm_calls=_dist(llm_counts), tool_calls=_dist(tool_counts), distinct_tools=len(tools_seen),
        tool_error_rate=round(tool_err / tool_total, 3) if tool_total else 0.0,
        repetition_rate=round(repeated / n, 3), termination_limit_rate=round(limit / n, 3), timeout_error_rate=round(toerr / n, 3),
        handoffs_per_run=round(handoffs / n, 2), spawns_per_run=round(spawns / n, 2), verify_rate=round(verify / n, 3), human_rate=round(human / n, 3),
        branching_factor=branching, trajectory_diversity=diversity, consistency=consistency, pass_all_runs=pass_all,
        tokens_per_run=_dist(tokens), peak_context=_dist(peaks), context_growth_per_step=round(statistics.fmean(growths), 1) if growths else 0.0,
        latency_ms=_dist(lats), cost_per_run=round(statistics.fmean(costs), 5) if costs else 0.0,
        cost_per_completed_task=round(sum(costs) / completed, 5) if completed else None,
        successes_per_1k_tokens=round(1000 * completed / total_tokens, 3) if completed and total_tokens else None,
    )


# ------------------------------------------------------------------ synthetic traces (tests, case studies)

def synthesize_traces(topology_id: str, n_tasks: int = 40, runs_per_task: int = 2, seed: int = 7, quality: float = 0.85,
                      tools: list[str] | None = None, workers: int = 4, chaos: float = 0.1, tokens_scale: float = 1.0) -> TraceSet:
    """Plausible fictional traces for a topology, for demos and tests. Not real data."""
    rng = random.Random(seed)
    tools = tools or ["search", "lookup", "fetch"]
    runs: list[TaskRun] = []
    for t in range(n_tasks):
        for k in range(runs_per_task):
            steps: list[Step] = []
            base_in = int(rng.uniform(2500, 4000) * tokens_scale)

            def llm(agent: str, ctx: int, out: int) -> None:
                steps.append(Step("llm", agent, "", ctx, int(out * rng.uniform(0.7, 1.4)), rng.uniform(900, 2200) + out * 12, False, "", None, (ctx * 2 + out * 10) / 1e6))

            def tool(agent: str, name: str | None = None) -> None:
                nm = name or rng.choice(tools)
                steps.append(Step("tool", agent, nm, 0, 0, rng.uniform(150, 900), rng.random() < chaos * 0.4, _hash([nm, rng.randint(0, 6)])))

            hard = rng.random() < chaos
            if topology_id in ("single_call", "prompt_chain"):
                stages = 1 if topology_id == "single_call" else 3
                ctx = base_in
                for s in range(stages):
                    llm("agent", ctx, 300 if s < stages - 1 else 500); ctx += 400
            elif topology_id in ("single_agent", "router", "handoff_network", "evaluator_optimizer"):
                agent = "agent"
                if topology_id == "router":
                    llm("router", 900, 20); agent = rng.choice(["handler_1", "handler_2", "handler_3"])
                if topology_id == "handoff_network":
                    agent = "spec_1"
                calls = max(1, int(rng.gauss(3 if not hard else 7, 1.2)))
                ctx = base_in
                for c in range(calls):
                    llm(agent, ctx, 150); tool(agent); ctx += int(rng.uniform(600, 1800))
                    if hard and rng.random() < 0.5:
                        steps.append(Step("tool", agent, steps[-1].name, 0, 0, 400, False, steps[-1].args_hash))  # repeated call
                    if topology_id == "handoff_network" and rng.random() < 0.3:
                        steps.append(Step("handoff", agent, "spec_2")); agent = "spec_2"
                llm(agent, ctx, 350)
                if topology_id == "evaluator_optimizer":
                    passed = rng.random() < quality
                    steps.append(Step("verify", "evaluator", "", 1500, 200, 1400, False, "", passed))
                    if not passed:
                        llm(agent, ctx + 800, 350); steps.append(Step("verify", "evaluator", "", 1700, 200, 1400, False, "", True))
            else:  # orchestrator_workers / hierarchical / parallel
                llm("lead", base_in, 700)
                nw = max(1, int(rng.gauss(workers, 1)))
                for w in range(nw):
                    steps.append(Step("spawn", "lead", f"worker_{w + 1}"))
                for w in range(nw):
                    ag = f"worker_{w + 1}"
                    ctx = int(rng.uniform(2000, 3000) * tokens_scale)
                    for c in range(max(1, int(rng.gauss(4, 1.5)))):
                        llm(ag, ctx, 150); tool(ag); ctx += int(rng.uniform(1500, 4000))
                    llm(ag, ctx, 600)
                llm("lead", base_in + 700 * nw, 900)
                if rng.random() < 0.8:
                    steps.append(Step("verify", "critic", "", 2500, 300, 1800, False, "", rng.random() < 0.9))
            success = rng.random() < (quality if not hard else quality - 0.35)
            term = "limit" if (hard and rng.random() < 0.35) else ("error" if not success and rng.random() < 0.2 else "end_turn")
            runs.append(TaskRun(f"task-{t}", f"task-{t}-run-{k}", success, term, steps, sum(s.latency_ms for s in steps), sum(s.cost_usd for s in steps)))
    return TraceSet(runs, source="synthetic (fictional)")


def traces_to_jsonl(ts: TraceSet) -> str:
    lines = []
    for r in ts.runs:
        lines.append(json.dumps({"schema": "vgselect-trace/1", "task_id": r.task_id, "run_id": r.run_id, "success": r.success, "terminated_by": r.terminated_by,
                                 "latency_ms": round(r.latency_ms, 1), "cost_usd": round(r.cost_usd, 6),
                                 "steps": [{k: v for k, v in asdict(s).items() if v not in (0, 0.0, "", None, False)} for s in r.steps]}))
    return "\n".join(lines) + "\n"
