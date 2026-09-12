## Agent report card: robo_advisor

Full report card for **robo_advisor**: overall **F** (54.1/100). Task complexity 5 (open-ended), design 4 (complex), behaviour 5 (open-ended). Priority: Loops without limits. Weakest dimension: Latency (F). Agents needing attention: agent.

| Dimension | Grade | Score | Weight |
|---|---|---|---|
| Outcome quality | **F** | 43.8 | 30 |
| Reliability and control | **F** | 39.8 | 20 |
| Cost and token efficiency | **A** | 90.0 | 15 |
| Latency | **F** | 36.3 | 15 |
| Governance and guardrails | **C** | 70.0 | 10 |
| Complexity fit | **C** | 71.0 | 10 |
| **Overall** | **F** | 54.1 | |

### Complexity

| Axis | Level | Basis |
|---|---|---|
| Task | 5 (open-ended) | profile: complexity, breadth, sources, parallel sub-tasks, context pressure |
| Design | 4 (complex) | 10 tools (3 overlapping), delegation depth 0, evaluator loop, 1 prompt definitions (~132 chars) |
| Behaviour | 5 (open-ended) | steps p50 8.0, p95 22.05, CV 0.58; branching 2.43; 0.0 spawns and 0.0 handoffs per run |

### Mismatches

- **Loops without limits** (high): Repetition in 31% of runs, 9% hit a limit, and no termination limits are in code. _Action: Add max turns/tool calls/iterations and explicit stop criteria; cache identical tool calls._
- **Overlapping tools** (info): 3 tools share a name stem (search_methodology, search_policy, search_products). _Action: Consolidate or namespace tools; overlap, not count, is what confuses agents (OpenAI)._

### Findings by dimension

**Outcome quality** (F)
- Only 35% of repeated tasks agree on outcome across runs: reliability across runs is low (Galileo reports 60% single-run falling to 25% over eight runs).
- Measured success 48% is below the stated single-agent baseline 61%: the added structure is not paying for itself.
- Success 48% is above the ~45% capability-saturation threshold: adding agents is unlikely to help; improve model, prompt or tools instead.

**Reliability and control** (F)
- 31% of runs repeat an identical tool call (step repetition is 15.7% of multi-agent failures in MAST). Add a result cache or a rule against re-calling with the same arguments.
- 9% of runs end by hitting a step or recursion limit: the agent does not know when it is done ('unaware of termination', 12.4% of failures). Add explicit stop criteria to the prompt and check the limit is not too low.
- Tool error rate 10%: return `is_error` results the model can act on, and add retries with backoff in the harness.

**Latency** (F)
- Median latency 22.1s exceeds the 15s budget.
- p95 latency 44.4s is 3.0x the budget: the tail is driven by long tool chains or loops.

**Governance and guardrails** (C)
- Loops or delegation without termination limits in code.
- High-stakes outputs without schema-validated structured output.
- Traces show no human approval steps despite irreversible tools.

**Complexity fit** (C)
- Loops without limits
- Overlapping tools

### Behavioural metrics

| Metric | Value |
|---|---|
| Runs / tasks | 80 / 40 |
| Success rate | 48% |
| Consistency across repeated runs | 35% |
| All runs pass (repeated tasks) | 15% |
| Steps per run (p50 / p95 / CV) | 8.0 / 22.05 / 0.58 |
| LLM calls per run (mean) | 5.05 |
| Tool calls per run (mean) | 4.75 |
| Distinct tools used | 5 |
| Tool error rate | 9.7% |
| Runs with repeated identical calls | 31% |
| Runs ended by a limit | 9% |
| Runs ended by error/timeout | 8% |
| Handoffs / spawns per run | 0.0 / 0.0 |
| Runs with verification / human step | 100% / 0% |
| Branching factor | 2.43 |
| Trajectory diversity | 0.5 |
| Tokens per run (mean / p95) | 67,584 / 145,937 |
| Peak context (max) | 25,510 |
| Context growth per step | 1,107 |
| Latency p50 / p95 | 22.1s / 44.4s |
| Cost per run / per completed task | $0.1386 / $0.2918 |
| Successes per 1k tokens | 0.007 |

### Per-agent cards

| Agent | Role | Model | Grade | Steps p50/p95 | Tool calls | Tool errors | Loops | Tokens/run | Latency p50 | Findings |
|---|---|---|---|---|---|---|---|---|---|---|
| agent | - | - | **D** | 7.0/20.05 | 4.75 | 10% | 31% | 65,243 | 19.3s | tool error rate 10%; repeats identical tool calls in 31% of runs |
| evaluator | - | - | **A** | 1.0/2.0 | 0.0 | 0% | 0% | 2,341 | 1.4s | stable: no loops, low variance, no tool errors |
