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
    "router": Role(name='Router', model='claude-haiku-4-5', provider='anthropic', effort='n/a', tier='haiku', fallback='claude-sonnet-5'),
"handler_1": Role(name='financial planning specialist', model='acme-onprem-70b', provider='openai', effort='n/a', tier='opus', fallback='claude-sonnet-5'),
"handler_2": Role(name='tax specialist', model='acme-onprem-70b', provider='openai', effort='n/a', tier='opus', fallback='claude-sonnet-5'),
"handler_3": Role(name='risk specialist', model='acme-onprem-70b', provider='openai', effort='n/a', tier='opus', fallback='claude-sonnet-5'),
"handler_4": Role(name='products specialist', model='acme-onprem-70b', provider='openai', effort='n/a', tier='opus', fallback='claude-sonnet-5'),
}

# Termination limits (MAST: "unaware of termination" and step repetition are ~28% of multi-agent failures).
RECURSION_LIMIT = 35   # LangGraph steps per request
MAX_TOOL_CALLS = 5          # per agent per request
MAX_ITERATIONS = 3             # evaluator / refinement loops
MAX_WORKERS = 2
LATENCY_BUDGET_S = 15.0

# Effort / reasoning controls are provider-specific and passed through provider kwargs
# (e.g. Anthropic: model_kwargs={"output_config": {"effort": "high"}}; OpenAI reasoning models: reasoning_effort=...).
# Adaptive thinking is the default on current Claude models.
DEFAULT_MAX_TOKENS = 4096
