"""Deterministic compliance keyword checks applied after the model."""
COMPLAINT_TERMS = ("complaint", "unhappy", "ombudsman", "escalate")
VULNERABILITY_TERMS = ("bereaved", "diagnosed", "confused", "carer")


def keyword_flags(transcript: str) -> list[str]:
    t = transcript.lower()
    flags = []
    if any(w in t for w in COMPLAINT_TERMS):
        flags.append("complaint")
    if any(w in t for w in VULNERABILITY_TERMS):
        flags.append("vulnerable_client")
    return flags
