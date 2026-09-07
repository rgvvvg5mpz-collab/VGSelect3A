"""Models, effort and limits per role. Generated from the VG Select: 3A plan."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    name: str
    model: str          # model id in your ecosystem catalog
    provider: str       # value for langchain.chat_models.init_chat_model(model_provider=...)
    effort: str
    tier: str
    fallback: str | None = None   # different provider where possible, for outages/refusals


# Chosen by VG Select: 3A from the model catalog and policy; see ARCHITECTURE.md "Model selection per role".
ROLES: dict[str, Role] = {
    "extract": Role(name='Extract', model='claude-sonnet-5', provider='anthropic', effort='high', tier='sonnet', fallback='claude-haiku-4-5'),
"finalize": Role(name='Finalize', model='claude-sonnet-5', provider='anthropic', effort='high', tier='opus', fallback='claude-haiku-4-5'),
}

# Termination limits (MAST: "unaware of termination" and step repetition are ~28% of multi-agent failures).
RECURSION_LIMIT = 25   # LangGraph steps per request
MAX_TOOL_CALLS = 3          # per agent per request
MAX_ITERATIONS = 2             # evaluator / refinement loops
MAX_WORKERS = 2
LATENCY_BUDGET_S = 60.0

# Effort / reasoning controls are provider-specific and passed through provider kwargs
# (e.g. Anthropic: model_kwargs={"output_config": {"effort": "high"}}; OpenAI reasoning models: reasoning_effort=...).
# Adaptive thinking is the default on current Claude models.
DEFAULT_MAX_TOKENS = 4096
