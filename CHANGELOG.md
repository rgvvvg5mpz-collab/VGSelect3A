# Changelog

## 0.2.0 - 2026-09-07

- Renamed to VG Select: 3A (Automated Agentic Architecture); package `vgselect3a`, CLI `vgselect`.
- Repository scanner: infers profile fields with confidence and file:line evidence; detects the currently implemented topology; report shows the current-vs-recommended gap.
- FastAPI service with OpenAPI document, zip upload / server path / git URL scanning (deny-by-default), health endpoint with feature flags, Dockerfile.
- Web UI redesigned: Vanguard palette, guided three-step flow, tooltips on every field, header and citation, verdict card, comparison table with rule expansions, latency-versus-fit chart, plan cards, next-steps checklist. No external front-end dependencies; diagrams rendered server-side as SVG.
- Deliverables: architecture document (PDF, reportlab) and downloadable LangGraph project skeleton (zip) with one template per topology, from the CLI (`--format pdf`, `scaffold`), the API (`/api/v1/recommend/pdf`, `/api/v1/recommend/skeleton`) and the UI.
- Claude Code skill; executive brief, deployment guide, consumer guide, methodology, industry guidance.
- New rules from the scaling study and RAG guidance: capability saturation above a ~45% single-agent baseline, tool overlap as the split trigger, error amplification per topology, retrieval-latency constraints.

## 0.1.0 - 2026-09-07

- Initial engine: workload profile, 36 cited rules, viability, call-tree latency/cost estimates, latency/accuracy balancing, decomposition plan, Markdown/JSON/Mermaid output, CLI, eight examples, tests.
