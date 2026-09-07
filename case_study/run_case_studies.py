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
    rec = recommend(profile, scan=scan, catalog=CATALOG, policy=POLICY)
    rec._catalog = CATALOG
    out = case / "output"
    out.mkdir()
    (out / "scan.md").write_text(scan_markdown(scan))
    (out / "scan.json").write_text(scan.to_json())
    (out / "profile.json").write_text(profile.to_json())
    (out / "recommendation.md").write_text(rec.to_markdown())
    (out / "recommendation.json").write_text(rec.to_json())
    (out / "plan.svg").write_text(rec.to_svg())
    (out / "plan.mmd").write_text(rec.to_mermaid())
    (out / "architecture.pdf").write_bytes(rec.to_pdf())
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
    lines += ["## Files", "",
              "| File | What it is |", "|---|---|",
              "| `scenario.md`, `overrides.json` | The narrative and the hand-authored profile fields the code cannot reveal |",
              "| `app/` | The mock application that was scanned |",
              "| `output/scan.md`, `output/scan.json` | What the scanner found: inferred fields with confidence, evidence with file:line |",
              "| `output/profile.json` | The merged profile the recommendation ran on |",
              "| `output/recommendation.md`, `output/recommendation.json` | The full report and structured result (ranked options, plan, model selection, next steps) |",
              "| `output/architecture.pdf` | The architecture document for the design review |",
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

Regenerate everything with:

```bash
.venv/bin/python case_study/run_case_studies.py
```
"""


def write_index(rows: list[dict]) -> None:
    lines = [INDEX_INTRO, "## Results at a glance", "",
             "| Case | Current topology | Recommended | Est. latency / budget | Cost / request | Models per role |", "|---|---|---|---|---|---|"]
    for s in rows:
        models = ", ".join(sorted({m[1] for m in s["models"] if m[1]})) or "unfilled"
        lines.append(f"| [{s['case']}]({s['case']}/README.md) | {s['current_topology']} | **{s['recommended_name']}** | ~{s['latency_s']:.0f}s / {s['budget_s']:.0f}s ({s['verdict']}) | ${s['cost_usd']:.3f} | {models} |")
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
