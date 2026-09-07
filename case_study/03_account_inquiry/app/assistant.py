"""Account assistant: one tool-use loop behind a websocket, with Redis-backed memory."""
import anthropic
import redis
from fastapi import FastAPI, WebSocket

from .tools import (explain_balance_change, faq_lookup, get_balances, get_contributions_ytd, get_cost_basis, get_positions,
                    get_transactions)

app = FastAPI()
client = anthropic.Anthropic()
memory = redis.Redis(host="memory.internal")

SYSTEM = """You answer questions about the client's own accounts. Every number must come from a tool result.
Never estimate. If a tool fails, say so. Keep answers under 80 words."""
TOOLS = [get_balances, get_positions, get_cost_basis, get_transactions, get_contributions_ytd, explain_balance_change, faq_lookup]


@app.websocket("/ws")
async def ws(websocket: WebSocket, client_id: str):
    await websocket.accept()
    history = memory.get(client_id) or []
    while True:
        message = await websocket.receive_text()
        runner = client.beta.messages.tool_runner(
            model="claude-sonnet-5", max_tokens=600, system=SYSTEM, tools=TOOLS,
            messages=history + [{"role": "user", "content": message}],
        )
        final = runner.until_done()
        text = next(b.text for b in final.content if b.type == "text")
        memory.set(client_id, history + [{"role": "user", "content": message}, {"role": "assistant", "content": text}])
        await websocket.send_text(text)
