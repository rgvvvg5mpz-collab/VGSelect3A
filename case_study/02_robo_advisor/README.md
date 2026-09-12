# Case study 2: Robo-advisor

**Business context.** A digital advice service for retail clients. In a chat,
the client asks questions such as "Should I move my emergency fund into the
bond ladder?" or "How much can I put into my retirement account this year?"
The service must answer within the firm's advice methodology, cite policy, use
the client's actual portfolio, and never give advice a human adviser would not
be allowed to give.

**What the application does today.** One large prompt with the methodology,
several policy documents and a dozen tools: portfolio analytics, risk scoring,
tax-lot lookups, contribution-limit rules, product catalog search, market data,
plus three knowledge bases (methodology, policy, product). A compliance review
model call runs on every answer. Latency is 20-40 seconds and the prompt is
hard to maintain; the team suspects it should be split.

**Constraints the code cannot see.** Answers should arrive within about 15
seconds. Errors are very costly (unsuitable advice). Conversations are
multi-turn. Client data is confidential. A human adviser reviews flagged
answers. Volume is ~8,000 conversations a day.

**Artistic liberty.** Four advice domains (planning, tax, risk, products), a
suitability rules engine as a deterministic API, and a written eval rubric
scored by compliance; single-prompt baseline scores 61% on it.

---

## VG Select: 3A results

**Scan.** 8 files; frameworks: anthropic-sdk, langgraph; tools found: contribution_limits, create_proposal, get_portfolio, market_data, risk_score, search_methodology, search_policy, search_products, suitability_check, tax_lots; knowledge sources: elasticsearch; side effects: external-post (irreversible). Current topology as implemented: **evaluator_optimizer**.

**Recommendation.** **Router / classifier dispatch** (score +1.1); estimated ~27s against a 15s budget (exceeds), $0.414 per request, 2x the tokens of one call. On the chosen models: ~16s, $0.023. Fastest viable within budget: none; strongest structural fit: Router / classifier dispatch.

| Topology | Score | Est. latency |
|---|---|---|
| Current (evaluator_optimizer) | -5.7 | ~82s |
| Recommended (router) | +1.1 | ~27s |

**Why.**
- 4 distinct domains: route each request to a specialist prompt/agent instead of one prompt carrying every domain's instructions and tools.
- Routing to specialists gives each a small, non-overlapping tool set.

**Model per role** (catalog `case-study-ecosystem`, providers used: anthropic, self_hosted).

| Role | Model | Effort | Fallback |
|---|---|---|---|
| router | claude-haiku-4-5 | n/a | claude-sonnet-5 |
| handler_1 | acme-onprem-70b | n/a | claude-sonnet-5 |
| handler_2 | acme-onprem-70b | n/a | claude-sonnet-5 |
| handler_3 | acme-onprem-70b | n/a | claude-sonnet-5 |
| handler_4 | acme-onprem-70b | n/a | claude-sonnet-5 |

## Agent report card

Overall **F** (54.1/100) from 80 fictional trace runs (`traces.jsonl`). Complexity: task 5, design 4, behaviour 5.

| Dimension | Grade | Score |
|---|---|---|
| Outcome quality | **F** | 43.8 |
| Reliability and control | **F** | 39.8 |
| Cost and token efficiency | **A** | 90.0 |
| Latency | **F** | 36.3 |
| Governance and guardrails | **C** | 70.0 |
| Complexity fit | **C** | 71.0 |

Mismatches: Loops without limits (high); Overlapping tools (info).

| Agent | Grade | Note |
|---|---|---|
| agent | **D** | tool error rate 10% |
| evaluator | **A** | stable: no loops, low variance, no tool errors |

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
