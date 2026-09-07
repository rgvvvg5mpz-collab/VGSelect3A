"""Tool definitions. Keep tools few, distinct and well described."""

from langchain_core.tools import tool


@tool
def contribution_limits(query: str) -> str:
    """TODO: describe precisely what `contribution_limits` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"contribution_limits result for: {query}"

@tool
def create_proposal(query: str) -> str:
    """TODO: describe precisely what `create_proposal` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"create_proposal result for: {query}"

@tool
def get_portfolio(query: str) -> str:
    """TODO: describe precisely what `get_portfolio` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"get_portfolio result for: {query}"

@tool
def market_data(query: str) -> str:
    """TODO: describe precisely what `market_data` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"market_data result for: {query}"

@tool
def risk_score(query: str) -> str:
    """TODO: describe precisely what `risk_score` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"risk_score result for: {query}"

@tool
def search_methodology(query: str) -> str:
    """TODO: describe precisely what `search_methodology` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"search_methodology result for: {query}"

@tool
def search_policy(query: str) -> str:
    """TODO: describe precisely what `search_policy` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"search_policy result for: {query}"

@tool
def search_products(query: str) -> str:
    """TODO: describe precisely what `search_products` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"search_products result for: {query}"

@tool
def suitability_check(query: str) -> str:
    """TODO: describe precisely what `suitability_check` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"suitability_check result for: {query}"

@tool
def tax_lots(query: str) -> str:
    """TODO: describe precisely what `tax_lots` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"tax_lots result for: {query}"


TOOLS = [contribution_limits, create_proposal, get_portfolio, market_data, risk_score, search_methodology, search_policy, search_products, suitability_check, tax_lots]

IRREVERSIBLE = {  # TODO: list tool names whose effects cannot be undone
}


def requires_approval(tool_name: str) -> bool:
    """Wire this into an interrupt (langgraph.types.interrupt) or a human approval step
    before executing irreversible tools."""
    return tool_name in IRREVERSIBLE
