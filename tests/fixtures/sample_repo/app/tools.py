import stripe
from anthropic import beta_tool
from pinecone import Pinecone

pc = Pinecone()
index = pc.Index("orders-kb")


@beta_tool
def lookup_order(order_id: str) -> str:
    """Look up an order by id."""
    return f"order {order_id}"


@beta_tool
def search_kb(query: str) -> str:
    """Search the knowledge base."""
    res = index.query(vector=[0.0] * 8, top_k=3)
    return str(res)


@beta_tool
def search_docs(query: str) -> str:
    """Search product docs."""
    return "docs"


@beta_tool
def search_tickets(query: str) -> str:
    """Search past tickets."""
    return "tickets"


@beta_tool
def issue_refund(order_id: str, amount: float) -> str:
    """Refund an order."""
    stripe.Refund.create(charge=order_id, amount=int(amount * 100))
    return "refunded"
