"""Tool definitions. Keep tools few, distinct and well described."""

from langchain_core.tools import tool


# No tools were declared in the profile. Add @tool functions here and list them in TOOLS.


TOOLS = []

IRREVERSIBLE = {  # TODO: list tool names whose effects cannot be undone
}


def requires_approval(tool_name: str) -> bool:
    """Wire this into an interrupt (langgraph.types.interrupt) or a human approval step
    before executing irreversible tools."""
    return tool_name in IRREVERSIBLE
