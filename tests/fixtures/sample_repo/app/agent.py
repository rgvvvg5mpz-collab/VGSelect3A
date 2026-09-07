import anthropic
from fastapi import FastAPI

from .tools import issue_refund, lookup_order, search_docs, search_kb, search_tickets

app = FastAPI()
client = anthropic.Anthropic()
SYSTEM = """You are a support agent. Use tools to help the customer."""


@app.post("/chat")
def chat(message: str) -> str:
    runner = client.beta.messages.tool_runner(
        model="claude-opus-5",
        max_tokens=4096,
        system=SYSTEM,
        tools=[lookup_order, search_kb, search_docs, search_tickets, issue_refund],
        messages=[{"role": "user", "content": message}],
    )
    final = runner.until_done()
    return next(b.text for b in final.content if b.type == "text")
