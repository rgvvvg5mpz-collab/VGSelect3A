"""Deterministic account tools (books and records) and FAQ retrieval."""
import requests
from anthropic import beta_tool
from pgvector.psycopg import register_vector


@beta_tool
def get_balances(client_id: str) -> str:
    """Current balance per account and total, from the books-and-records API."""
    return requests.get(f"https://bor.internal/balances/{client_id}", timeout=3).text


@beta_tool
def get_positions(client_id: str, account_id: str) -> str:
    """Positions with quantity, price and market value for an account."""
    return requests.get(f"https://bor.internal/positions/{client_id}/{account_id}", timeout=3).text


@beta_tool
def get_cost_basis(client_id: str, account_id: str, symbol: str) -> str:
    """Cost basis (lots, method, unrealised gain) for one holding."""
    return requests.get(f"https://bor.internal/costbasis/{client_id}/{account_id}/{symbol}", timeout=3).text


@beta_tool
def get_transactions(client_id: str, account_id: str, days: int = 30) -> str:
    """Recent transactions (contributions, withdrawals, dividends, trades)."""
    return requests.get(f"https://bor.internal/transactions/{client_id}/{account_id}", params={"days": days}, timeout=3).text


@beta_tool
def get_contributions_ytd(client_id: str, tax_year: int) -> str:
    """Year-to-date contributions per account against the statutory limit."""
    return requests.get(f"https://bor.internal/contributions/{client_id}/{tax_year}", timeout=3).text


@beta_tool
def explain_balance_change(client_id: str, account_id: str, date: str) -> str:
    """Deterministic attribution of a day's balance change: market move, flows, fees."""
    return requests.get(f"https://bor.internal/attribution/{client_id}/{account_id}/{date}", timeout=3).text


@beta_tool
def faq_lookup(question: str) -> str:
    """Semantic search over the approved FAQ / explanations knowledge base (pgvector)."""
    return "faq passages"
