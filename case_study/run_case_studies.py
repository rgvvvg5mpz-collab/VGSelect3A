"""Regenerate every case study: scan the mock app, merge the hand-authored
overrides, recommend, and write all VG Select: 3A outputs into the case folder.

    .venv/bin/python case_study/run_case_studies.py [case_dir ...]
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

from vgselect3a import WorkloadProfile, recommend
from vgselect3a.catalog import Catalog
from vgselect3a.model_selector import SelectionPolicy
from vgselect3a.scanner import merge_profile, scan_markdown, scan_repository
from vgselect3a.traces import load_traces, synthesize_traces, traces_to_jsonl

# Fictional trace settings per case (quality, chaos, workers): plausible behaviour for the narrative.
TRACE_SETTINGS = {
    "01_call_summarization": dict(topology="prompt_chain", n_tasks=60, runs_per_task=2, quality=0.9, chaos=0.05, tools=["post_call_summary"], seed=11),
    "02_robo_advisor": dict(topology="evaluator_optimizer", n_tasks=40, runs_per_task=2, quality=0.62, chaos=0.35, tools=["get_portfolio", "risk_score", "search_policy", "search_methodology", "suitability_check"], seed=22, tokens_scale=3.0),
    "03_account_inquiry": dict(topology="single_agent", n_tasks=80, runs_per_task=2, quality=0.9, chaos=0.08, tools=["get_balances", "get_cost_basis", "get_transactions", "faq_lookup"], seed=33),
}

ROOT = Path(__file__).resolve().parent
CATALOG = Catalog.load(ROOT / "catalog.json")
POLICY = SelectionPolicy(require_verified=True)


def run(case: Path) -> dict:
    import shutil
    if (case / "output").exists():
        shutil.rmtree(case / "output")          # never scan our own previous outputs
    scan = scan_repository(case)                # app/ plus evals/ and tests/ count as evidence
    overrides = json.loads((case / "overrides.json").read_text())
    profile_data = merge_profile(scan, overrides)
    profile = WorkloadProfile.from_dict(profile_data)
    out = case / "output"
    out.mkdir()
    # traces: fictional, generated once per case (kept next to the app so a developer can see the format)
    tpath = case / "traces.jsonl"
    if not tpath.exists():
        cfg = dict(TRACE_SETTINGS.get(case.name, dict(topology="single_agent")))
        topo = cfg.pop("topology")
        tpath.write_text(traces_to_jsonl(synthesize_traces(topo, **cfg)))
    traces = load_traces(tpath)
    rec = recommend(profile, scan=scan, catalog=CATALOG, policy=POLICY, traces=traces)
    rec._catalog = CATALOG
    (out / "scan.md").write_text(scan_markdown(scan))
    (out / "scan.json").write_text(scan.to_json())
    (out / "profile.json").write_text(profile.to_json())
    (out / "recommendation.md").write_text(rec.to_markdown())
    (out / "recommendation.json").write_text(rec.to_json())
    (out / "plan.svg").write_text(rec.to_svg())
    (out / "plan.mmd").write_text(rec.to_mermaid())
    (out / "architecture.pdf").write_bytes(rec.to_pdf())
    (out / "report_card.md").write_text(rec.report_card.to_markdown())
    (out / "report_card.json").write_text(json.dumps(rec.report_card.to_dict(), indent=2))
    zip_bytes = rec.to_skeleton("langgraph")
    (out / "skeleton.zip").write_bytes(zip_bytes)
    skel = out / "skeleton"
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        zf.extractall(skel)
    best = rec.primary
    sel = rec.selection
    cur = next((c for c in rec.candidates if c.topology.id == scan.current_topology), None)
    summary = {
        "case": case.name, "name": profile.name, "current_topology": scan.current_topology,
        "recommended": best.topology.id, "recommended_name": best.topology.name, "score": best.score,
        "latency_s": best.estimate.latency_s, "budget_s": profile.latency_budget_s, "verdict": best.latency_verdict,
        "cost_usd": best.estimate.cost_usd, "tokens_x": best.estimate.token_multiplier,
        "selected_latency_s": rec.selected_estimate.latency_s, "selected_cost_usd": rec.selected_estimate.cost_usd,
        "current_score": cur.score if cur else None, "current_latency_s": cur.estimate.latency_s if cur else None,
        "fastest_viable": rec.fastest_viable.topology.name if rec.fastest_viable else None,
        "most_accurate": rec.most_accurate.topology.name if rec.most_accurate else None,
        "models": [(c.component_id, c.model_id, c.effort, c.fallback_model_id) for c in sel.choices],
        "unfilled": sel.unfilled, "warnings": sel.warnings, "providers": sel.providers_used,
        "top_reasons": [s.rationale for s in sorted(best.signals, key=lambda s: -s.delta) if s.delta > 0][:4],
        "scan_tools": scan.tools, "scan_sources": scan.knowledge_sources, "scan_side_effects": scan.side_effects,
        "scan_frameworks": scan.frameworks, "files": scan.files_scanned,
        "card": {"grade": rec.report_card.overall_grade, "score": rec.report_card.overall_score, "task": rec.report_card.task_level,
                 "design": rec.report_card.design_level, "behaviour": rec.report_card.behaviour_level,
                 "dims": [(d.name, d.grade, d.score) for d in rec.report_card.dimensions],
                 "mismatches": [(m.severity, m.title) for m in rec.report_card.mismatches],
                 "agents": [(a.agent, a.grade, a.findings[0] if a.findings else "") for a in rec.report_card.agents],
                 "runs": rec.report_card.behaviour.runs if rec.report_card.behaviour else 0},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    write_readme(case, summary)
    return summary


def write_readme(case: Path, s: dict) -> None:
    scenario = (case / "scenario.md").read_text().strip()
    models = "\n".join(f"| {cid} | {mid or '**unfilled**'} | {eff} | {fb or '-'} |" for cid, mid, eff, fb in s["models"])
    gap = (f"| Current ({s['current_topology']}) | {s['current_score']:+.1f} | ~{s['current_latency_s']:.0f}s |\n" if s["current_score"] is not None else "")
    lines = [scenario, "", "---", "", "## VG Select: 3A results", "",
             f"**Scan.** {s['files']} files; frameworks: {', '.join(s['scan_frameworks']) or 'none'}; tools found: {', '.join(t for t in s['scan_tools'] if not t.startswith('~')) or 'none'}; "
             f"knowledge sources: {', '.join(s['scan_sources']) or 'none'}; side effects: {', '.join(s['scan_side_effects']) or 'none'}. Current topology as implemented: **{s['current_topology']}**.", "",
             f"**Recommendation.** **{s['recommended_name']}** (score {s['score']:+.1f}); estimated ~{s['latency_s']:.0f}s against a {s['budget_s']:.0f}s budget ({s['verdict']}), "
             f"${s['cost_usd']:.3f} per request, {s['tokens_x']:.0f}x the tokens of one call. On the chosen models: ~{s['selected_latency_s']:.0f}s, ${s['selected_cost_usd']:.3f}. "
             f"Fastest viable within budget: {s['fastest_viable'] or 'none'}; strongest structural fit: {s['most_accurate']}.", "",
             "| Topology | Score | Est. latency |", "|---|---|---|", gap + f"| Recommended ({s['recommended']}) | {s['score']:+.1f} | ~{s['latency_s']:.0f}s |", "",
             "**Why.**", *[f"- {r}" for r in s["top_reasons"]], "",
             f"**Model per role** (catalog `case-study-ecosystem`, providers used: {', '.join(s['providers']) or 'none'}).", "",
             "| Role | Model | Effort | Fallback |", "|---|---|---|---|", models, ""]
    if s["unfilled"]:
        lines += [f"Unfilled roles: {', '.join(s['unfilled'])}.", ""]
    if s["warnings"]:
        lines += ["Warnings:", *[f"- {w}" for w in s["warnings"]], ""]
    c = s["card"]
    lines += ["## Agent report card", "",
              f"Overall **{c['grade']}** ({c['score']}/100) from {c['runs']} fictional trace runs (`traces.jsonl`). Complexity: task {c['task']}, design {c['design']}, behaviour {c['behaviour']}.", "",
              "| Dimension | Grade | Score |", "|---|---|---|", *[f"| {n} | **{g}** | {sc if sc is not None else 'n/a'} |" for n, g, sc in c["dims"]], ""]
    if c["mismatches"]:
        lines += ["Mismatches: " + "; ".join(f"{t} ({sev})" for sev, t in c["mismatches"]) + ".", ""]
    if c["agents"]:
        lines += ["| Agent | Grade | Note |", "|---|---|---|", *[f"| {a} | **{g}** | {f} |" for a, g, f in c["agents"]], ""]
    lines += ["Full card: `output/report_card.md`.", ""]
    lines += ["## Files", "",
              "| File | What it is |", "|---|---|",
              "| `scenario.md`, `overrides.json` | The narrative and the hand-authored profile fields the code cannot reveal |",
              "| `app/` | The mock application that was scanned |",
              "| `output/scan.md`, `output/scan.json` | What the scanner found: inferred fields with confidence, evidence with file:line |",
              "| `output/profile.json` | The merged profile the recommendation ran on |",
              "| `output/recommendation.md`, `output/recommendation.json` | The full report and structured result (ranked options, plan, model selection, next steps) |",
              "| `output/architecture.pdf` | The architecture document for the design review (includes the report card) |",
              "| `traces.jsonl`, `output/report_card.md`, `output/report_card.json` | Fictional run-time traces in the vgselect-trace format, and the agent report card graded from them |",
              "| `output/plan.svg`, `output/plan.mmd` | The plan diagram |",
              "| `output/skeleton.zip`, `output/skeleton/` | The generated LangGraph project for the recommended topology |",
              "| `output/summary.json` | The key numbers used in this README |", ""]
    (case / "README.md").write_text("\n".join(lines))


INDEX_INTRO = """# VG Select: 3A case studies

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

Each case also carries fictional run-time traces (`traces.jsonl`, generated by
`vgselect3a.traces.synthesize_traces`) so the **agent report card** can grade
behaviour as well as design. Regenerate everything with:

```bash
.venv/bin/python case_study/run_case_studies.py
```
"""


def write_index(rows: list[dict]) -> None:
    lines = [INDEX_INTRO, "## Results at a glance", "",
             "| Case | Current topology | Recommended | Est. latency / budget | Cost / request | Models per role | Report card |", "|---|---|---|---|---|---|---|"]
    for s in rows:
        models = ", ".join(sorted({m[1] for m in s["models"] if m[1]})) or "unfilled"
        lines.append(f"| [{s['case']}]({s['case']}/README.md) | {s['current_topology']} | **{s['recommended_name']}** | ~{s['latency_s']:.0f}s / {s['budget_s']:.0f}s ({s['verdict']}) | ${s['cost_usd']:.3f} | {models} | **{s['card']['grade']}** ({s['card']['score']}) |")
    lines += ["", "Each case README explains the scenario, the scan findings, why the topology was chosen, the model per role, and where every file is.", ""]
    (ROOT / "README.md").write_text("\n".join(lines))


if __name__ == "__main__":
    cases = [Path(a) for a in sys.argv[1:]] or sorted(p for p in ROOT.iterdir() if p.is_dir() and p.name[:2].isdigit())
    rows = []
    for c in cases:
        s = run(c)
        rows.append(s)
        print(f"{s['case']:28s} current={s['current_topology']:20s} -> {s['recommended']:22s} {s['latency_s']:6.0f}s/{s['budget_s']:.0f}s {s['verdict']:8s} ${s['cost_usd']:.3f} models={[m[1] for m in s['models']][:3]} unfilled={s['unfilled']}")
    if not sys.argv[1:]:
        write_index(rows)
