"""Role agent factory. Provider-agnostic: models come from the catalog choice in config.ROLES and are
built with langchain's init_chat_model, so Anthropic, OpenAI, Google, Bedrock, Mistral or a self-hosted
OpenAI-compatible endpoint all work. Uses langchain's create_agent (LangChain 1.x) with a fallback to
langgraph.prebuilt.create_react_agent (LangGraph 0.2/0.3)."""

from langchain.chat_models import init_chat_model

from .config import DEFAULT_MAX_TOKENS, ROLES

try:  # LangChain 1.x
    from langchain.agents import create_agent as _create_agent

    def _build(model, tools, system_prompt):
        return _create_agent(model, tools=tools, system_prompt=system_prompt)
except ImportError:  # LangGraph 0.2 / 0.3
    from langgraph.prebuilt import create_react_agent as _create_react_agent

    def _build(model, tools, system_prompt):
        return _create_react_agent(model, tools, prompt=system_prompt)


def chat_model(role_id: str, **kwargs):
    """Chat model for a role; pass use_fallback=True to build the fallback model instead."""
    role = ROLES[role_id]
    use_fallback = kwargs.pop("use_fallback", False)
    model_id = role.fallback if use_fallback and role.fallback else role.model
    return init_chat_model(model_id, model_provider=role.provider, max_tokens=kwargs.pop("max_tokens", DEFAULT_MAX_TOKENS), **kwargs)


def role_agent(role_id: str, system_prompt: str, tools=None):
    """A tool-using agent for one role of the plan."""
    return _build(chat_model(role_id), list(tools or []), system_prompt)


def last_text(result) -> str:
    """Final assistant text from an agent/graph result."""
    msgs = result["messages"] if isinstance(result, dict) else result
    for m in reversed(msgs):
        content = getattr(m, "content", None)
        if getattr(m, "type", "") == "ai" and content:
            if isinstance(content, list):
                return "".join(b.get("text", "") for b in content if isinstance(b, dict))
            return str(content)
    return ""
