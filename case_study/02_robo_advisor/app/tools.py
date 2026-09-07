"""Deterministic APIs and knowledge-base search exposed to the advisor."""
import requests
from anthropic import beta_tool
from opensearchpy import OpenSearch

kb = OpenSearch(hosts=["https://kb.internal:9200"])


@beta_tool
def get_portfolio(client_id: str) -> str:
    """Holdings, cash and allocation for the client from the portfolio analytics API."""
    return requests.get(f"https://analytics.internal/portfolio/{client_id}", timeout=5).text


@beta_tool
def risk_score(client_id: str) -> str:
    """Current risk tolerance and capacity score for the client."""
    return requests.get(f"https://risk.internal/score/{client_id}", timeout=5).text


@beta_tool
def tax_lots(client_id: str, account_id: str) -> str:
    """Tax lots and unrealised gains for an account."""
    return requests.get(f"https://tax.internal/lots/{client_id}/{account_id}", timeout=5).text


@beta_tool
def contribution_limits(account_type: str, tax_year: int) -> str:
    """Statutory contribution limits for an account type and tax year (rules engine)."""
    return requests.get("https://rules.internal/limits", params={"type": account_type, "year": tax_year}, timeout=5).text


@beta_tool
def suitability_check(client_id: str, proposal: str) -> str:
    """Deterministic suitability rules engine: returns pass/fail with reasons."""
    return requests.post("https://rules.internal/suitability", json={"client_id": client_id, "proposal": proposal}, timeout=5).text


@beta_tool
def market_data(ticker: str) -> str:
    """Latest price, yield and volatility for a security."""
    return requests.get(f"https://marketdata.internal/{ticker}", timeout=5).text


@beta_tool
def search_methodology(query: str) -> str:
    """Search the advice methodology knowledge base."""
    return str(kb.search(index="methodology", body={"query": {"match": {"text": query}}}))


@beta_tool
def search_policy(query: str) -> str:
    """Search the compliance policy knowledge base."""
    return str(kb.search(index="policy", body={"query": {"match": {"text": query}}}))


@beta_tool
def search_products(query: str) -> str:
    """Search the product catalog knowledge base."""
    return str(kb.search(index="products", body={"query": {"match": {"text": query}}}))


@beta_tool
def create_proposal(client_id: str, summary: str) -> str:
    """Save a draft rebalancing proposal for adviser review (not executed)."""
    return requests.post("https://proposals.internal/draft", json={"client_id": client_id, "summary": summary}, timeout=5).text
