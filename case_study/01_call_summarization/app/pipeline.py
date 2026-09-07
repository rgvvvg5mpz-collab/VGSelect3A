"""Nightly call-summarisation batch: transcript -> redaction -> summary -> CRM."""
import re

import anthropic
from celery import Celery
from pydantic import BaseModel

from .crm import post_call_summary

app = Celery("calls")
client = anthropic.Anthropic()

SYSTEM = """You summarise recorded client calls for a regulated financial firm.
Return a JSON object with: summary, intents, commitments, compliance_flags."""


class CallSummary(BaseModel):
    summary: str
    intents: list[str]
    commitments: list[str]
    compliance_flags: list[str]


def redact(transcript: str) -> str:
    transcript = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]", transcript)
    return re.sub(r"\b\d{13,16}\b", "[CARD]", transcript)


@app.task
def summarise_call(call_id: str, transcript: str) -> dict:
    response = client.messages.parse(
        model="claude-opus-5",
        max_tokens=2000,
        system=SYSTEM,
        messages=[{"role": "user", "content": redact(transcript)}],
        output_format=CallSummary,
    )
    summary = response.parsed_output
    post_call_summary(call_id, summary.model_dump())
    return summary.model_dump()
