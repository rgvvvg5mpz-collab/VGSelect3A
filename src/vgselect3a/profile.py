"""Workload profile: the structured inputs the recommender reasons over.

Every field has a FieldSpec so the CLI wizard, JSON loader, LLM intake and
docs all share one definition.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, asdict
from typing import Any


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str  # "enum" | "int" | "float" | "bool" | "str"
    description: str
    choices: tuple[str, ...] = ()
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    group: str = "task"


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec("name", "str", "Short name for the application.", default="app", group="meta"),
    FieldSpec("description", "str", "One or two sentences describing what the application does.", default="", group="meta"),
    # --- Task shape -----------------------------------------------------------------
    FieldSpec(
        "task_complexity", "enum",
        "How much reasoning a single request needs. "
        "trivial: lookup/classification; simple: one-step generation; moderate: a few dependent steps; "
        "complex: many dependent steps with judgment; open_ended: the steps cannot be enumerated in advance.",
        choices=("trivial", "simple", "moderate", "complex", "open_ended"), default="moderate",
    ),
    FieldSpec(
        "steps_predictable", "bool",
        "Can the sequence of steps be fixed in code ahead of time (workflow) rather than decided by the model at run time (agent)?",
        default=True,
    ),
    FieldSpec(
        "scope_breadth", "int",
        "Number of distinct domains or skill areas one request can span (e.g. code + security + docs = 3).",
        default=1, minimum=1, maximum=20,
    ),
    FieldSpec(
        "parallel_subtasks", "int",
        "Typical number of independent sub-tasks in one request that could run at the same time (0 or 1 = none).",
        default=1, minimum=0, maximum=100,
    ),
    FieldSpec(
        "output_type", "enum",
        "Primary deliverable of a request.",
        choices=("short_answer", "structured_data", "long_document", "code_change", "action"), default="short_answer",
    ),
    # --- Tools ------------------------------------------------------------------------
    FieldSpec("tool_count", "int", "Number of distinct tools/functions available to the application.", default=0, minimum=0, maximum=500, group="tools"),
    FieldSpec("tool_calls_per_task", "int", "Expected average number of tool calls per request.", default=0, minimum=0, maximum=1000, group="tools"),
    FieldSpec(
        "tool_dependency", "enum",
        "Are tool calls mostly sequential (each depends on the last), independent (can be issued together), or mixed?",
        choices=("sequential", "mixed", "independent"), default="sequential", group="tools",
    ),
    FieldSpec(
        "tool_side_effects", "enum",
        "Worst-case side effect of the tools: read_only, reversible_writes (drafts, files under VCS), irreversible (send email, payments, deletes).",
        choices=("read_only", "reversible_writes", "irreversible"), default="read_only", group="tools",
    ),
    FieldSpec(
        "tool_overlap", "bool",
        "Do several tools have similar or overlapping purposes (so the model may pick the wrong one)? OpenAI's split trigger is overlap, not count.",
        default=False, group="tools",
    ),
    FieldSpec("tool_latency_s", "float", "Average wall-clock latency of one tool call in seconds.", default=0.5, minimum=0.0, maximum=600.0, group="tools"),
    # --- Knowledge --------------------------------------------------------------------
    FieldSpec("knowledge_sources", "int", "Number of distinct knowledge sources (vector stores, wikis, APIs, the web) that must be consulted.", default=0, minimum=0, maximum=50, group="knowledge"),
    FieldSpec(
        "retrieval_depth", "enum",
        "none: no retrieval; single_lookup: one query answers it; multi_hop: follow-up queries depend on earlier results; "
        "exhaustive: breadth-first coverage of a topic across many documents.",
        choices=("none", "single_lookup", "multi_hop", "exhaustive"), default="none", group="knowledge",
    ),
    FieldSpec("context_tokens_per_task", "int", "Approximate tokens of documents/tool output that must be read to answer one request.", default=2000, minimum=0, maximum=50_000_000, group="knowledge"),
    # --- Quality ----------------------------------------------------------------------
    FieldSpec("accuracy_priority", "int", "1 = best effort is fine ... 5 = errors are very costly (money, safety, compliance).", default=3, minimum=1, maximum=5, group="quality"),
    FieldSpec(
        "single_agent_baseline", "float",
        "Measured accuracy (0.0-1.0) of a single agent/call on your eval, if you have one; -1 = not measured. Above ~0.45, adding agents tends to hurt.",
        default=-1.0, minimum=-1.0, maximum=1.0, group="quality",
    ),
    FieldSpec(
        "verifiability", "enum",
        "Can an answer be checked objectively? none: purely subjective; partial: rubric/spot checks; strong: tests, schemas, ground truth.",
        choices=("none", "partial", "strong"), default="partial", group="quality",
    ),
    FieldSpec(
        "error_recoverability", "enum",
        "How easily a wrong action can be caught and undone: easy (review before commit), moderate, hard (acts on the world immediately).",
        choices=("easy", "moderate", "hard"), default="easy", group="quality",
    ),
    # --- Operating constraints ----------------------------------------------------------
    FieldSpec("latency_budget_s", "float", "Target end-to-end latency for one request, in seconds (p50 is fine).", default=30.0, minimum=0.5, maximum=86_400.0, group="ops"),
    FieldSpec(
        "interaction", "enum",
        "single_turn: one request, one answer; multi_turn: conversational; long_running: one task spanning many minutes/hours.",
        choices=("single_turn", "multi_turn", "long_running"), default="single_turn", group="ops",
    ),
    FieldSpec("requests_per_day", "int", "Expected volume, requests per day.", default=1000, minimum=0, maximum=1_000_000_000, group="ops"),
    FieldSpec("cost_sensitivity", "int", "1 = cost is not a concern ... 5 = cost dominates the decision.", default=3, minimum=1, maximum=5, group="ops"),
    FieldSpec("human_in_loop", "bool", "Is a human available to approve risky actions during a request?", default=False, group="ops"),
)

SPEC_BY_NAME = {s.name: s for s in FIELD_SPECS}


@dataclass
class WorkloadProfile:
    name: str = "app"
    description: str = ""
    task_complexity: str = "moderate"
    steps_predictable: bool = True
    scope_breadth: int = 1
    parallel_subtasks: int = 1
    output_type: str = "short_answer"
    tool_count: int = 0
    tool_calls_per_task: int = 0
    tool_dependency: str = "sequential"
    tool_side_effects: str = "read_only"
    tool_overlap: bool = False
    tool_latency_s: float = 0.5
    knowledge_sources: int = 0
    retrieval_depth: str = "none"
    context_tokens_per_task: int = 2000
    accuracy_priority: int = 3
    single_agent_baseline: float = -1.0
    verifiability: str = "partial"
    error_recoverability: str = "easy"
    latency_budget_s: float = 30.0
    interaction: str = "single_turn"
    requests_per_day: int = 1000
    cost_sensitivity: int = 3
    human_in_loop: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    # ------------------------------------------------------------------ validation
    def validate(self) -> None:
        problems: list[str] = []
        for spec in FIELD_SPECS:
            value = getattr(self, spec.name)
            if spec.kind == "enum" and value not in spec.choices:
                problems.append(f"{spec.name}={value!r} not in {spec.choices}")
            elif spec.kind == "int":
                if isinstance(value, bool) or not isinstance(value, int):
                    problems.append(f"{spec.name} must be an int, got {value!r}")
                elif spec.minimum is not None and value < spec.minimum:
                    problems.append(f"{spec.name}={value} below minimum {spec.minimum}")
                elif spec.maximum is not None and value > spec.maximum:
                    problems.append(f"{spec.name}={value} above maximum {spec.maximum}")
            elif spec.kind == "float":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    problems.append(f"{spec.name} must be a number, got {value!r}")
                elif spec.minimum is not None and value < spec.minimum:
                    problems.append(f"{spec.name}={value} below minimum {spec.minimum}")
                elif spec.maximum is not None and value > spec.maximum:
                    problems.append(f"{spec.name}={value} above maximum {spec.maximum}")
            elif spec.kind == "bool" and not isinstance(value, bool):
                problems.append(f"{spec.name} must be a bool, got {value!r}")
        if problems:
            raise ValueError("Invalid WorkloadProfile: " + "; ".join(problems))

    # ------------------------------------------------------------------ (de)serialisation
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkloadProfile":
        known = {f.name for f in fields(cls)} - {"extra"}
        kwargs: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for key, value in data.items():
            if key in known:
                spec = SPEC_BY_NAME.get(key)
                kwargs[key] = _coerce(spec, value) if spec else value
            elif key == "extra" and isinstance(value, dict):
                extra.update(value)
            else:
                extra[key] = value
        return cls(extra=extra, **kwargs)

    @classmethod
    def from_json(cls, text: str) -> "WorkloadProfile":
        return cls.from_dict(json.loads(text))

    def to_dict(self) -> dict[str, Any]:
        """Flat dict: extras (domains, sources, tools, ...) sit at the top level,
        the same shape as the example profile files."""
        d = asdict(self)
        extra = d.pop("extra")
        for k, v in extra.items():
            d.setdefault(k, v)
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    # ------------------------------------------------------------------ derived signals
    @property
    def complexity_score(self) -> int:
        return ("trivial", "simple", "moderate", "complex", "open_ended").index(self.task_complexity)

    @property
    def uses_tools(self) -> bool:
        return self.tool_count > 0 and self.tool_calls_per_task > 0

    @property
    def is_interactive(self) -> bool:
        return self.latency_budget_s <= 10.0

    @property
    def context_pressure(self) -> str:
        """How hard the per-task reading load pushes on one context window."""
        t = self.context_tokens_per_task
        if t < 20_000:
            return "low"
        if t < 120_000:
            return "medium"
        if t < 400_000:
            return "high"
        return "extreme"


def _coerce(spec: FieldSpec, value: Any) -> Any:
    if spec.kind == "int" and isinstance(value, (float, str)) and not isinstance(value, bool):
        try:
            return int(value)
        except ValueError:
            return value
    if spec.kind == "float" and isinstance(value, (int, str)) and not isinstance(value, bool):
        try:
            return float(value)
        except ValueError:
            return value
    if spec.kind == "bool" and isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y")
    return value


def json_schema() -> dict[str, Any]:
    """JSON Schema for a profile (used by the LLM intake and for docs)."""
    props: dict[str, Any] = {}
    for spec in FIELD_SPECS:
        p: dict[str, Any] = {"description": spec.description}
        if spec.kind == "enum":
            p["type"] = "string"
            p["enum"] = list(spec.choices)
        elif spec.kind == "int":
            p["type"] = "integer"
        elif spec.kind == "float":
            p["type"] = "number"
        elif spec.kind == "bool":
            p["type"] = "boolean"
        else:
            p["type"] = "string"
        if spec.minimum is not None:
            p["minimum"] = spec.minimum
        if spec.maximum is not None:
            p["maximum"] = spec.maximum
        props[spec.name] = p
    return {
        "type": "object",
        "properties": props,
        "required": [s.name for s in FIELD_SPECS],
        "additionalProperties": False,
    }
