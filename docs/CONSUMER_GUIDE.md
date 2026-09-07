# VG Select: 3A — Consumer Guide

For engineers who want an architecture recommendation for an agentic
application from a running VG Select: 3A service, the CLI, the Python library
or the Claude Code skill. Deployers should read
[DEPLOYMENT.html](DEPLOYMENT.html); the reasoning behind the answers is in
[METHODOLOGY.md](METHODOLOGY.md); the evidence is in
[industry_guidance.md](industry_guidance.md).

## 1. The 60-second version

```bash
export VGSELECT_URL=https://vgselect.internal.example.com

# 1. Scan your repository (zip it; node_modules, .git, venv are skipped by the scanner)
zip -qr /tmp/repo.zip . -x '*.git*' -x '*node_modules*'
curl -s "$VGSELECT_URL/api/v1/scan/upload" \
  -F archive=@/tmp/repo.zip \
  -F 'overrides={"latency_budget_s": 8, "accuracy_priority": 4, "cost_sensitivity": 3, "requests_per_day": 20000}' \
  > result.json

# 2. Read the answer
python -c 'import json; d=json.load(open("result.json")); print(d["recommendation"]["headline"])'

# 3. Get the two deliverables (the PDF and the LangGraph skeleton) for that answer
python -c 'import json; d=json.load(open("result.json")); json.dump({"profile": d["profile"], "scan": d["scan"]}, open("request.json","w"))'
curl -s "$VGSELECT_URL/api/v1/recommend/pdf"      -H 'content-type: application/json' -d @request.json -o architecture.pdf
curl -s "$VGSELECT_URL/api/v1/recommend/skeleton" -H 'content-type: application/json' -d @request.json -o my-agent.zip
```

The scan infers what the code reveals (tools, retrieval, side effects, current
agent loop, serving surface). You supply what code cannot show: latency budget,
accuracy priority, cost sensitivity, volume. Review the inferred fields and
their confidence in `result.json["scan"]["inferred"]`, correct any that are
wrong via `overrides`, and re-run.

Or open the UI at `$VGSELECT_URL/` and do the same interactively: it has the
same scan, profile and download steps with a tooltip on every field.

## 2. Ways to consume

| Surface | When |
|---|---|
| Web UI at `/` | Design reviews and first looks. Three steps: start from a scenario, scan, description or blank; describe the workload; get the verdict, comparison, chart, plan, next steps and both downloads. |
| REST API (`/api/v1/*`, OpenAPI at `/openapi.json`, Swagger at `/docs`, ReDoc at `/redoc`) | CI checks, architecture linting, internal tooling, generated clients |
| CLI `vgselect` (`pip install -e '.[pdf]'` from this repository) | Local use without the service; the same reports, PDF and skeleton |
| Claude Code skill `.claude/skills/vg-select-3a` | Ask Claude Code "which architecture should this agent use?"; it scans, asks for the missing fields, recommends, and writes the PDF and skeleton |
| Python API `from vgselect3a import WorkloadProfile, recommend` | Embedding in your own tools; `rec.to_pdf()`, `rec.to_skeleton()` |

## 3. Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/v1/recommend` | `{"profile": {...}, "include_markdown": true}` | `RecommendationOut` |
| POST | `/api/v1/scan` | `{"path": "/scan/repo"}` or `{"git_url": "https://..."}` plus optional `overrides`, `recommend`, `include_markdown` | `ScanOut` (`scan`, merged `profile`, `recommendation`) |
| POST | `/api/v1/scan/upload` | multipart: `archive` (zip), `overrides` (JSON string), `recommend`, `include_markdown` | `ScanOut` |
| POST | `/api/v1/recommend/pdf` | `{"profile": {...}, "scan": <scan object, optional>}` | `application/pdf` architecture document (503 if the server lacks reportlab) |
| POST | `/api/v1/recommend/skeleton` | `{"profile": {...}, "scan": <optional>, "framework": "langgraph"}` | `application/zip` runnable project skeleton |
| POST | `/api/v1/describe` | `{"text": "prose description", "model": "claude-opus-5", "overrides": {...}}` | `RecommendationOut` (503 if the server has no Anthropic credentials) |
| GET | `/api/v1/fields` | | Profile field definitions (name, kind, choices, range, description, group) |
| GET | `/api/v1/examples` | | Eight bundled example profiles |
| GET | `/api/v1/topologies` | | The ten topologies with summaries and trade-offs |
| GET | `/api/v1/citations` | | Citation key to source name, for rendering rule rationales |
| GET | `/api/v1/catalog` | | The model ecosystem catalog (models, providers, platforms, regions) |
| POST | `/api/v1/catalog/validate` | `[ModelSpec, ...]` | Validates entries; lists illustrative ones |
| GET | `/health` | | Status, version, scan roots, and whether git clone, describe and PDF are enabled |

Every recommend, scan, PDF and skeleton request accepts an optional `policy`
(`allowed_providers`, `blocked_providers`, `allowed_platforms`, `regions`,
`require_verified`, `require_approved`, `prefer_provider`) and optional
`catalog_models` (extra or overriding catalog entries for that request). See
[MODEL_CATALOG.md](MODEL_CATALOG.md).

Path scanning and git cloning are enabled per deployment; `GET /health` tells
you which are on. Zip upload always works. The `scan` object returned by a scan
call can be passed back to the PDF and skeleton endpoints so the document
includes the scan findings and gap.

## 4. The profile

Every field has a default, so you can send only what you know. Run
`GET /api/v1/fields` or `vgselect fields` for the full list. The ones that
change the answer most (marked "key" in the UI):

| Field | Meaning |
|---|---|
| `task_complexity` | trivial, simple, moderate, complex, open_ended |
| `steps_predictable` | Can the steps be fixed in code (workflow) or must the model choose them (agent)? |
| `parallel_subtasks` | Independent pieces of work per request that could run concurrently |
| `scope_breadth` | Distinct domains one request spans |
| `tool_count`, `tool_calls_per_task`, `tool_dependency`, `tool_side_effects`, `tool_overlap`, `tool_latency_s` | Tool surface |
| `knowledge_sources`, `retrieval_depth`, `context_tokens_per_task` | Retrieval and reading load |
| `accuracy_priority` (1-5), `verifiability`, `error_recoverability`, `single_agent_baseline` | Quality and risk |
| `latency_budget_s`, `interaction`, `requests_per_day`, `cost_sensitivity`, `human_in_loop` | Operating constraints |
| `data_sensitivity` | public / internal / confidential / restricted: only catalog models cleared for this class can staff a role |

Optional lists `domains`, `sources`, `tools`, `subtasks`, `sections` name the
components in the plan and the tool stubs in the skeleton (for example
`sources: ["web", "wiki"]` yields "Researcher: web" and "Researcher: wiki").

## 5. Reading the result

`RecommendationOut` fields:

- `product`, `version`: what produced the result.
- `headline`: the recommendation, its estimated latency versus your budget,
  its token multiplier, and the fastest/most-accurate alternatives when they
  differ. When a scan was supplied it also says whether the topology changes.
- `primary`: the recommended topology id.
- `candidates[]`: all ten topologies, ranked. `score` = `fit` (rule evidence)
  + `latency_adj` + `cost_adj`. `quality_proxy` is the fit excluding latency
  and cost rules. `latency_verdict` is fits / tight / exceeds / far over
  against your budget. `viable=false` means the topology cannot do the job
  (`infeasible_reason`). Each candidate lists its `signals`: rule id, delta,
  rationale, citation; and `estimate.assumptions`.
- `frontier[]`: the Pareto set over (latency, quality_proxy). `fastest_viable`
  and `most_accurate` are the two ends.
- `plan`: components (name, role, `model_id`, `tier`, `effort`, tools,
  `parallel_group`), edges, `briefing_rules` for subagents, and
  `augmentations` (cross-cutting recommendations with citations).
- `mermaid`: a flowchart of the plan for docs and wikis; `svg`: the same
  diagram rendered server-side as standalone SVG.
- `selection`: model per role: `choices[]` with the derived `requirements`,
  `model_id`, `effort`, `fallback_model_id`, per-call latency and cost,
  `alternatives` with scores, `rejected` with reasons, `rationale`; plus
  `warnings`, `unfilled`, `providers_used`. `selected_estimate` re-runs the
  topology estimate on the chosen models; `tiers` lists the reference model per
  capability level used for the ranking.
- `scan`: present when the recommendation came from a scan: frameworks,
  tools, sources, side effects, `current_topology`, `inferred[]` with
  confidence, and `evidence[]` with file:line.
- `report_markdown`: the whole thing as a document you can commit.

Latency and cost are order-of-magnitude estimates for ranking, computed from
published serving assumptions and your tool latency. Do not quote them as
measurements.

## 6. The two deliverables

### Architecture document (PDF)

A4, Vanguard-styled, ready for a design review: summary table, why this
architecture (cited) with counter-signals, repository scan findings and
current-vs-recommended gap when a scan was supplied, options compared with the
winner highlighted, frontier and runners-up, decomposition plan with the
diagram, briefing rules, cross-cutting recommendations, estimate assumptions,
the profile used, and sources.

```bash
curl -s "$VGSELECT_URL/api/v1/recommend/pdf" -H 'content-type: application/json' \
  -d @request.json -o architecture.pdf          # request.json = {"profile": {...}, "scan": {...}}
vgselect recommend --scan . --format pdf --out architecture.pdf
```

In the UI: the "Architecture doc (PDF)" button on the verdict card.

### Agent skeleton (zip, LangChain/LangGraph)

A runnable project for the recommended topology, named `<app>-agent/`:

| File | Contents |
|---|---|
| `app/graph.py` | `StateGraph` wiring for the topology: fan-out with `Send`, conditional edges for routers and evaluator loops, a subgraph per domain lead for hierarchies, handoff routing with a cap |
| `app/agents.py` | Provider-agnostic role agent factory on `langchain.chat_models.init_chat_model` (Anthropic, OpenAI, Azure OpenAI, Google, Bedrock, Mistral, self-hosted OpenAI-compatible, ...); uses `langchain.agents.create_agent` (LangChain 1.x) with a fallback to `langgraph.prebuilt.create_react_agent` |
| `app/config.py` | Model, provider, fallback and effort per role from the catalog selection; `RECURSION_LIMIT`, `MAX_TOOL_CALLS`, `MAX_ITERATIONS`, `MAX_WORKERS`, latency budget |
| `app/tools.py` | `@tool` stubs named after the tools in your profile or scan; an approval hook when irreversible tools exist |
| `app/state.py` | `TypedDict` state with reducers for parallel results |
| `main.py`, `tests/test_graph.py` | Run one request; smoke test that the graph compiles without an API key |
| `README.md`, `ARCHITECTURE.md`, `vgselect_profile.json` | How to run and what to fill in; the full recommendation; the profile it came from |
| `requirements.txt`, `.env.example`, `.gitignore` | Only the integration packages and credentials the chosen providers need |

```bash
curl -s "$VGSELECT_URL/api/v1/recommend/skeleton" -H 'content-type: application/json' \
  -d '{"profile": {...}, "framework": "langgraph"}' -o my-agent.zip
vgselect scaffold --scan . --out my-agent.zip
unzip my-agent.zip && cd *-agent
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
pytest                                   # graph compiles
python main.py "a representative request" # needs ANTHROPIC_API_KEY in .env
```

In the UI: the "LangGraph skeleton (.zip)" button on the verdict card.

Everything marked `TODO` in the skeleton needs product-specific work: tool
bodies, prompts, acceptance criteria. The graph structure, limits and model
tiering are the parts the recommendation determines. All ten templates have
been verified to compile and pass their smoke test against LangGraph 1.2 and
LangChain 1.4.

## 7. Client snippets

Python:

```python
import requests

VG = "https://vgselect.internal.example.com"
profile = {"task_complexity": "complex", "steps_predictable": False, "tool_count": 25,
           "tool_calls_per_task": 40, "output_type": "code_change", "verifiability": "strong",
           "latency_budget_s": 900, "interaction": "long_running", "accuracy_priority": 4}
rec = requests.post(f"{VG}/api/v1/recommend", json={"profile": profile}, timeout=30).json()
print(rec["primary"], rec["headline"])
for c in rec["candidates"][:3]:
    print(c["name"], c["score"], c["estimate"]["latency_s"], c["latency_verdict"])

pdf = requests.post(f"{VG}/api/v1/recommend/pdf", json={"profile": profile}, timeout=60).content
open("architecture.pdf", "wb").write(pdf)
```

TypeScript:

```ts
const res = await fetch(`${VG}/api/v1/recommend`, {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify({ profile: { task_complexity: "moderate", scope_breadth: 3, tool_count: 12, tool_calls_per_task: 3,
                                    tool_side_effects: "irreversible", latency_budget_s: 8, interaction: "multi_turn" } }),
});
const rec = await res.json();
console.log(rec.primary, rec.plan.components.map((c: any) => `${c.name} -> ${c.model_id}`));
```

CLI (no service needed):

```bash
pip install -e '.[pdf]'                           # from this repository
vgselect scan .                                   # what the code reveals (add --format json --profile-out p.json)
vgselect recommend --scan . --set latency_budget_s=8 --set accuracy_priority=4
vgselect recommend --example deep_research --format mermaid
vgselect recommend --scan . --format pdf --out architecture.pdf
vgselect scaffold --scan . --out my-agent.zip
vgselect wizard --out my_app.json                 # interactive questionnaire
vgselect catalog --catalog my_catalog.json        # list/validate the model ecosystem
vgselect recommend --scan . --providers anthropic,self_hosted --regions eu --allow-unverified
```

Generate a typed client from the spec: `openapi-generator-cli generate -i $VG/openapi.json -g python` (or `typescript-fetch`).

## 8. Using it in CI

Fail a pull request when the implemented topology drifts from the agreed one:

```bash
zip -qr repo.zip . -x '*.git*'
curl -sf "$VGSELECT_URL/api/v1/scan/upload" -F archive=@repo.zip -F 'overrides=@architecture/profile.json' -F include_markdown=false > out.json
python - <<'PY'
import json, sys
d = json.load(open("out.json")); rec = d["recommendation"]; cur = d["scan"]["current_topology"]
agreed = json.load(open("architecture/decision.json"))["topology"]
print("current:", cur, "recommended:", rec["primary"], "agreed:", agreed)
sys.exit(0 if cur == agreed else 1)
PY
```

Commit the profile you agreed on (`architecture/profile.json`) so the scan
inferences are always corrected by the same known facts, and commit the PDF
from the design review next to it.

## 9. The Claude Code skill

Copy `.claude/skills/vg-select-3a/` into your project (or `~/.claude/skills/`)
and set `VGSELECT_URL` if you have a deployment. Then ask Claude Code, for
example, "Should this agent be split into subagents?" It scans the repository,
asks for the few fields code cannot reveal, runs the recommender, reports the
topology, the gap from the current implementation, the latency/accuracy
frontier and the plan, and writes the architecture PDF and the skeleton zip.

## 10. FAQ

- **The recommendation is "single agent" but I expected multi-agent.** Check
  `parallel_subtasks`, `retrieval_depth`, `context_tokens_per_task` and
  `single_agent_baseline`. Multi-agent needs independent sub-tasks, context
  overflow, or breadth-first research to score; above a ~45% single-agent
  baseline it is penalised.
- **Everything "exceeds" my latency budget.** The headline names the fastest
  viable option. If nothing fits, the budget is incompatible with the tool
  calls and reading per request; the estimate assumptions list what to cut.
- **Can I trust the scan?** Treat inferences below 50% confidence as guesses.
  Evidence rows show exactly which lines produced each inference.
- **The PDF endpoint returns 503.** The server was installed without the
  `pdf`/`service` extra (reportlab). `GET /health` shows `pdf_enabled`.
- **Which LangGraph version does the skeleton target?** LangChain 1.x with
  LangGraph 1.x; it falls back to the older prebuilt agent on LangGraph 0.2/0.3.
  Other frameworks are not generated yet; the `framework` parameter exists so
  more can be added (`src/vgselect3a/scaffold/`).
- **Which models does the plan assume?** Whatever the catalog and policy
  allow. With the bundled catalog and default policy that is Claude Opus 5 for
  orchestration/synthesis, Sonnet 5 for workers and Haiku 4.5 for routers,
  because only the Anthropic entries are verified. Register your OpenAI,
  Google, self-hosted or other models in the catalog (see MODEL_CATALOG.md)
  and the selector will use them where they fit.
- **A role is "unfilled".** No catalog model passed the hard filters (typically
  data class, approval, region or capability). The table lists the rejection
  reasons; clear a model for that data class, approve it, or lower the role's
  ambition by changing the topology or budget.
