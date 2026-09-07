# VG Select: 3A — Model Catalog and Per-Role Model Selection

VG Select: 3A staffs every role in the recommended architecture (orchestrator,
workers, router, evaluator, ...) with a model from your **ecosystem catalog**.
The catalog is a JSON document maintained by the platform team; the selector
matches each role's derived requirements against it under a **selection
policy**. This document describes the schema, the selection procedure, and how
to maintain the catalog.

## 1. Catalog schema

A catalog is `{"name": "...", "models": [ModelSpec, ...]}` (or a bare list of
ModelSpec objects). The bundled default is
`src/vgselect3a/catalogs/default.json`. Point the service at your own with
`VGSELECT_CATALOG=/path/catalog.json`, the CLI with `--catalog`, or send extra
entries per request via `catalog_models`.

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Model id as used by the provider SDK / gateway. Unique in the catalog. |
| `display_name`, `provider`, `family` | string | Provider (`anthropic`, `openai`, `google`, `meta`, `mistral`, `amazon`, `microsoft`, `cohere`, `deepseek`, `xai`, `self_hosted`, `other`); family groups generations (used for consistency and verifier independence). |
| `platforms` | list | Where it is reachable: `anthropic_api`, `bedrock`, `vertex`, `foundry`, `openai_api`, `azure_openai`, `google_api`, `self_hosted`, `other`. |
| `regions` | list | Serving regions (`global`, `us`, `eu`, `on_prem`, ...). |
| `approved` | bool | Platform-team approval. Unapproved entries are rejected (and shown as rejected) unless the policy sets `require_approved=false`. |
| `data_classes` | list | Data classes the model is cleared for: `public`, `internal`, `confidential`, `restricted`. A role is only staffed by models cleared for the profile's `data_sensitivity`. |
| `retention` | `standard` / `zero` | Data retention terms. |
| `deprecation_date` | ISO date | Deprecated models are rejected; models within `deprecation_horizon_days` are penalised. |
| `reasoning_tier` | 1..5 | Capability level: 1 trivial, 3 mid, 5 frontier. Compared with each role's required level. |
| `tool_use` | 0..3 | 0 none, 1 basic, 2 reliable, 3 reliable with parallel tool calls. |
| `structured_output`, `strict_schema` | bool | JSON output; guaranteed schema conformance (required for high-stakes structured roles). |
| `context_window`, `max_output` | int | Tokens. Roles need context for their reading share plus prompt and tool schemas. |
| `modalities` | list | `text`, `image`, `pdf`, `audio`, `video`. |
| `thinking`, `effort_control` | bool | Reasoning mode available; effort/reasoning level controllable per request. |
| `ttft_s`, `tokens_per_s` | float | Serving figures used for the role's latency estimate. |
| `rpm`, `tpm`, `max_concurrency` | int | Rate limits; low concurrency rejects parallel-worker roles. |
| `batch`, `batch_discount` | bool, float | Batch API availability and discount. |
| `input_price`, `output_price`, `cache_read_price` | float | USD per million tokens. |
| `evidence` | map | Measured accuracy (0..1) per task family on **your** evals: `general`, `classification`, `extraction`, `research`, `writing`, `coding`, `evaluation`, `conversation`, `planning`. |
| `langchain_provider` | string | Value passed to `langchain.chat_models.init_chat_model(model_provider=...)` in the generated skeleton (defaulted from `provider`). |
| `illustrative` | bool | Placeholder numbers. Excluded by default (`require_verified=true`). |
| `verified_on`, `notes` | string | Provenance. |

The bundled Anthropic entries carry list prices and serving figures from the
bundled reference. The OpenAI, Google, self-hosted and Mistral entries are
**placeholders**: they show the shape of an ecosystem catalog and are marked
`illustrative: true`. Replace their ids, capability, performance, prices and
evidence from your model registry and vendor price lists, set
`illustrative: false` and `verified_on`, and set `approved`, `data_classes` and
`regions` to your governance decisions.

Validate a catalog before deploying it:

```bash
vgselect catalog --catalog my_catalog.json          # lists and validates
curl -s $VGSELECT_URL/api/v1/catalog/validate -H 'content-type: application/json' -d @models.json
```

## 2. Role requirements (derived, not asked)

For every component of the plan, `requirements.py` derives:

| Requirement | How it is derived |
|---|---|
| `role_type` | orchestrator, synthesizer, responder, single agent, coder, worker, reader, router, evaluator, handler, specialist, stage |
| `reasoning_level` (1..5) | From task complexity and role: lead = complexity + 2 (min 3); workers = complexity-mapped, capped at 4 unless accuracy priority is 5; routers 1-2; evaluators 5 when accuracy priority ≥ 4 |
| `context_tokens` | Prompt + tool schemas + the role's share of the reading load (workers split it) |
| `output_tokens` | From output type and complexity; short for routers and tool rounds |
| `needs_tools`, `tool_count`, `needs_parallel_tools`, `tool_rounds` | From the profile's tool surface and the role's share of tool calls |
| `needs_structured_output`, `needs_strict_schema` | Routers and evaluators always; extraction roles; strict when accuracy priority ≥ 4 |
| `latency_share_s` | The role's slice of the end-to-end budget by topology (e.g. router ≤ 12% capped at 1.5 s; orchestrator 30%; workers 55%; evaluator 15%) |
| `stakes` | Accuracy priority, raised for roles that act irreversibly |
| `calls_per_day` | Requests per day × tool rounds × iterations |
| `data_class` | The profile's `data_sensitivity` |
| `task_family` | For evidence lookup: classification, extraction, research, writing, coding, evaluation, conversation, planning, general |
| `effort_hint` | low for routers/readers, medium for careful workers, high/xhigh/max for leads and evaluators by stakes |
| `independent_of` | Verifier vs lead, evaluator vs generator, judge vs voters |
| `cache_group` | Roles sharing a loop or parallel group share one model (prompt cache, one behaviour) |

## 3. Selection procedure

1. **Hard filters** (a rejection reason is recorded for every model): not approved; provider/platform/region outside the policy; illustrative entry under `require_verified`; not cleared for the data class; context window or max output too small; no tool use / not reliable enough for large tool sets; no structured output or strict schema where required; missing modality; deprecated; capability tier below the requirement unless measured evidence for the task family is ≥ 80%; concurrency too low for parallel workers.
2. **Score** each surviving model: quality (capability margin weighted by stakes, measured evidence, parallel tool use, strict schema, effort control; penalties for over-provisioning under cost pressure, illustrative entries, imminent deprecation) plus a latency adjustment against the role's share (tolerance grows with accuracy priority) plus a cost adjustment relative to the cheapest passing model, weighted by the role's daily volume and your cost sensitivity. Family consistency with the orchestrator and a preferred provider earn small bonuses.
3. **Cross-role constraints**: the orchestrator is selected first with a floor equal to the strongest requirement among the roles it briefs, and re-selected if a staffed model ends up stronger than it; roles in one cache group share a model; verifiers and judges switch to a different family when an alternative within one score point exists, otherwise a warning suggests prompt variation and code checks.
4. **Fallback**: the next-best passing model, preferably on another provider, for outages and refusals.
5. **Feedback**: roles no model can staff are reported as unfilled with the first rejection reasons; roles whose best model still exceeds 1.5× their latency share get a warning to shrink the role or revisit the topology or budget.

The topology ranking itself uses **reference models per capability level**
taken from the catalog under the same policy (cheapest eligible tier-5, tier-4
and tier-3 models), so every option is estimated on models you could deploy.
After selection the primary topology is re-estimated on the chosen models
(`selected_estimate`).

## 4. Policy

| Field | Default | Meaning |
|---|---|---|
| `allowed_providers`, `blocked_providers` | any / none | Provider allow/deny lists |
| `allowed_platforms` | any | The model must be reachable on one of these |
| `regions` | any | The model must be served in one of these |
| `require_verified` | true | Exclude illustrative entries |
| `require_approved` | true | Exclude unapproved entries |
| `prefer_provider` | none | Small bonus for consistency |
| `family_consistency_bonus` | 0.25 | Bonus for matching the orchestrator's family |
| `deprecation_horizon_days` | 180 | Penalty window before a deprecation date |

CLI: `--catalog`, `--providers`, `--platforms`, `--regions`,
`--allow-unverified`, `--prefer-provider`. API: `policy` object and
`catalog_models` on recommend, scan, PDF and skeleton requests. UI: the "Model
ecosystem" group under the profile.

## 5. What the outputs show

- **Report and PDF**: a "Model selection per role" table (needs, chosen model,
  effort, fallback, estimated latency and cost per call, alternatives with
  scores), the rationale per role, warnings, and why unfilled roles could not
  be staffed.
- **Plan and diagram**: each component shows its chosen model and provider.
- **Skeleton**: `app/config.py` carries model, provider, fallback and effort
  per role; `app/agents.py` builds models with `init_chat_model`, so Anthropic,
  OpenAI, Azure OpenAI, Google (AI Studio or Vertex), Bedrock, Mistral, Cohere,
  DeepSeek, xAI, Groq, Ollama or a self-hosted OpenAI-compatible endpoint all
  work; `requirements.txt` and `.env.example` list only the integration
  packages and credentials the chosen providers need.

## 6. Maintaining the catalog

- Keep one catalog per environment (dev, prod, region) in version control;
  the platform team owns `approved`, `data_classes`, `regions`.
- Refresh prices and serving figures on a schedule from vendor price lists and
  your gateway's telemetry; set `verified_on`.
- Add `evidence` from your eval suites per task family; it is the strongest
  signal the selector has and can lift a cheaper, smaller model into a role.
- Add `deprecation_date` as soon as a vendor announces it; the selector warns
  six months ahead.
- Run `pytest` after editing the bundled default; the tests assert the shape
  of the verified entries.
