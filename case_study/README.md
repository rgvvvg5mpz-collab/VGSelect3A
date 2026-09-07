# VG Select: 3A case studies

Three fictional test applications run end to end through VG Select: 3A. Each
folder holds a mock application that was scanned, a scenario, the hand-authored
profile fields the code cannot reveal, and every output the tool produces: the
scan, the merged profile, the recommendation in Markdown and JSON, the plan
diagram, the architecture PDF, and the generated LangGraph skeleton.

The model ecosystem used is `catalog.json` in this folder: the current
Anthropic models plus **fictional** on-premises and third-party entries invented
for the case studies (their numbers are fixtures, not vendor facts). It exists
to show restricted-data staffing and rejection reasons; do not reuse it in
production.

Regenerate everything with:

```bash
.venv/bin/python case_study/run_case_studies.py
```

## Results at a glance

| Case | Current topology | Recommended | Est. latency / budget | Cost / request | Models per role |
|---|---|---|---|---|---|
| [01_call_summarization](01_call_summarization/README.md) | single_call | **Prompt chain (sequential workflow)** | ~26s / 60s (fits) | $0.045 | claude-sonnet-5 |
| [02_robo_advisor](02_robo_advisor/README.md) | evaluator_optimizer | **Router / classifier dispatch** | ~27s / 15s (exceeds) | $0.414 | acme-onprem-70b, claude-haiku-4-5 |
| [03_account_inquiry](03_account_inquiry/README.md) | single_agent | **Single agent with tools** | ~7s / 5s (exceeds) | $0.003 | acme-onprem-70b |

Each case README explains the scenario, the scan findings, why the topology was chosen, the model per role, and where every file is.
