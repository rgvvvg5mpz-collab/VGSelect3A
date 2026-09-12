---
name: vg-select-3a
description: Recommend the architecture (topology) of an agentic LLM application - single agent vs workflow vs orchestrator + subagents - balancing latency and accuracy. Scans the current repository first, then runs VG Select 3A (Automated Agentic Architecture). Use when the user asks which agent architecture to use, whether to split into subagents, how to decompose an agent, or to review an existing agent's topology.
---

# VG Select: 3A - Automated Agentic Architecture

You recommend an architecture for an agentic application using the `vgselect`
engine in this repository (or a deployed VG Select service). The engine is
deterministic and every rule is cited; your job is to gather a truthful
profile, run it, and explain the result. Do not invent numbers the engine did
not produce.

## Workflow

1. **Locate the engine.** Prefer, in order:
   - a deployed service: if `VGSELECT_URL` is set, use `POST $VGSELECT_URL/api/v1/scan/upload` (zip of the repo), `/api/v1/recommend`, `/api/v1/recommend/pdf` and `/api/v1/recommend/skeleton` (see `docs/CONSUMER_GUIDE.html`); pass the `scan` object from the scan response back to the PDF and skeleton calls;
   - the CLI: `vgselect` on PATH, or `python -m vgselect3a.cli` with `PYTHONPATH=src` from this repository.
   If none is available, install with `pip install -e .` from the VG Select repository and continue.

2. **Scan the repository the user is asking about** (default: the current working directory):
   ```bash
   vgselect scan . --format json --profile-out /tmp/vgselect_profile.json
   ```
   Read the inferred fields and their confidence. Treat inferences under 50% confidence as guesses.

3. **Fill the gaps from what you know.** The scan cannot see latency budgets, accuracy priority, cost sensitivity, or request volume. Take them from the user's message, CLAUDE.md, READMEs, or ask one short question with the fields that matter most:
   `latency_budget_s`, `accuracy_priority` (1-5), `cost_sensitivity` (1-5), `requests_per_day`, `parallel_subtasks`, `context_tokens_per_task`.
   Run `vgselect fields` for definitions. If the user has an eval, ask for the single-agent baseline accuracy (`single_agent_baseline`, 0-1); it changes the answer. Also confirm `data_sensitivity` (public/internal/confidential/restricted) and any provider, platform or region constraints: pass them as `--providers`, `--platforms`, `--regions`, and `--catalog` if the team keeps its own model catalog (see `docs/MODEL_CATALOG.html`).

4. **Recommend.** Merge the corrections into the profile and run:
   ```bash
   vgselect recommend --scan . --profile /tmp/vgselect_profile.json --format md
   ```
   (`--set key=value` overrides individual fields.) Use `--format json` when you need the structured plan.

5. **Report to the user** in this order, briefly:
   - the recommended topology and the one-line reason;
   - how it compares with what the repository implements today (the "Gap" table);
   - the latency/accuracy frontier: the fastest viable option and the most accurate one, with estimated seconds and token multiples;
   - the decomposition plan: components, what runs in parallel;
   - the model per role from the catalog (chosen, effort, fallback), any unfilled roles and why, and any selection warnings;
   - the three most important cross-cutting recommendations (evals first, termination limits, verification, gating of irreversible tools);
   - the assumptions behind the estimates and which inferred fields the user should confirm.
   Then produce the two deliverables and tell the user where they are:
   ```bash
   vgselect recommend --scan . --profile /tmp/vgselect_profile.json --format pdf --out docs/architecture/vgselect-architecture.pdf
   vgselect scaffold  --scan . --profile /tmp/vgselect_profile.json --out /tmp/vgselect-skeleton.zip
   ```
   (`--format pdf` needs the `pdf` extra: `pip install -e '.[pdf]'`.) Offer to unzip the skeleton into a directory the user names (never over an existing project without asking) and to run its smoke test (`pip install -r requirements.txt && pytest`). Summarise what the skeleton contains: graph wiring for the topology, role agents on the recommended models, tool stubs named after the repository's tools, termination limits, and the TODOs to fill in.

6. **If the agent already runs in production or has eval traces**, ask for a traces export (JSONL `vgselect-trace/1`, LangSmith run export, or OTel GenAI spans; format in `docs/REPORT_CARD.html`) and add `--traces FILE` to the commands above, or run `vgselect report-card --scan . --traces FILE`. Report the overall grade, the three complexity levels, the mismatch flags with their actions, the weakest dimension, and the per-agent rows for multi-agent systems.

## Rules of thumb the engine encodes (so you can sanity-check output)

- Start simple: single call -> single agent -> workflow -> multi-agent, promoting only on measured need.
- Multi-agent pays off for breadth-first research, context overflow, and independent sub-tasks; it costs ~15x chat tokens and adds coordination failure modes.
- Sequential, shared-state work (most coding) stays single-agent; use read-only subagents for exploration only.
- Above a ~45% single-agent baseline, adding agents tends to hurt.
- Irreversible actions need a gated, dedicated tool with human or checkpoint approval.

## Do not

- Do not run `vgselect describe` (it calls the Claude API) unless the user asks and credentials are configured.
- Do not scan directories outside the user's project without saying so.
- Do not present estimated latency or cost as measurements.
