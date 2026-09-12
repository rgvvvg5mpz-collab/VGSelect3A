## Agent report card: account_inquiry

Full report card for **account_inquiry**: overall **D** (63.8/100). Task complexity 2 (simple), design 4 (complex), behaviour 5 (open-ended). Weakest dimension: Latency (F).

| Dimension | Grade | Score | Weight |
|---|---|---|---|
| Outcome quality | **B** | 80.4 | 30 |
| Reliability and control | **F** | 57.9 | 20 |
| Cost and token efficiency | **B** | 89.0 | 15 |
| Latency | **F** | 10.0 | 15 |
| Governance and guardrails | **D** | 60.0 | 10 |
| Complexity fit | **C** | 72.0 | 10 |
| **Overall** | **D** | 63.8 | |

### Complexity

| Axis | Level | Basis |
|---|---|---|
| Task | 2 (simple) | profile: complexity, breadth, sources, parallel sub-tasks, context pressure |
| Design | 4 (complex) | 7 tools (5 overlapping), delegation depth 0, 1 prompt definitions (~166 chars) |
| Behaviour | 5 (open-ended) | steps p50 7.0, p95 17.1, CV 0.59; branching 2.4; 0.0 spawns and 0.0 handoffs per run |

### Mismatches

- **Over-built for the task** (warn): Design complexity is level 4 (complex) for a level-2 (simple) task. _Action: Collapse structure: fewer roles, a single agent or a code-defined workflow; multi-agent costs ~15x chat tokens._
- **High stakes, little verification** (warn): Only 0% of runs include a verification step for a stakes-5 workload. _Action: Add an evaluator/verifier step (tests, schema checks, or an independent model) before returning._
- **Overlapping tools** (info): 5 tools share a name stem (get_balances, get_contributions_ytd, get_cost_basis, get_positions). _Action: Consolidate or namespace tools; overlap, not count, is what confuses agents (OpenAI)._

### Findings by dimension

**Outcome quality** (B)
- Only 71% of repeated tasks agree on outcome across runs: reliability across runs is low (Galileo reports 60% single-run falling to 25% over eight runs).

**Reliability and control** (F)
- No termination limits found in code while runs are long or loop: every loop needs a cap.
- High-stakes workload with little verification in traces and no eval harness in code (verification failures are ~25% of multi-agent failures).

**Cost and token efficiency** (B)
- Measured 22,165 tokens per run is 1.8x the estimate for this topology: look for redundant reading, missing caching, or over-long tool results.

**Latency** (F)
- Median latency 16.9s exceeds the 5s budget.
- p95 latency 31.9s is 6.4x the budget: the tail is driven by long tool chains or loops.

**Governance and guardrails** (D)
- Tests exist but no eval harness for model behaviour.
- Loops or delegation without termination limits in code.
- No tracing/observability library detected; multi-agent failures cannot be diagnosed without per-turn traces.
- High-stakes outputs without schema-validated structured output.

**Complexity fit** (C)
- Over-built for the task
- High stakes, little verification
- Overlapping tools

### Behavioural metrics

| Metric | Value |
|---|---|
| Runs / tasks | 160 / 80 |
| Success rate | 84% |
| Consistency across repeated runs | 71% |
| All runs pass (repeated tasks) | 70% |
| Steps per run (p50 / p95 / CV) | 7.0 / 17.1 / 0.59 |
| LLM calls per run (mean) | 3.95 |
| Tool calls per run (mean) | 3.29 |
| Distinct tools used | 4 |
| Tool error rate | 3.0% |
| Runs with repeated identical calls | 10% |
| Runs ended by a limit | 4% |
| Runs ended by error/timeout | 2% |
| Handoffs / spawns per run | 0.0 / 0.0 |
| Runs with verification / human step | 0% / 0% |
| Branching factor | 2.4 |
| Trajectory diversity | 0.47 |
| Tokens per run (mean / p95) | 22,165 / 58,230 |
| Peak context (max) | 13,537 |
| Context growth per step | 1,160 |
| Latency p50 / p95 | 16.9s / 31.9s |
| Cost per run / per completed task | $0.0506 / $0.0600 |
| Successes per 1k tokens | 0.038 |

### Per-agent cards

| Agent | Role | Model | Grade | Steps p50/p95 | Tool calls | Tool errors | Loops | Tokens/run | Latency p50 | Findings |
|---|---|---|---|---|---|---|---|---|---|---|
| agent | Plans and executes the whole task in one tool-use loop. | acme-onprem-70b | **A** | 7.0/17.1 | 3.29 | 3% | 10% | 22,165 | 16.9s | stable: no loops, low variance, no tool errors |
