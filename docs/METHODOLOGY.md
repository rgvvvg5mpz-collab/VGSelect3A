# VG Select: 3A — Methodology

How VG Select: 3A (Automated Agentic Architecture) turns a code repository and
a workload description into an architecture recommendation, and what the
numbers mean. The evidence behind each rule is in
[industry_guidance.md](industry_guidance.md).

## 1. Problem statement

Teams building agentic LLM applications face one recurring design decision:
how much structure to add. A single model call is fastest and cheapest; a
single agent with tools handles multi-step work; workflows (chains, routers,
fan-out, voting, evaluator loops) add predictability and accuracy at the cost
of latency; multi-agent systems (orchestrator + subagents, hierarchies,
handoffs) add breadth and parallelism at roughly 15x the tokens of a chat
interaction and with documented coordination failure modes.

Published guidance converges on "start simple, add structure only where
measured need exists", but leaves the mapping from workload properties to
topology implicit. 3A makes that mapping explicit, repeatable and auditable.

## 2. Pipeline

```
repository ──scan──▶ inferred profile ─┐
                                        ├─merge─▶ WorkloadProfile ─▶ rules ─▶ viability ─▶ estimates ─▶ balance ─▶ rank
prose/description ──Claude intake──────┤                                                                   │
manual profile / examples ─────────────┘                                                    decomposition plan + guardrails
                                                                                                           │
                                                          ┌────────────────────────────────────────────────┤
                                                          ▼                                                ▼
                                             architecture document (PDF)                    agent skeleton (LangGraph zip)
                                             + Markdown / JSON / SVG / UI
```

### 2.1 Inputs: the workload profile

Twenty-six fields in six groups (task shape, tools, knowledge, quality,
operating constraints, metadata). Each field has a definition, type, range or
enum, and default, held in one place (`profile.py`) from which the CLI, the
JSON schema for the Claude intake, the Pydantic models for the API and the UI
form are all generated. See `vgselect fields`.

### 2.2 Repository scan (inference)

The scanner (`scanner.py`) walks the tree (skipping VCS, dependency and build
directories; at most 20,000 files, 1 MB each) and applies regular-expression
tables over source and dependency files only. Prose (`.md`, `.txt`) is never
evidence. It extracts:

| Category | Signals | Inferred fields |
|---|---|---|
| Frameworks | SDK imports and dependency declarations (Anthropic, OpenAI, LangChain/LangGraph, CrewAI, AutoGen, ADK, MCP, ...) | context for the report |
| Tools | decorators (`@tool`, `@beta_tool`, `@mcp.tool`), tool schemas, Zod tools, OpenAI function specs, OpenAPI documents in the repo | `tool_count`, `tool_calls_per_task` (rough), `tool_overlap` (shared name stems) |
| Retrieval | vector DB clients, embeddings, retrievers, web search, SQL, graph DBs | `knowledge_sources`, `retrieval_depth`, `context_tokens_per_task` (rough) |
| Side effects | email/SMS, payments, external POST/DELETE, chat posting, DB writes, file writes, shell, infra, ticketing | `tool_side_effects`, `error_recoverability`, `accuracy_priority` |
| Agent patterns | manual tool loops, tool runners, graphs, supervisors, subagents, handoffs, routers, fan-out, evaluators, chains | `current_topology`, `steps_predictable`, `task_complexity`, `parallel_subtasks`, `scope_breadth` |
| Serving | HTTP APIs, streaming, batch/cron, chat UIs, CLIs | `latency_budget_s`, `interaction` |
| Quality | tests, eval harnesses, structured outputs, caching, approval flows, memory, compaction | `verifiability`, `human_in_loop` |

Every inference carries a confidence (0-1) and a reason, and every category
keeps file:line evidence. Fields the code cannot reveal (latency budget,
accuracy priority, cost sensitivity, volume) are left to the user; user values
always override inferences. The scan also identifies the topology the code
implements today, so the report can show the gap.

### 2.3 Rules (structural fit)

Forty-one rules (`rules.py`) each read the profile and add or subtract fit
points for one or more topologies, with a rationale and a citation key. They
are grouped as the guidance suggests:

1. Simplicity first (trivial/simple tasks -> single call or single agent; multi-agent penalised below complex).
2. Workflow vs. agent (predictable steps -> chain/sectioning; unpredictable -> agent; open-ended -> orchestrator).
3. Parallelism and breadth (independent sub-tasks -> sectioning or orchestrator; many domains -> router/handoffs/hierarchy).
4. Knowledge and context (single lookup -> RAG in code; multi-hop -> agentic retrieval; exhaustive or context overflow -> subagents).
5. Accuracy and verification (strong verifiability + high stakes -> evaluator loop; bounded high-stakes answers -> voting).
6. Latency budget and cost/volume.
7. Tool surface (overlap, count, sequential chains).
8. Interaction shape (long-running, conversational, document, code change).
9. Measured evidence (single-agent baseline above ~45% -> penalise multi-agent; low baseline on decomposable task -> favour centralised multi-agent).
10. Sequential dependency and error amplification (centralised 4.4x vs decentralised 7.8x vs independent 17x).
11. Retrieval latency (interactive budgets force single-pass/adaptive RAG).

Weights are small integers chosen so that one strong signal (about +3) equals
the typical latency penalty of missing a budget by 50%. They are deliberately
coarse: the intent is a defensible ranking with visible reasons, not a
regression.

### 2.4 Viability (hard constraints)

Independent of score, a topology is marked non-viable when it cannot do the
job: a single call cannot make tool calls or follow-up retrievals; a fixed
chain cannot follow an open-ended path; sectioning needs something to fan out;
handoffs and hierarchy need more than one domain. Non-viable candidates are
shown, struck through, at the bottom.

### 2.5 Estimates (latency, cost, tokens)

For every topology the estimator (`estimator.py`) builds a call tree from the
profile:

- a **single call** is one request reading up to the task's context tokens;
- an **agent loop** is `ceil(tool_calls / batch)` tool rounds (batch 4 for
  independent tools, 2 mixed, 1 sequential) with context growing as results
  accumulate, plus a final answer;
- **chains** are 2-4 sequential stages; **routers** add a small-model
  classification hop; **sectioning** and **voting** run branches in parallel
  (waves of at most 10) then aggregate; the **evaluator loop** runs 2-3
  generate/evaluate iterations; **orchestrator-workers** is plan + one wave of
  N workers (each a Sonnet-tier agent loop over its share of tools and
  reading) + synthesis; **hierarchical** adds a lead layer; **handoffs** add
  a transfer hop.

Latency is the critical path: sequential segments add, parallel segments
count their slowest branch. Each call costs time-to-first-token plus output
tokens divided by tokens-per-second for its model tier, plus tool latency per
round. Cost sums every call at list prices without caching. The token
multiplier is total tokens divided by one plain call. Model tier per role is
chosen by capability and only lowered when the latency budget forces it.

Serving assumptions (`MODEL_TIERS`) are published rates and rough throughput
figures; replace them with measurements. The outputs are order-of-magnitude
and exist to rank options, which is why the report prints its assumptions.

### 2.6 Balancing latency and accuracy

```
score = fit + latency_adj + cost_adj

latency_adj: ratio = est_latency / budget
             +1.0 at ratio <= 0.5, falling to 0 at ratio 1.0,
             -1.5 .. -3.5 for ratio 1..2, then -3.5 - log2(ratio) (capped)
             negative values are scaled by 1 + 0.3 * (3 - accuracy_priority),
             clamped to [0.4, 1.6]: high accuracy priority tolerates lateness

cost_adj   = -(cost_sensitivity / 3) * 0.6 * log2(cost / cheapest_viable_cost)
```

So the same workload gets a faster answer when speed matters and a more
thorough one when correctness matters, and the trade is visible in the table.
The report also prints the Pareto frontier over (latency, structural fit) and
names the fastest viable option within budget and the most accurate option.

### 2.7 Decomposition plan

For the winning topology the planner (`decomposition.py`) produces components
with role, model tier, effort level, tools and parallel group:

- worker count follows Anthropic's research-system heuristic (1 agent for
  fact-finding, 2-4 for comparisons, 10+ for complex research), raised by
  context pressure (one worker per ~100k tokens of reading) and capped at 20;
- workers are named after the profile's sources, domains, sections or
  sub-tasks when given;
- orchestrators run on the Opus tier at high/xhigh effort (max when accuracy
  priority is 5); reading-heavy workers on Sonnet or Haiku at low/medium;
- a verifier is added for multi-agent plans when verifiability exists and
  accuracy priority is high; a gate for irreversible tools;
- briefing rules restate the delegation contract (objective, output format,
  tools/sources, boundaries, effort).

Cross-cutting recommendations are emitted independently of topology: evals
first (~20 queries), termination limits, verification at the orchestrator,
prompt caching, streaming, structured outputs, parallel tool use,
programmatic tool calling, tool search, context editing/compaction/memory,
model tiering, adaptive RAG, batch API. Each carries a citation.

### 2.7a Model selection per role

Each component of the plan gets a requirements block derived from the profile
and its role (capability level, latency share, context, tools, structured
output, stakes, volume, data class, task family, independence, cache group),
and the selector matches it against the model ecosystem catalog under the
policy: hard filters, capability floor with measured-evidence override,
quality/latency/cost scoring, orchestrator-not-weaker-than-workers, verifier
independence, one model per loop, fallback on another provider, and
unfilled-role feedback. The topology ranking is estimated on reference models
per capability level from the same catalog and policy, and the primary is
re-estimated on the chosen models. Full description: [MODEL_CATALOG.md](MODEL_CATALOG.md).

### 2.8 Outputs

- **Architecture document (PDF)**: the deliverable for a design review.
  Summary, why (cited) with counter-signals, scan findings and gap, options
  compared, frontier and runners-up, plan with diagram, briefing rules,
  cross-cutting recommendations, assumptions, the profile used, sources.
  Generated with reportlab (`pdf_report.py`) from the same objects as the
  Markdown report, so the two never disagree; the diagram uses the same
  layout function as the SVG.
- **Agent skeleton (zip)**: a runnable LangGraph project for the recommended
  topology (`scaffold/langgraph.py`, one template per topology; see 2.9).
- Markdown report, JSON (full structure, including every signal and scan
  evidence), Mermaid and SVG diagrams; the same content in the web UI, which
  adds a latency-versus-fit chart and per-row rule expansions.

### 2.9 Skeleton generation

The generator fills a topology template with the plan and profile: one role
entry per component (model ID, effort, tier), tool stubs named after the
profile's or scan's tools, termination limits derived from the profile
(`RECURSION_LIMIT` from tool calls per task, `MAX_ITERATIONS` from accuracy
priority, `MAX_WORKERS` from the worker-count heuristic), and an approval hook
when irreversible tools exist. How each topology maps to LangGraph:

| Topology | Graph construct |
|---|---|
| Single call | `retrieve` (code) -> `answer` nodes |
| Single agent | one `create_agent` / `create_react_agent` node with all tools |
| Prompt chain | one node per stage, code gates as plain nodes, linear edges |
| Router | small-model structured-output classifier, `add_conditional_edges` to one handler per domain |
| Parallel sectioning | `split` -> `Send` fan-out to `section` -> `merge`, results via an `operator.add` reducer |
| Parallel voting | `Send` fan-out to N `vote` nodes -> majority in code (discrete answers) or a judge call |
| Evaluator-optimizer | `generate` -> `evaluate` (structured verdict) -> conditional edge back or `finish`, capped by `MAX_ITERATIONS` |
| Orchestrator + workers | `plan` (structured briefs) -> `Send` fan-out to `worker` -> `synthesise` -> optional `verify` |
| Hierarchical | `top_plan` -> `Send` per domain into a compiled lead subgraph (plan -> workers -> synth) -> `top_synth` |
| Handoffs | one node per specialist, each returning a structured answer/handoff decision; conditional routing with `MAX_HANDOFFS` |

The generated code is a starting point: graph structure, limits and model
tiering are decided by the recommendation; prompts, tool bodies and acceptance
criteria are marked TODO. It targets LangChain 1.x / LangGraph 1.x with a
fallback import for LangGraph 0.2/0.3.

## 3. Validation

- Eight canonical scenarios (FAQ bot, moderation classifier, support agent,
  coding agent, deep research, extraction pipeline, PR review, enterprise
  analyst) are bundled and tested for the expected topology.
- Property tests check monotonicity: tightening the budget moves the answer
  toward faster topologies; raising accuracy priority reduces the latency
  penalty; parallel research is faster under an orchestrator than under a
  single agent; a measured baseline above 45% penalises multi-agent.
- A fixture repository exercises the scanner end to end (tools, retrieval,
  payments side effect, tool overlap, FastAPI surface) and every API endpoint,
  including the PDF and skeleton endpoints and the scan round-trip into the
  PDF.
- Catalog validation, requirement derivation and model selection are tested
  under policies (providers, regions, data class, unverified entries,
  measured evidence lifting a smaller model, verifier independence, the
  orchestrator floor).
- PDF generation is tested for several scenarios and for a scan-based
  recommendation; the generated skeleton is syntax-checked for all ten
  topologies and for mixed-provider plans (68 tests in total). Separately, every skeleton was unzipped and
  its own smoke test run against LangGraph 1.2 / LangChain 1.4: all ten
  compile.

## 4. Limitations and how to calibrate

- Estimates are heuristic. Calibrate `MODEL_TIERS` and estimator constants
  from your traces, then re-run the examples.
- The scanner is pattern-based. It cannot count tool calls per request or
  tokens per request; both are rough inferences to be replaced by measured
  values (`tool_calls_per_task`, `context_tokens_per_task`).
- Rules encode published guidance as of September 2026. When you learn
  something from your own evals, add a rule with its evidence rather than
  editing weights ad hoc.
- Model selection is only as good as the catalog: capability tiers and
  serving figures for non-Anthropic models must come from your registry and
  evals (the bundled placeholders are excluded until verified), and measured
  `evidence` per task family is the signal that changes decisions most.

## 5. Extending

- New topology: add to `TOPOLOGIES`, an estimator branch, a plan branch,
  viability rules, and at least one scoring rule.
- New rule: a function decorated with `@rule` returning `Signal`s; add its
  citation to `industry_guidance.md`.
- New scanner pattern: extend the tables at the top of `scanner.py`; add a
  fixture and a test.
- New skeleton framework: add a module under `scaffold/` exposing
  `generate(rec) -> {path: content}` and register it in `scaffold/__init__.py`;
  add it to the `framework` literal in `service/schemas.py` and to the CLI
  choices. Test that every topology's output compiles.
