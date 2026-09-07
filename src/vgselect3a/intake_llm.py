"""Optional: infer a WorkloadProfile from a free-text description with Claude.

Requires `pip install vgselect[llm]` and credentials resolvable by the
Anthropic SDK (ANTHROPIC_API_KEY, or an `ant auth login` profile).

The structured-output schema is generated from FIELD_SPECS so the model can
only produce valid enum values and ranges; the result is validated again by
WorkloadProfile.
"""

from __future__ import annotations

import json
from typing import Any

from .profile import WorkloadProfile, json_schema

SYSTEM = """You are an experienced architect of LLM agent systems. You read a product/engineering
description of an agentic application and fill in a structured workload profile that a rule engine
will use to recommend an architecture (single call, single agent, prompt chain, router, parallel
sectioning, voting, evaluator-optimizer, orchestrator-workers, hierarchical, handoffs).

Estimate every field from the description. Where the text is silent, infer a realistic value from
the kind of application and say so in `assumptions`. Be concrete with numbers (tool calls per task,
tokens read per task, latency budget in seconds). List concrete `domains`, `sources`, `tools`,
`subtasks` and `sections` names when the text implies them, so the plan can use real names."""


def _schema() -> dict[str, Any]:
    base = json_schema()
    props = dict(base["properties"])
    for key, desc in (
        ("domains", "Distinct domains / skill areas named or implied by the description."),
        ("sources", "Distinct knowledge sources (databases, wikis, APIs, the web) named or implied."),
        ("tools", "Tools/functions named or implied."),
        ("subtasks", "Independent sub-tasks one request can be split into."),
        ("sections", "Independent sections when work can be partitioned ahead of time."),
        ("assumptions", "Short statements of what you inferred rather than read."),
    ):
        props[key] = {"type": "array", "items": {"type": "string"}, "description": desc}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def profile_from_description(text: str, model: str = "claude-opus-5") -> WorkloadProfile:
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover
        raise SystemExit("The `describe` command needs the Anthropic SDK: pip install 'vgselect[llm]'") from e

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": _schema()}},
        system=SYSTEM,
        messages=[{"role": "user", "content": f"<description>\n{text}\n</description>\n\nFill in the workload profile."}],
    )
    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        raise SystemExit(f"The model declined to process this description ({getattr(detail, 'category', None)}).")
    raw = next(b.text for b in response.content if b.type == "text")
    data = json.loads(raw)
    extra_keys = ("domains", "sources", "tools", "subtasks", "sections", "assumptions")
    extras = {k: data.pop(k) for k in extra_keys if k in data}
    profile = WorkloadProfile.from_dict(data)
    profile.extra.update({k: v for k, v in extras.items() if v})
    return profile
