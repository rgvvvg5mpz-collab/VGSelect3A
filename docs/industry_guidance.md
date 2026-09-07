# Industry guidance behind the rule engine

This document is the evidence base for `vgselect3a`. Each rule in
`src/vgselect3a/rules.py` carries a citation key; the keys resolve here.
Sources were fetched on 2026-09-07. Quotes are short and attributed; see the
URLs for full context.

| Key | Source |
|---|---|
| ANTHROPIC_BEA | Anthropic, *Building effective agents* - https://www.anthropic.com/engineering/building-effective-agents |
| ANTHROPIC_MAR | Anthropic, *How we built our multi-agent research system* - https://www.anthropic.com/engineering/multi-agent-research-system |
| ANTHROPIC_CTX | Anthropic, *Effective context engineering for AI agents* - https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents ; *Writing effective tools for agents* - https://www.anthropic.com/engineering/writing-tools-for-agents |
| ANTHROPIC_MA | Anthropic Managed Agents multiagent guidance (bundled Claude API skill) and Claude Code subagent docs - https://code.claude.com/docs/en/sub-agents |
| OPENAI_PG | OpenAI, *A practical guide to building agents* - https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf ; Agents SDK multi-agent docs - https://openai.github.io/openai-agents-python/multi_agent/ |
| GOOGLE_ADK | Google ADK workflow patterns - https://adk.dev/workflows/patterns/ ; https://developers.googleblog.com/developers-guide-to-multi-agent-patterns-in-adk/ |
| LANGGRAPH | LangChain/LangGraph multi-agent docs - https://docs.langchain.com/oss/python/langchain/multi-agent ; https://github.com/langchain-ai/langgraph-supervisor-py |
| MS_AF | Microsoft Azure Architecture Center, *AI agent design patterns* - https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns ; Agent Framework orchestrations - https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/overview |
| MAST | Cemri et al., *Why Do Multi-Agent LLM Systems Fail?* - https://arxiv.org/abs/2503.13657 |
| SCALING | Google/MIT, *Towards a Science of Scaling Agent Systems* (Dec 2025) - https://arxiv.org/abs/2512.08296 |
| COGNITION | Cognition, *Don't Build Multi-Agents* - https://cognition.com/blog/dont-build-multi-agents |
| RAG | *Agentic RAG vs classic RAG* (Towards Data Science) ; Mastra, *Agentic RAG* ; LatentRAG https://arxiv.org/html/2605.06285 ; Agentic RAG survey https://arxiv.org/html/2501.09136 |

---

## 1. Source-by-source findings

### 1.1 Anthropic, "Building effective agents" (ANTHROPIC_BEA)

Core distinction: **workflows** orchestrate LLMs and tools through predefined
code paths; **agents** let the LLM dynamically direct its own process and tool
usage.

Patterns and when to use them:

- **Augmented LLM** (retrieval + tools + memory) is the base unit. For many
  applications optimising a single call with retrieval and in-context examples
  is enough.
- **Prompt chaining**: fixed sequence of calls with programmatic gates. Use when
  the task decomposes cleanly into fixed sub-tasks; it trades latency for higher
  per-step accuracy.
- **Routing**: classify, then dispatch to a specialised path. Use when there are
  distinct categories better handled separately and classification is accurate.
  Includes routing easy queries to a small model.
- **Parallelization**: *sectioning* (independent sub-tasks concurrently) and
  *voting* (same task several times for confidence).
- **Orchestrator-workers**: a central LLM dynamically breaks down the task,
  delegates, and synthesises. Use for complex tasks where the sub-tasks cannot
  be predicted in advance. This is what distinguishes it from parallelization.
- **Evaluator-optimizer**: generator + evaluator loop. Use when there are clear
  evaluation criteria and iteration provides measurable value.
- **Autonomous agent**: tool loop with environmental feedback, for open-ended
  problems where the number of steps cannot be predicted. Costs: higher latency
  and cost, compounding errors.

Meta-rule: find the simplest solution possible and add complexity only when it
demonstrably improves outcomes. Agentic systems trade latency and cost for task
performance.

### 1.2 Anthropic, "How we built our multi-agent research system" (ANTHROPIC_MAR)

Architecture: Opus lead agent plans, spawns Sonnet subagents in parallel with
isolated context, synthesises; a citation agent post-processes.

Numbers:

- Multi-agent (Opus lead + Sonnet workers) beat single-agent Opus by 90.2% on
  the internal research eval.
- Token usage alone explains ~80% of performance variance; tool-call count and
  model choice explain most of the rest.
- Agents use ~4x the tokens of chat; multi-agent systems ~15x.
- Upgrading the model was a larger gain than doubling the token budget.
- Running 3-5 subagents in parallel (each using 3+ tools in parallel) cut
  research time by up to 90% on complex queries.

When it is worth it: heavy parallelisation, information exceeding one context
window, many complex tools, and task value high enough to pay for it.
When it is not: domains where all agents must share context or have many
inter-dependencies; most coding tasks have fewer truly parallel pieces than
research.

Effort-scaling heuristic (encoded in `worker_count`):

- Simple fact-finding: 1 agent, 3-10 tool calls.
- Direct comparisons: 2-4 subagents, 10-15 calls each.
- Complex research: 10+ subagents with clearly divided responsibilities.

Delegation contract: each subagent brief needs an objective, an output format,
tool/source guidance, and clear boundaries; otherwise agents duplicate work,
leave gaps, or over-spawn (e.g. 50 subagents for a simple query). Start evals
with ~20 representative queries; use an LLM judge with a rubric; trace
everything because runs are non-deterministic.

### 1.3 Anthropic, context engineering and tools (ANTHROPIC_CTX)

Context is a finite attention budget subject to "context rot". Long-horizon
techniques and their fit:

- **Compaction** (summarise and re-initialise) for long back-and-forth; the
  lightest variant is **tool-result clearing**.
- **Structured note-taking / memory** for iterative work with milestones.
- **Sub-agent architectures** (isolated context per subagent returning a
  1,000-2,000 token summary) for research/analysis where parallel exploration
  pays off.

Tools: more tools do not mean better outcomes; consolidate overlapping tools,
namespace them, return semantic identifiers, paginate/truncate outputs. If a
human engineer cannot say which tool applies, the agent cannot either. On
retrieval: agentic (grep-style) search is slower but more accurate and
transparent than embeddings; add semantic search only if you need speed.

Claude Code subagent guidance: delegate when output is verbose and not needed
in the main context, the work is self-contained, or there are independent
investigations to run in parallel. Concrete trigger: exploring ten or more files
or three or more independent pieces of work. Keep it in the main conversation
when phases share significant context, when there is frequent back-and-forth,
or when latency matters (subagents start cold). Never have two subagents edit
the same file. Defaults: 20 concurrent subagents, 3 nesting levels.

### 1.4 OpenAI, "A practical guide to building agents" (OPENAI_PG)

Build an agent only for complex decision-making, hard-to-maintain rule sets, or
heavy reliance on unstructured data; otherwise a deterministic solution may
suffice. Prototype with the most capable model, then swap in smaller models
where accuracy holds.

Single agent first: maximise a single agent's capabilities before splitting.
Split triggers:

- **Complex logic**: prompts with many conditional branches that no longer
  scale as templates.
- **Tool overload**: it is not the number of tools but their overlap. Some
  systems manage 15+ distinct tools; others struggle with fewer than 10
  overlapping ones. Split only if improving tool clarity does not help.

Two multi-agent shapes: **manager** (agents as tools; one agent owns the user
and the final synthesis) and **decentralised handoffs** (one-way transfer of
control and conversation state; ideal for triage or when a specialist should
fully take over). Human intervention on failure thresholds and on high-risk,
irreversible actions (refunds, payments, cancellations).

### 1.5 Google ADK (GOOGLE_ADK)

Deterministic workflow agents (Sequential, Parallel, Loop) vs. LLM-driven
delegation. Seven patterns: coordinator/dispatcher, sequential pipeline,
parallel fan-out/gather, hierarchical task decomposition (when a task is too
big for one context window), generate-and-review, iterative refinement (with
`max_iterations`), human-in-the-loop for irreversible actions. Guidance: use
LLM-driven delegation for context-dependent routing, deterministic workflows
for predictable processes; start with a sequential chain, debug it, then add
complexity.

### 1.6 LangChain / LangGraph (LANGGRAPH)

Reasons to go multi-agent: specialised knowledge without overwhelming one
context window, independent team ownership, concurrent specialised workers.
Pattern comparison from the docs (calls per request):

| Scenario | Subagents (supervisor) | Handoffs | Skills | Router |
|---|---|---|---|---|
| One-shot request | 4 | 3 | 3 | 3 |
| Repeat request | 8 | 5 | 5 | 6 |
| Multi-domain | 5 (~9K tokens) | 7+ (~14K+) | 3 (~15K) | 5 (~9K) |

Guidance: subagents for distributed development and parallelisation; handoffs
for repeat requests and direct user interaction; router for clear input
categories with lightweight classification; supervisor for conversation-aware
orchestration; hierarchical (supervisor of supervisors) only at scale. For most
handoff cases a single agent with middleware is simpler.

### 1.7 Microsoft (MS_AF)

Complexity ladder: direct model call -> single agent with tools ("often the
right default for enterprise use cases") -> multi-agent orchestration, justified
only by prompt complexity, tool overload, security boundaries, or parallel
specialisation. "Decision-making and flow-control overhead often exceed the
benefits."

Patterns with avoid-when rules: **sequential** (avoid when stages are parallel
or early errors propagate unchecked), **concurrent** (avoid without a conflict
resolution strategy or when order matters), **group chat** (read-only
deliberation, keep to three or fewer agents, needs an objective completion
check), **handoff** (avoid when the right agent is identifiable from the input;
use a dispatcher), **Magentic** dynamic planner (open-ended, side-effecting
tools, slowest and most cost-variable; cap rounds/stalls/resets).

### 1.8 Quantitative and critical studies

**MAST (Cemri et al.)**: 1,600+ traces across 7 frameworks; failure rates 41%
to 87%. Failure classes: specification/system design 43.9% (step repetition
15.7%, unaware of termination 12.4%), inter-agent misalignment 31.8%
(reasoning-action mismatch 13.2%), task verification 24.5%. Fixes to roles,
termination and verification gave at most +15.6%. Failures stem from
organisational design and coordination, not individual agent capability.

**Towards a Science of Scaling Agent Systems (Google/MIT)**: 260 configurations,
5 architectures, 6 benchmarks. Gains: Finance-Agent +80.8% (centralised),
BrowseComp-Plus +9.2%, Workbench +5.6%, Terminal-Bench +1.7%. Losses: PlanCraft
-39% to -70%, SWE-bench Verified -2.1%. **Capability saturation**: when the
single-agent baseline already exceeds ~45% accuracy, adding agents yields
negative returns. Tool-heavy (16-tool) workflows suffer coordination overhead.
Error amplification vs. single agent: centralised 4.4x, hybrid 5.1x,
decentralised 7.8x, independent 17.2x. Token overhead vs. single agent:
independent +58%, decentralised +263%, centralised +285%, hybrid +515%.

**Cognition, "Don't build multi-agents"**: share full context and traces;
actions carry implicit decisions and parallel workers make conflicting ones.
Parallel subagents are fragile for coding; prefer a single-threaded agent with
a context-compression model. Claude Code uses subagents only for read-only
question answering, never parallel code writing.

### 1.9 Retrieval (RAG)

Classic RAG is retrieve-once-then-generate with predictable latency; agentic RAG
is a retrieve-reason-decide loop whose latency and cost become distributions
with p95 tails. Rules: single-hop, single-source, latency-sensitive -> classic
RAG; multi-hop, cross-source, self-correcting -> agentic RAG, tolerating 3x-20x
latency (Search-R1 needs 16-22x the inference time of naive RAG for 27% -> 43%
EM on HotpotQA). Cap retrieval iterations (~4). Mixed traffic -> adaptive RAG:
classify, single-pass by default, escalate on failure signals (missing
citations, low confidence, contradictions, repeated follow-ups). Many
heterogeneous sources -> single-agent router first; subagent-per-source only
when per-source exploration would overflow the main context or parallel latency
reduction is needed.

---

## 2. Consolidated decision framework (what the engine implements)

### Input dimensions

| Dimension | Profile field(s) |
|---|---|
| Step predictability | `steps_predictable`, `task_complexity` |
| Decomposability / independence | `parallel_subtasks`, `tool_dependency` |
| Breadth | `scope_breadth`, `knowledge_sources` |
| Context volume | `context_tokens_per_task` |
| Tool count and overlap | `tool_count`, `tool_overlap` |
| Retrieval need | `retrieval_depth` |
| Single-agent baseline | `single_agent_baseline` |
| Evaluability | `verifiability` |
| Latency budget | `latency_budget_s` |
| Error cost / reversibility | `accuracy_priority`, `tool_side_effects`, `error_recoverability`, `human_in_loop` |
| Task value / cost | `cost_sensitivity`, `requests_per_day` |
| Conversation ownership | `interaction`, `output_type` |

### Rule tiers

- **Tier 0 - no agent**: fixed path, no tools, single step -> direct call.
- **Tier 1 - workflows** (predictable steps): prompt chain for fixed sequential
  stages; router for classifiable categories (and model-tier routing);
  sectioning for known independent sub-tasks; voting for high-stakes decisions
  with comparable answers; evaluator loop only with clear criteria; human gate
  before irreversible actions.
- **Tier 2 - single agent** (unpredictable path, one context suffices, ~15
  distinct tools or fewer): the default. Stay here when the baseline already
  exceeds ~45%, when sub-tasks share mutable state, or when work is sequential.
  Use compaction, tool-result clearing and memory for length.
- **Tier 3 - multi-agent** requires a hard trigger (3+ independent pieces,
  context overflow, persistent tool overlap, unscalable prompt logic, security
  boundaries) and no blocker (shared mutable state, task value too low for
  ~15x tokens, real-time latency without parallel speed-up, baseline > 45%).
  Default to centralised orchestrator-workers (lowest error amplification);
  size fan-out by the Anthropic heuristic; handoffs only when a specialist must
  own the user; hierarchy only at 10+ workers clustered into domains.
- **Tier 4 - retrieval**: classic RAG for single-hop; agentic retrieval capped
  at ~4 iterations for multi-hop; adaptive RAG for mixed traffic;
  subagent-per-source only for deep, parallel exploration.

### Expected effects per topology

| Topology | Latency vs. one call | Tokens | Accuracy effect | Main risk |
|---|---|---|---|---|
| Direct call | 1x | 1x | baseline | model limits |
| Prompt chain | ~n serial calls | ~n | higher per-step accuracy | early-stage error propagation |
| Routing | +1 cheap call | ~1x | specialised prompts/models | misroutes |
| Sectioning | ~slowest branch | n branches | coverage and speed | merge conflicts |
| Voting | ~one branch | n | higher confidence | pure cost |
| Evaluator loop | k iterations | k | only with clear criteria | unbounded loops |
| Single agent | bounded by turn limit | ~4x chat | best for sequential work | compounding errors |
| Orchestrator-workers | faster than single agent when parallel | ~15x chat (+285% vs single agent) | +90% on breadth research; negative on sequential planning | 41-87% failure rates in studied frameworks; 4.4x error amplification |
| Handoffs | serial + transfer calls | ~1.3-2x single agent | triage / stateful flows | loops; 7.8x error amplification |
| Hierarchical | extra hops each level | ~25x chat | only at very large breadth | debugging, briefing loss |

### Always-on guardrails the engine emits

1. Start one level simpler than the rule suggests; promote only on measured
   eval failure (~20 representative queries).
2. Every loop, handoff chain and orchestrator has explicit termination limits.
3. Every multi-agent design has a verification step at the orchestrator.
4. Every irreversible action has a gate (human or checkpoint/rollback).
5. Prefer upgrading the model over adding agents or tokens.

---

## 3. How the documented patterns map to VG Select topologies

The sources use different names for the same shapes. This table is the
cross-reference used by the rules, the plan and the skeleton templates.

| VG Select topology | Anthropic | OpenAI | Google ADK | LangChain / LangGraph | Microsoft |
|---|---|---|---|---|---|
| Single call | Augmented LLM | Direct model call | LlmAgent (no tools) | Single model call | Direct model call |
| Single agent | Autonomous agent | Single agent with tools | LlmAgent with tools | Agent (`create_agent`) | Single agent with tools |
| Prompt chain | Prompt chaining | Code-driven orchestration | Sequential pipeline (SequentialAgent) | Custom workflow / RunnableSequence | Sequential |
| Router | Routing | Deterministic dispatcher | Coordinator/Dispatcher | Router | Handoff avoided when routing is decidable up front |
| Parallel sectioning | Parallelization: sectioning | Code-driven fan-out | Parallel fan-out/gather (ParallelAgent) | `Send` fan-out | Concurrent |
| Parallel voting | Parallelization: voting | - | - | `Send` fan-out + aggregation | Concurrent (quorum / majority) |
| Evaluator-optimizer | Evaluator-optimizer | - | Generate-and-review; Iterative refinement (LoopAgent) | Custom loop with conditional edge | Maker-checker |
| Orchestrator + workers | Orchestrator-workers; multi-agent research system | Manager (agents as tools) | Hierarchical task decomposition (AgentTool) | Subagents / Supervisor | Magentic (dynamic planner) |
| Hierarchical | 10+ subagents with divided responsibilities | - | Multi-level hierarchy | Supervisor of supervisors | - |
| Handoffs | - | Decentralised handoffs | LLM-driven `transfer_to_agent` | Handoffs (swarm) | Handoff |

Group chat / debate (Microsoft) is not a separate topology here; its
read-only-deliberation use cases are covered by parallel voting (independent
perspectives merged by a judge) and the evaluator-optimizer loop.
