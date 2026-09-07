# VG Select: 3A (Automated Agentic Architecture)

VG Select: 3A recommends the architecture of an agentic LLM application. It
scans a code repository to learn what the application does (tools, data
sources, side effects, existing agent loops), combines that with a workload
profile (complexity, latency budget, accuracy priority, cost sensitivity), and
ranks ten topologies with evidence-cited rules:

single call, single agent with tools, prompt chain, router, parallel
sectioning, parallel voting, evaluator-optimizer, orchestrator + worker
subagents, hierarchical teams, specialist handoffs.

For each option it estimates latency and cost, shows the latency/accuracy
frontier, and turns the winner into a concrete decomposition plan
(orchestrator, subagents, model per role, effort, parallel groups, briefing
rules, guardrails) with a diagram.

Every recommendation produces two deliverables:

- an **architecture document (PDF)**: summary, evidence, scan findings and
  current-vs-recommended gap, options compared, plan with diagram, next
  steps, assumptions, sources;
- a **downloadable agent skeleton (zip)** for LangChain/LangGraph: the
  `StateGraph` wired for the recommended topology, role agents on the
  recommended model tiers, tool stubs, termination limits, and a smoke test.
  All ten templates compile and pass their smoke test against LangGraph 1.2.

## Documents

| Audience | Document |
|---|---|
| Executives | [Executive brief](docs/EXECUTIVE_BRIEF.html) - what it is and why it helps the enterprise (one page, print-ready) |
| Engineers deploying the service | [Deployment guide](docs/DEPLOYMENT.html) - install, Docker, configuration, security model, operations |
| Engineers consuming the service, CLI or skill | [Consumer guide](docs/CONSUMER_GUIDE.md) - endpoints, profile fields, reading results, PDF and skeleton, CI use |
| Architects and reviewers | [Methodology](docs/METHODOLOGY.md) - how the recommendation, estimates, plan and skeleton are computed |
| Everyone | [Industry guidance](docs/industry_guidance.md) - the evidence behind every rule and how patterns map to topologies |
| API consumers | [OpenAPI spec](openapi/vgselect-3a.openapi.json) - also live at `/openapi.json`, Swagger at `/docs` |
| Claude Code users | [Skill](.claude/skills/vg-select-3a/SKILL.md) - scan, recommend, and produce both deliverables from the editor |
| Maintainers | [Changelog](CHANGELOG.md) |

## Quick start

Service with web UI (recommended):

```bash
pip install -e '.[service]'           # FastAPI, Uvicorn, reportlab (PDF)
vgselect-service                      # UI at http://localhost:8080, API docs at /docs
```

Command line:

```bash
pip install -e '.[pdf]'                                                # core engine + PDF
vgselect scan .                                                        # what the code reveals
vgselect recommend --scan . --set latency_budget_s=8 --set accuracy_priority=4
vgselect recommend --example deep_research                             # bundled scenario, Markdown report
vgselect recommend --profile my_app.json --format json                 # md | json | mermaid | svg | pdf
vgselect recommend --scan . --format pdf --out architecture.pdf        # architecture document
vgselect scaffold --scan . --out my-agent.zip                          # LangGraph project skeleton
vgselect wizard --out my_app.json                                      # interactive questionnaire
vgselect fields                                                        # every profile field explained
```

Python:

```python
from vgselect3a import WorkloadProfile, recommend
from vgselect3a.scanner import scan_repository, merge_profile

scan = scan_repository(".")
profile = WorkloadProfile.from_dict(merge_profile(scan, {"latency_budget_s": 8, "accuracy_priority": 4}))
rec = recommend(profile, scan=scan)
print(rec.headline)
rec.to_markdown(); rec.to_json(); rec.to_svg()
open("architecture.pdf", "wb").write(rec.to_pdf())
open("my-agent.zip", "wb").write(rec.to_skeleton("langgraph"))
```

Docker:

```bash
docker build -t vgselect-3a . && docker run --rm -p 8080:8080 -v $PWD:/scan:ro -e VGSELECT_SCAN_ROOTS=/scan vgselect-3a
```

## Install extras

| Extra | Adds | Needed for |
|---|---|---|
| none | nothing (standard library only) | engine, scanner, Markdown/JSON/Mermaid/SVG, skeleton zip |
| `pdf` | reportlab | `--format pdf`, `Recommendation.to_pdf()` |
| `service` | FastAPI, Uvicorn, Pydantic, python-multipart, reportlab | `vgselect-service`, the UI and API |
| `llm` | anthropic, pydantic | `vgselect describe` and `/api/v1/describe` (prose to profile with Claude) |
| `dev` | pytest, httpx plus the service stack | `pytest` |

## The web UI

A guided three-step flow in Vanguard colours. Start from a bundled scenario, a
repository scan (zip upload, server path, or git URL), a prose description, or
a blank profile. Describe the workload with pill groups, switches, sliders and
unit-labelled numbers; every field, table header and citation has a tooltip,
and a live sentence restates what you are asking for. The result leads with a
verdict card (architecture, budget badge, latency bar, cost, tokens, score),
then the reasons with citations, what the scan found and the gap from the
current implementation, a comparison table with per-row rule expansions, a
latency-versus-fit chart with the budget line and frontier, the build plan as
cards plus a server-rendered diagram, a next-steps checklist, and the
assumptions. Buttons on the verdict card download the PDF, the LangGraph
skeleton, Markdown and JSON. No external front-end dependencies.

## Repository layout

```
src/vgselect3a/
  profile.py        workload profile fields (single source of truth for CLI, API, UI, LLM intake)
  scanner.py        repository scanner -> inferred profile with confidence + file:line evidence
  rules.py          41 cited scoring rules
  recommender.py    viability, latency/cost balancing, Pareto frontier, to_pdf/to_skeleton
  estimator.py      call-tree latency/cost model per topology
  decomposition.py  subagent plan, model tiering, guardrails
  render.py         Markdown / JSON / Mermaid / SVG and the shared diagram layout
  pdf_report.py     architecture document (PDF, reportlab)
  scaffold/         LangGraph project skeleton generator, one template per topology
  cli.py            vgselect scan | recommend | scaffold | wizard | describe | examples | fields
  intake_llm.py     optional Claude-powered prose -> profile
  service/          FastAPI app, Pydantic schemas (generated from the profile), static UI
  examples/         eight canonical profiles
docs/               executive brief, deployment guide, consumer guide, methodology, industry guidance
openapi/            exported OpenAPI 3 document (scripts/export_openapi.py)
scripts/            OpenAPI export
.claude/skills/     Claude Code skill
.claude/launch.json dev-server config for the Claude Code browser preview
tests/              engine, scanner (fixture repo), API, PDF and skeleton tests
Dockerfile          production image (non-root, healthcheck)
```

## Tests

```bash
pip install -e '.[dev]' && pytest
```

55 tests: eight canonical scenarios, monotonicity of the latency/accuracy
balance, viability, the scanner against a fixture repository, every API
endpoint, PDF generation, and syntax checks of the generated skeleton for all
ten topologies. To exercise the skeletons against the real library, unzip one
and run its own `pytest` with `langgraph`, `langchain` and
`langchain-anthropic` installed.

Estimates are order-of-magnitude heuristics for ranking, not production
predictions. Tune `MODEL_TIERS` in `topologies.py` and the constants in
`estimator.py` to your measurements.
