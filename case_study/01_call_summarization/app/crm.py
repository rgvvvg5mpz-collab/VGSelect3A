"""Salesforce integration."""
import requests
from simple_salesforce import Salesforce

sf = Salesforce(username="svc", password="***", security_token="***")


def post_call_summary(call_id: str, payload: dict) -> None:
    sf.Task.create({"Subject": f"Call {call_id}", "Description": payload["summary"]})
    requests.post("https://hooks.internal/compliance", json={"call_id": call_id, "flags": payload["compliance_flags"]}, timeout=5)
