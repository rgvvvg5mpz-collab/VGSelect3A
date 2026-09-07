# Case study 3: Account balances and cost basis assistant

**Business context.** Clients ask, in the app's chat, questions such as "What
is my total balance across accounts?", "What is the cost basis of my index fund
in the taxable account?", "How much did I contribute this year?" and "Why did my
balance drop yesterday?". Every number must come from the books and records
systems; the assistant explains, it never estimates.

**What the application does today.** A single agent with six deterministic
account tools, a FAQ knowledge base for explanations, and a Redis-backed
conversation memory, served behind a FastAPI websocket. It works, but latency
is 6-9 seconds and the team is asked to cut model spend and to keep all client
data on infrastructure cleared for restricted data.

**Constraints the code cannot see.** Answers within 5 seconds. Numbers must be
exactly right (accuracy 5), but every number is verifiable against the API
(strong verifiability). Account data is restricted. Volume is 200,000 requests a
day, so cost dominates. Conversations are multi-turn.

**Artistic liberty.** The firm has an on-premises open-weights model cleared for
restricted data, registered in the case-study catalog; the cloud models are not
cleared for this data class. A measured single-agent baseline on an internal eval
is 88%.

---

## VG Select: 3A results

**Scan.** 7 files; frameworks: anthropic-sdk; tools found: explain_balance_change, faq_lookup, get_balances, get_contributions_ytd, get_cost_basis, get_positions, get_transactions; knowledge sources: pgvector, sql; side effects: none. Current topology as implemented: **single_agent**.

**Recommendation.** **Single agent with tools** (score +2.1); estimated ~7s against a 5s budget (exceeds), $0.003 per request, 1x the tokens of one call. On the chosen models: ~7s, $0.003. Fastest viable within budget: none; strongest structural fit: Single agent with tools.

| Topology | Score | Est. latency |
|---|---|---|
| Current (single_agent) | +2.1 | ~7s |
| Recommended (single_agent) | +2.1 | ~7s |

**Why.**
- Simple task with a few tools: a single agent loop is enough.
- Unpredictable path: the model must choose steps at run time, which is the definition of an agent.
- Multi-hop retrieval: the model must decide follow-up queries from earlier results (agentic retrieval).
- A 88% single-agent baseline is the regime where one agent plus a better model/effort/tools wins.

**Model per role** (catalog `case-study-ecosystem`, providers used: self_hosted).

| Role | Model | Effort | Fallback |
|---|---|---|---|
| agent | acme-onprem-70b | n/a | - |

## Files

| File | What it is |
|---|---|
| `scenario.md`, `overrides.json` | The narrative and the hand-authored profile fields the code cannot reveal |
| `app/` | The mock application that was scanned |
| `output/scan.md`, `output/scan.json` | What the scanner found: inferred fields with confidence, evidence with file:line |
| `output/profile.json` | The merged profile the recommendation ran on |
| `output/recommendation.md`, `output/recommendation.json` | The full report and structured result (ranked options, plan, model selection, next steps) |
| `output/architecture.pdf` | The architecture document for the design review |
| `output/plan.svg`, `output/plan.mmd` | The plan diagram |
| `output/skeleton.zip`, `output/skeleton/` | The generated LangGraph project for the recommended topology |
| `output/summary.json` | The key numbers used in this README |
