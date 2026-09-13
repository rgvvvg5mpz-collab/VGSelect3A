# VG Select: 3A (Automated Agentic Architecture)

VG Select: 3A decides how an agentic LLM application should be built, and
which model should run each part of it.

It scans a code repository to learn what the application does (tools, data
sources, side effects, existing agent loops), combines that with a workload
profile (complexity, latency budget, accuracy priority, cost sensitivity, data
sensitivity), and ranks ten topologies with evidence-cited rules:

single call, single agent with tools, prompt chain, router, parallel
sectioning, parallel voting, evaluator-optimizer, orchestrator + worker
subagents, hierarchical teams, specialist handoffs.

For each option it estimates latency and cost, shows the latency/accuracy
frontier, and turns the winner into a decomposition plan (orchestrator,
subagents, effort, parallel groups, briefing rules, guardrails) with a
diagram. Every role in that plan is then staffed from your **model ecosystem
catalog** (Anthropic, OpenAI, Google, self-hosted open-weights, or any provider
you register) under a governance policy, with a fallback per role and a reason
for every rejected model.

For an agent that already exists, the **agent report card** grades it: design
complexity from the code, behavioural complexity from run-time traces
(loops, limit hits, branching, consistency, tokens, latency, cost per
completed task), task complexity from the profile, mismatch flags between the
three, graded dimensions, and a card per agent in multi-agent systems. See
[docs/REPORT_CARD.html](docs/REPORT_CARD.html).

Every recommendation produces two deliverables:

- an **architecture document (PDF)**: summary, evidence, scan findings and
  current-vs-recommended gap, options compared, plan with diagram, model per
  role, next steps, assumptions, sources;
- a **runnable agent skeleton (zip)** for LangChain/LangGraph: the
  `StateGraph` wired for the recommended topology, provider-aware role agents
  on the chosen models, tool stubs, termination limits, and a smoke test. All
  ten templates compile and pass their smoke test against LangGraph 1.2.

## How it works

```
repository ──scan──▶ inferred profile ─┐
prose ──Claude intake (optional)───────┼─merge─▶ workload profile
manual profile / bundled example ──────┘              │
                                                      ▼
   41 cited rules ──▶ viability ──▶ latency/cost estimates on catalog reference models ──▶ balance ──▶ ranked topologies
                                                      │
                                                      ▼
                          decomposition plan ──▶ per-role requirements ──▶ model selection from the catalog under policy
                                                      │
                                                      ▼
                     Markdown / JSON / SVG / web UI · architecture PDF · LangGraph skeleton (zip)
```

1. **Scan** ([scanner.py](src/vgselect3a/scanner.py)): pattern tables over source and dependency files infer 17 profile fields with a confidence and file:line evidence, and identify the topology the code implements today. Prose is never evidence.
2. **Rules** ([rules.py](src/vgselect3a/rules.py)): 41 rules from Anthropic, OpenAI, Google, Microsoft, LangChain, MAST and the agent-scaling study add or subtract fit per topology; each carries a citation resolved in [docs/industry_guidance.html](docs/industry_guidance.html).
3. **Viability and estimates** ([recommender.py](src/vgselect3a/recommender.py), [estimator.py](src/vgselect3a/estimator.py)): options that cannot do the job rank last; a call tree per topology gives critical-path latency and list-price cost on reference models the catalog and policy allow.
4. **Balance**: score = fit + latency adjustment + cost adjustment. Higher accuracy priority tolerates lateness; higher cost sensitivity penalises expensive designs. The Pareto frontier and the fastest and most accurate options are reported.
5. **Plan and model selection** ([decomposition.py](src/vgselect3a/decomposition.py), [requirements.py](src/vgselect3a/requirements.py), [model_selector.py](src/vgselect3a/model_selector.py)): roles are sized by published heuristics; each role's requirements (capability level, latency share, context, tools, structured output, stakes, volume, data class) are matched against the catalog: hard filters, capability floor that measured evidence can override, quality/latency/cost scoring, orchestrator never weaker than its workers, independent verifiers, one model per loop, fallback on another provider, and unfilled-role feedback.
6. **Deliverables** ([pdf_report.py](src/vgselect3a/pdf_report.py), [scaffold/](src/vgselect3a/scaffold/)): the PDF and the skeleton are generated from the same objects as the report.

Full write-up: [docs/METHODOLOGY.html](docs/METHODOLOGY.html) and [docs/MODEL_CATALOG.html](docs/MODEL_CATALOG.html).

## Documents

| Audience | Document |
|---|---|
| Executives | [Executive brief](docs/EXECUTIVE_BRIEF.html) - what it is and why it helps the enterprise (one page, print-ready) |
| People using the deployed app | [User guide](docs/USER_GUIDE.html) - every step, field and result panel explained; also served by the app at `/guide` |
| Engineers deploying the service | [Deployment guide](docs/DEPLOYMENT.html) - architecture, install (VM, systemd, Docker, Compose, Kubernetes), configuration, model catalog management, security, proxy and auth, operations, troubleshooting, CI/CD, go-live checklist |
| Engineers consuming the service, CLI or skill | [Consumer guide](docs/CONSUMER_GUIDE.html) - endpoints, profile fields, policy, reading results, PDF and skeleton, CI use |
| Architects and reviewers | [Methodology](docs/METHODOLOGY.html) - how the recommendation, estimates, plan, model selection and skeleton are computed |
| Platform teams | [Model catalog](docs/MODEL_CATALOG.html) - catalog schema, per-role requirements, the selection procedure, policy, maintenance |
| Developers with a running agent | [Report card](docs/REPORT_CARD.html) - complexity axes, metrics, grading, mismatch flags, trace format |
| Everyone | [Industry guidance](docs/industry_guidance.html) - the evidence behind every rule and how vendor patterns map to topologies |
| API consumers | [OpenAPI spec](openapi/vgselect-3a.openapi.json) - also live at `/openapi.json`, Swagger at `/docs` |
| Claude Code users | [Skill](.claude/skills/vg-select-3a/SKILL.md) - scan, recommend, and produce both deliverables from the editor |
| Everyone | [Case studies](case_study/README.md) - three fictional applications run end to end: scan, recommendation, model per role, report card, PDF, skeleton |
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
vgselect catalog                                                       # the model ecosystem
vgselect report-card --scan . --traces runs.jsonl                      # grade an existing agent from code + traces
vgselect recommend --scan . --catalog my_catalog.json --providers anthropic,self_hosted --regions eu
vgselect wizard --out my_app.json                                      # interactive questionnaire
vgselect fields                                                        # every profile field explained
```

Python:

```python
from vgselect3a import WorkloadProfile, recommend
from vgselect3a.catalog import Catalog
from vgselect3a.model_selector import SelectionPolicy
from vgselect3a.scanner import merge_profile, scan_repository

scan = scan_repository(".")
profile = WorkloadProfile.from_dict(merge_profile(scan, {"latency_budget_s": 8, "accuracy_priority": 4, "data_sensitivity": "confidential"}))
rec = recommend(profile, scan=scan, catalog=Catalog.load("my_catalog.json"), policy=SelectionPolicy(regions=["eu"]))
print(rec.headline)
for choice in rec.selection.choices:                      # model per role
    print(choice.component_id, choice.model_id, choice.effort, choice.fallback_model_id)
rec.to_markdown(); rec.to_json(); rec.to_svg()
open("architecture.pdf", "wb").write(rec.to_pdf())
open("my-agent.zip", "wb").write(rec.to_skeleton("langgraph"))
```

Docker:

```bash
docker build -t vgselect-3a . && docker run --rm -p 8080:8080 \
  -v $PWD:/scan:ro -e VGSELECT_SCAN_ROOTS=/scan \
  -v $PWD/my_catalog.json:/catalog.json:ro -e VGSELECT_CATALOG=/catalog.json vgselect-3a
```

## API at a glance

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/recommend` | Rank topologies, plan, model selection, report |
| POST | `/api/v1/scan`, `/api/v1/scan/upload` | Scan a repository (server path / git URL / zip), infer the profile, recommend |
| POST | `/api/v1/recommend/pdf`, `/api/v1/recommend/skeleton` | Architecture PDF; LangGraph skeleton zip |
| POST | `/api/v1/describe` | Prose to profile with Claude (optional) |
| GET | `/api/v1/catalog`; POST `/api/v1/catalog/validate` | Model ecosystem catalog; validate entries |
| GET | `/api/v1/fields`, `/api/v1/examples`, `/api/v1/topologies`, `/api/v1/citations` | Reference data |
| GET | `/health`, `/docs`, `/redoc`, `/openapi.json` | Health and feature flags; API docs |

Every recommend, scan, PDF and skeleton request accepts a `policy` (providers,
platforms, regions, verified-only, approved-only, preferred provider) and
`catalog_models` (extra or overriding catalog entries).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `VGSELECT_CATALOG` | bundled default | Path to your model ecosystem catalog JSON |
| `VGSELECT_SCAN_ROOTS` | none | Colon-separated directories that may be scanned by server path |
| `VGSELECT_ALLOW_GIT_CLONE` | `0` | Allow scanning by git URL (shallow clone) |
| `VGSELECT_MAX_UPLOAD_MB` | `50` | Zip upload limit |
| `VGSELECT_CORS_ORIGINS` | none | Browser origins allowed to call the API |
| `VGSELECT_HOST` / `VGSELECT_PORT` | `0.0.0.0` / `8080` | Bind address |
| `ANTHROPIC_API_KEY` | unset | Enables `describe` with the `llm` extra |

## Install extras

| Extra | Adds | Needed for |
|---|---|---|
| none | nothing (standard library only) | engine, scanner, catalog, selection, Markdown/JSON/Mermaid/SVG, skeleton zip |
| `pdf` | reportlab | `--format pdf`, `Recommendation.to_pdf()` |
| `service` | FastAPI, Uvicorn, Pydantic, python-multipart, reportlab | `vgselect-service`, the UI and API |
| `llm` | anthropic, pydantic | `vgselect describe` and `/api/v1/describe` |
| `dev` | pytest, httpx plus the service stack | `pytest` |

## Model ecosystem

The bundled catalog ([catalogs/default.json](src/vgselect3a/catalogs/default.json))
has verified entries for the current Anthropic models and placeholder entries,
marked `illustrative`, showing the shape of OpenAI, Google, self-hosted
open-weights and Mistral models. Placeholders are excluded from selection until
you replace their numbers and mark them verified. Each entry describes
governance (provider, platforms, regions, approval, data classes, retention,
deprecation), capability (reasoning tier, tool use, structured and strict
output, context, modalities, effort control), performance, cost, and measured
accuracy per task family from your own evals, which is the strongest signal
the selector has. Point the service at your registry's catalog with
`VGSELECT_CATALOG`, constrain the ecosystem per request with a policy, and the
generated skeleton runs mixed-provider plans through LangChain's
`init_chat_model` without code changes.

## The web UI

A guided flow in Vanguard colours with a progress tracker (Start, Describe,
Results). Step 1 offers five starting points: a bundled scenario, a repository
scan (zip, server path or git URL, plus optional traces), a prose description
filled in by Claude, a blank profile, or "Grade agent" for an agent that
already runs. Step 2 groups the twenty-six fields with completion badges, pill
groups, switches, sliders, unit-labelled numbers and one-click presets, and a
live sentence restating what you are asking for; a Model ecosystem group
constrains providers, platforms and regions. Results open with a sticky
summary strip and jump links, then the verdict card (budget badge, latency bar,
cost, tokens, score, cited reasons), what the scan found and the gap from the
current implementation, the agent report card (grade ring, complexity tiles,
graded dimensions, mismatches, per-agent rows), the options table with per-row
rule expansions, a latency-versus-fit chart, the model per role, the build
plan with a server-rendered diagram, a next-steps checklist and the
assumptions. Every control, header, tile, chip and citation has a tooltip;
Ctrl/⌘+Enter runs the recommendation; inputs are remembered until Reset. The
verdict card downloads the PDF, the LangGraph skeleton, Markdown and JSON. The
user guide is served by the app at `/guide`. No external front-end
dependencies.

## Repository layout

```
src/vgselect3a/
  profile.py        workload profile fields (single source of truth for CLI, API, UI, LLM intake)
  scanner.py        repository scanner -> inferred profile with confidence + file:line evidence
  rules.py          41 cited scoring rules
  recommender.py    viability, latency/cost balancing, Pareto frontier, selection, to_pdf/to_skeleton
  estimator.py      call-tree latency/cost model per topology (tiers from the catalog)
  decomposition.py  subagent plan, guardrails
  catalog.py        model ecosystem catalog (ModelSpec, Catalog); catalogs/default.json
  requirements.py   per-role requirements derived from the plan
  model_selector.py filters, scoring, cross-role constraints, fallbacks -> model per role
  traces.py         run-time trace format, adapters (LangSmith, OTel), behavioural metrics, synthetic traces
  report_card.py    complexity levels, mismatch flags, graded dimensions, per-agent cards
  render.py         Markdown / JSON / Mermaid / SVG and the shared diagram layout
  pdf_report.py     architecture document (PDF, reportlab)
  scaffold/         LangGraph project skeleton generator, one template per topology, provider-aware
  cli.py            vgselect scan | recommend | scaffold | report-card | catalog | wizard | describe | examples | fields
  intake_llm.py     optional Claude-powered prose -> profile
  service/          FastAPI app, Pydantic schemas (generated from the profile), static UI
  examples/         eight canonical profiles
docs/               executive brief, deployment guide, consumer guide, methodology, model catalog, industry guidance
openapi/            exported OpenAPI 3 document (scripts/export_openapi.py)
scripts/            OpenAPI export, Markdown-to-HTML converter, user-guide sync into the package
case_study/         three mock applications with fictional traces and every 3A output (scan, recommendation, report card, PDF, skeleton) and a runner
.claude/skills/     Claude Code skill
.claude/launch.json dev-server config for the Claude Code browser preview
tests/              engine, scanner (fixture repo), catalog and selection, API, PDF and skeleton tests
Dockerfile          production image (non-root, healthcheck); published to ghcr.io by CI
.github/workflows/  CI: tests, OpenAPI and user-guide freshness, clean-install smoke test, image publish, release on tags
```

## Releases

Versions are tagged `vX.Y.Z`. Pushing a tag runs the pipeline: tests, a
clean-install smoke test of the wheel, an image push to
`ghcr.io/rgvvvg5mpz-collab/vgselect3a` (tags: version, major.minor, `main`,
commit SHA) that is started and health-checked before publishing, and a GitHub
release with notes from [CHANGELOG.md](CHANGELOG.md). Latest:
[v0.4.1](https://github.com/rgvvvg5mpz-collab/VGSelect3A/releases/tag/v0.4.1).
Deployment, configuration and operations: [docs/DEPLOYMENT.html](docs/DEPLOYMENT.html).

## Tests

```bash
pip install -e '.[dev]' && pytest
```

78 tests: eight canonical scenarios, monotonicity of the latency/accuracy
balance, viability, the scanner against a fixture repository, catalog
validation, per-role requirements, model selection under policies (providers,
regions, data class, evidence, verifier independence, orchestrator floor),
trace parsing (native, LangSmith, OpenTelemetry), behavioural metrics, report
card grading and mismatch flags, every API endpoint, PDF generation, and
syntax checks of the generated skeleton for all ten topologies and for
mixed-provider plans. To exercise the
skeletons against the real library, unzip one and run its own `pytest` with
`langgraph`, `langchain` and the provider integration packages installed.

Estimates are order-of-magnitude heuristics for ranking, not production
predictions. Calibrate the catalog's serving figures and prices from your own
telemetry, and add measured accuracy per task family.
