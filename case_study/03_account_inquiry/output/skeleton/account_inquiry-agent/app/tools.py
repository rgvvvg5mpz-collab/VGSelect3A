"""Tool definitions. Keep tools few, distinct and well described."""

from langchain_core.tools import tool


@tool
def explain_balance_change(query: str) -> str:
    """TODO: describe precisely what `explain_balance_change` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"explain_balance_change result for: {query}"

@tool
def faq_lookup(query: str) -> str:
    """TODO: describe precisely what `faq_lookup` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"faq_lookup result for: {query}"

@tool
def get_balances(query: str) -> str:
    """TODO: describe precisely what `get_balances` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"get_balances result for: {query}"

@tool
def get_contributions_ytd(query: str) -> str:
    """TODO: describe precisely what `get_contributions_ytd` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"get_contributions_ytd result for: {query}"

@tool
def get_cost_basis(query: str) -> str:
    """TODO: describe precisely what `get_cost_basis` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"get_cost_basis result for: {query}"

@tool
def get_positions(query: str) -> str:
    """TODO: describe precisely what `get_positions` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"get_positions result for: {query}"

@tool
def get_transactions(query: str) -> str:
    """TODO: describe precisely what `get_transactions` does, its inputs and what it returns.
    Agents choose tools by this description."""
    # TODO: implement
    return f"get_transactions result for: {query}"


TOOLS = [explain_balance_change, faq_lookup, get_balances, get_contributions_ytd, get_cost_basis, get_positions, get_transactions]
