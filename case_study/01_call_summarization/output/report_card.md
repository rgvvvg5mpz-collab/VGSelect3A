## Agent report card: call_summarization

Full report card for **call_summarization**: overall **B** (84.7/100). Task complexity 3 (moderate), design 1 (trivial), behaviour 2 (simple). Weakest dimension: Governance and guardrails (F).

| Dimension | Grade | Score | Weight |
|---|---|---|---|
| Outcome quality | **B** | 84.6 | 30 |
| Reliability and control | **B** | 87.5 | 20 |
| Cost and token efficiency | **A** | 100.0 | 15 |
| Latency | **A** | 100.0 | 15 |
| Governance and guardrails | **F** | 30.0 | 10 |
| Complexity fit | **B** | 88.0 | 10 |
| **Overall** | **B** | 84.7 | |

### Complexity

| Axis | Level | Basis |
|---|---|---|
| Task | 3 (moderate) | profile: complexity, breadth, sources, parallel sub-tasks, context pressure |
| Design | 1 (trivial) | 0 tools (0 overlapping), delegation depth 0, 1 prompt definitions (~143 chars) |
| Behaviour | 2 (simple) | steps p50 3.0, p95 3.0, CV 0.0; branching 1.0; 0.0 spawns and 0.0 handoffs per run |

### Mismatches

- **High stakes, little verification** (warn): Only 0% of runs include a verification step for a stakes-4 workload. _Action: Add an evaluator/verifier step (tests, schema checks, or an independent model) before returning._

### Findings by dimension

**Outcome quality** (B)
- Only 78% of repeated tasks agree on outcome across runs: reliability across runs is low (Galileo reports 60% single-run falling to 25% over eight runs).

**Reliability and control** (B)
- High-stakes workload with little verification in traces and no eval harness in code (verification failures are ~25% of multi-agent failures).

**Governance and guardrails** (F)
- No eval harness or tests found: build a ~20-query eval before changing structure.
- Irreversible integrations without an approval or confirmation gate in code.
- No tracing/observability library detected; multi-agent failures cannot be diagnosed without per-turn traces.
- Traces show no human approval steps despite irreversible tools.

**Complexity fit** (B)
- High stakes, little verification

### Behavioural metrics

| Metric | Value |
|---|---|
| Runs / tasks | 120 / 60 |
| Success rate | 88% |
| Consistency across repeated runs | 78% |
| All runs pass (repeated tasks) | 77% |
| Steps per run (p50 / p95 / CV) | 3.0 / 3.0 / 0.0 |
| LLM calls per run (mean) | 3.0 |
| Tool calls per run (mean) | 0.0 |
| Distinct tools used | 0 |
| Tool error rate | 0.0% |
| Runs with repeated identical calls | 0% |
| Runs ended by a limit | 2% |
| Runs ended by error/timeout | 0% |
| Handoffs / spawns per run | 0.0 / 0.0 |
| Runs with verification / human step | 0% / 0% |
| Branching factor | 1.0 |
| Trajectory diversity | 0.0 |
| Tokens per run (mean / p95) | 12,116 / 14,100 |
| Peak context (max) | 4,774 |
| Context growth per step | 400 |
| Latency p50 / p95 | 17.9s / 19.0s |
| Cost per run / per completed task | $0.0329 / $0.0376 |
| Successes per 1k tokens | 0.072 |

### Per-agent cards

| Agent | Role | Model | Grade | Steps p50/p95 | Tool calls | Tool errors | Loops | Tokens/run | Latency p50 | Findings |
|---|---|---|---|---|---|---|---|---|---|---|
| agent | - | - | **A** | 3.0/3.0 | 0.0 | 0% | 0% | 12,116 | 17.9s | stable: no loops, low variance, no tool errors |
