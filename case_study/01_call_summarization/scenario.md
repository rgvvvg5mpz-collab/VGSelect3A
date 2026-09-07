# Case study 1: Call summarization

**Business context.** A contact centre records ~50,000 client calls a day.
Within a minute of a call ending, the advisor's CRM should show a concise
summary, the client's stated intents, any commitments the firm made, and
compliance flags (complaints, vulnerable-client indicators, unlicensed advice).

**What the application does today.** A nightly batch job pulls transcripts
from the telephony platform, sends each to a single model call with a long
prompt, and posts the result to Salesforce. Quality is uneven: action items
are missed, compliance flags are inconsistent, and the team wants near-real-time
turnaround instead of overnight.

**Constraints the code cannot see.** Turnaround of about 60 seconds per call
is acceptable (the advisor is writing notes anyway). Accuracy matters: a missed
complaint is a regulatory issue. Transcripts contain client PII, so the data
class is confidential. Cost matters at this volume.

**Artistic liberty.** The pipeline has a deterministic redaction step before the
model, a schema-validated output, and a rules engine that checks compliance
flags against keyword lists; a small eval set of 300 hand-labelled calls exists.
