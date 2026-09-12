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

---

## VG Select: 3A results

**Scan.** 8 files; frameworks: anthropic-sdk; tools found: none; knowledge sources: none; side effects: external-post (irreversible), ticket/crm (irreversible). Current topology as implemented: **single_call**.

**Recommendation.** **Prompt chain (sequential workflow)** (score +3.2); estimated ~26s against a 60s budget (fits), $0.045 per request, 2x the tokens of one call. On the chosen models: ~25s, $0.059. Fastest viable within budget: Single model call; strongest structural fit: Parallel voting / ensemble.

| Topology | Score | Est. latency |
|---|---|---|
| Current (single_call) | +0.2 | ~9s |
| Recommended (prompt_chain) | +3.2 | ~26s |

**Why.**
- Steps are predictable: a code-defined chain with gates beats an agent deciding the path (more predictable, cheaper, easier to test).

**Model per role** (catalog `case-study-ecosystem`, providers used: anthropic).

| Role | Model | Effort | Fallback |
|---|---|---|---|
| extract | claude-sonnet-5 | high | claude-haiku-4-5 |
| finalize | claude-sonnet-5 | high | claude-haiku-4-5 |

## Agent report card

Overall **B** (84.7/100) from 120 fictional trace runs (`traces.jsonl`). Complexity: task 3, design 1, behaviour 2.

| Dimension | Grade | Score |
|---|---|---|
| Outcome quality | **B** | 84.6 |
| Reliability and control | **B** | 87.5 |
| Cost and token efficiency | **A** | 100.0 |
| Latency | **A** | 100.0 |
| Governance and guardrails | **F** | 30.0 |
| Complexity fit | **B** | 88.0 |

Mismatches: High stakes, little verification (warn).

| Agent | Grade | Note |
|---|---|---|
| agent | **A** | stable: no loops, low variance, no tool errors |

Full card: `output/report_card.md`.

## Files

| File | What it is |
|---|---|
| `scenario.md`, `overrides.json` | The narrative and the hand-authored profile fields the code cannot reveal |
| `app/` | The mock application that was scanned |
| `output/scan.md`, `output/scan.json` | What the scanner found: inferred fields with confidence, evidence with file:line |
| `output/profile.json` | The merged profile the recommendation ran on |
| `output/recommendation.md`, `output/recommendation.json` | The full report and structured result (ranked options, plan, model selection, next steps) |
| `output/architecture.pdf` | The architecture document for the design review (includes the report card) |
| `traces.jsonl`, `output/report_card.md`, `output/report_card.json` | Fictional run-time traces in the vgselect-trace format, and the agent report card graded from them |
| `output/plan.svg`, `output/plan.mmd` | The plan diagram |
| `output/skeleton.zip`, `output/skeleton/` | The generated LangGraph project for the recommended topology |
| `output/summary.json` | The key numbers used in this README |
