"""Single-prompt advisor with a compliance reviewer pass."""
import anthropic
from fastapi import FastAPI
from langgraph.checkpoint.memory import MemorySaver

from .tools import (contribution_limits, create_proposal, get_portfolio, market_data, risk_score, search_methodology,
                    search_policy, search_products, suitability_check, tax_lots)

app = FastAPI()
client = anthropic.Anthropic()
memory = MemorySaver()

SYSTEM = open("prompts/advisor_methodology_and_policy.md").read()  # ~9k tokens of methodology and policy
REVIEWER = """You are the compliance reviewer. Check the draft answer against policy and the suitability result.
Return approve/flag with reasons."""

TOOLS = [get_portfolio, risk_score, tax_lots, contribution_limits, suitability_check, market_data,
         search_methodology, search_policy, search_products, create_proposal]


@app.post("/chat")
def chat(client_id: str, message: str, history: list[dict]) -> dict:
    runner = client.beta.messages.tool_runner(
        model="claude-opus-5", max_tokens=4000, system=SYSTEM, tools=TOOLS,
        messages=history + [{"role": "user", "content": message}],
    )
    draft = runner.until_done()
    draft_text = next(b.text for b in draft.content if b.type == "text")
    review = client.messages.create(
        model="claude-opus-5", max_tokens=800, system=REVIEWER,
        messages=[{"role": "user", "content": draft_text}],
    )
    verdict = next(b.text for b in review.content if b.type == "text")
    requires_confirmation = verdict.startswith("flag")
    return {"answer": draft_text, "review": verdict, "requires_confirmation": requires_confirmation}
