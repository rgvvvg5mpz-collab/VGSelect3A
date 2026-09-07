"""Markdown, JSON and Mermaid renderers for a Recommendation."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from .decomposition import Plan
from .scanner import scan_markdown
from .topologies import MODEL_TIERS

if TYPE_CHECKING:
    from .recommender import Recommendation

CITATIONS = {
    "ANTHROPIC_BEA": "Anthropic, Building effective agents",
    "ANTHROPIC_MAR": "Anthropic, How we built our multi-agent research system",
    "ANTHROPIC_CTX": "Anthropic, Effective context engineering for AI agents",
    "ANTHROPIC_MA": "Anthropic, Managed Agents multiagent guidance",
    "OPENAI_PG": "OpenAI, A practical guide to building agents",
    "COGNITION": "Cognition, Don't build multi-agents",
    "MAST": "Cemri et al., Why do multi-agent LLM systems fail? (MAST)",
    "LANGGRAPH": "LangGraph, Multi-agent systems",
    "GOOGLE_ADK": "Google ADK, Multi-agent systems",
    "MS_AF": "Microsoft Azure / Agent Framework, AI agent design patterns",
    "SCALING": "Google/MIT, Towards a Science of Scaling Agent Systems",
    "RAG": "Agentic vs classic RAG guidance (see docs/industry_guidance.html)",
}


def to_dict(rec: "Recommendation") -> dict:
    return {
        "profile": rec.profile.to_dict(),
        "headline": rec.headline,
        "primary": rec.primary.topology.id,
        "candidates": [
            {
                "topology": c.topology.id,
                "name": c.topology.name,
                "family": c.topology.family,
                "score": c.score,
                "fit": c.fit,
                "quality_proxy": c.quality_proxy,
                "latency_adj": c.latency_adj,
                "cost_adj": c.cost_adj,
                "latency_verdict": c.latency_verdict,
                "viable": c.viable,
                "infeasible_reason": c.infeasible_reason,
                "estimate": {
                    "latency_s": c.estimate.latency_s,
                    "cost_usd": c.estimate.cost_usd,
                    "llm_calls": c.estimate.llm_calls,
                    "total_tokens": c.estimate.total_tokens,
                    "token_multiplier": c.estimate.token_multiplier,
                    "assumptions": c.estimate.assumptions,
                },
                "signals": [asdict(s) for s in c.signals],
            }
            for c in rec.candidates
        ],
        "frontier": [c.topology.id for c in rec.frontier],
        "fastest_viable": rec.fastest_viable.topology.id if rec.fastest_viable else None,
        "most_accurate": rec.most_accurate.topology.id if rec.most_accurate else None,
        "plan": {
            "topology": rec.plan.topology_id,
            "components": [{**asdict(c), "model_id": c.model_id} for c in rec.plan.components],
            "edges": [asdict(e) for e in rec.plan.edges],
            "augmentations": [asdict(a) for a in rec.plan.augmentations],
            "briefing_rules": rec.plan.briefing_rules,
        },
        "mermaid": to_mermaid(rec.plan),
        "svg": to_svg(rec.plan),
        "scan": rec.scan.to_dict() if rec.scan else None,
        "selection": rec.selection.to_dict() if rec.selection else None,
        "selected_estimate": {
            "latency_s": rec.selected_estimate.latency_s, "cost_usd": rec.selected_estimate.cost_usd,
            "token_multiplier": rec.selected_estimate.token_multiplier, "tiers_used": rec.selected_estimate.tiers_used,
        } if rec.selected_estimate else None,
        "tiers": {k: v.model_id for k, v in rec.tiers.items()},
    }


def to_json(rec: "Recommendation", indent: int = 2) -> str:
    return json.dumps(to_dict(rec), indent=indent)


def to_mermaid(plan: Plan) -> str:
    lines = ["flowchart TD"]
    groups: dict[str, list[str]] = {}
    for c in plan.components:
        label = f"{c.name}<br/><i>{c.model_id if c.tier != 'code' else 'code'}</i>"
        shape = f'{c.id}[["{label}"]]' if c.tier == "code" else f'{c.id}["{label}"]'
        if c.parallel_group:
            groups.setdefault(c.parallel_group, []).append(shape)
        else:
            lines.append(f"    {shape}")
    for g, shapes in groups.items():
        lines.append(f"    subgraph {g} [{g} - parallel]")
        lines.append("        direction LR")
        lines += [f"        {s}" for s in shapes]
        lines.append("    end")
    for e in plan.edges:
        lbl = f"|{e.label}|" if e.label else ""
        lines.append(f"    {e.src} -->{lbl} {e.dst}")
    return "\n".join(lines)


def selection_markdown(rec: "Recommendation") -> str:
    sel = rec.selection
    out = ["## Model selection per role\n"]
    pol = sel.policy
    constraints = []
    if pol.allowed_providers:
        constraints.append("providers " + ", ".join(pol.allowed_providers))
    if pol.allowed_platforms:
        constraints.append("platforms " + ", ".join(pol.allowed_platforms))
    if pol.regions:
        constraints.append("regions " + ", ".join(pol.regions))
    constraints.append("verified entries only" if pol.require_verified else "illustrative entries allowed")
    out.append(f"Catalog `{sel.catalog_name}`; data class **{rec.profile.data_sensitivity}**; policy: {'; '.join(constraints)}. "
               f"Providers used: {', '.join(sel.providers_used) or 'none'}. "
               + (f"Estimated per request on the chosen models: ~{rec.selected_estimate.latency_s:.0f}s, ${rec.selected_estimate.cost_usd:.3f}." if rec.selected_estimate else "") + "\n")
    out.append("| Role | Needs | Chosen model | Effort | Fallback | Est. per call | Alternatives |")
    out.append("|---|---|---|---|---|---|---|")
    for c in sel.choices:
        r = c.requirements
        needs = f"tier ≥{r.reasoning_level}; {r.latency_share_s:.0f}s share; {r.context_tokens:,} ctx" + ("; tools" if r.needs_tools else "") + ("; structured" if r.needs_structured_output else "")
        chosen = f"**{c.model_id}**" if c.model_id else "**unfilled**"
        est = f"~{c.est_latency_s:.1f}s, ${c.est_cost_per_call:.4f}" if c.model_id else "-"
        alts = ", ".join(f"{a.model_id} ({a.score:+.1f})" for a in c.alternatives[:3]) or "-"
        out.append(f"| {c.component_id} ({r.role_type}) | {needs} | {chosen} | {c.effort} | {c.fallback_model_id or '-'} | {est} | {alts} |")
    out.append("")
    for c in sel.choices:
        if c.rationale:
            out.append(f"- **{c.component_id}**: " + " ".join(c.rationale))
    if sel.warnings:
        out.append("\nWarnings:")
        for w in sel.warnings:
            out.append(f"- {w}")
    unfilled = [c for c in sel.choices if not c.model_id]
    if unfilled:
        out.append("\nWhy roles are unfilled (first rejections):")
        for c in unfilled[:3]:
            out.append(f"- {c.component_id}: " + "; ".join(f"{j.model_id}: {j.reason}" for j in c.rejected[:4]))
    out.append("")
    return "\n".join(out)


def to_markdown(rec: "Recommendation") -> str:
    p = rec.profile
    best = rec.primary
    out: list[str] = []
    out.append(f"# Architecture recommendation: {p.name}\n")
    if p.description:
        out.append(f"> {p.description}\n")
    out.append(rec.headline + "\n")

    if rec.scan is not None:
        out.append(scan_markdown(rec.scan))
        cur = rec.scan.current_topology
        if cur not in ("none", best.topology.id):
            curc = next((c for c in rec.candidates if c.topology.id == cur), None)
            if curc:
                out.append("### Gap: current vs. recommended\n")
                out.append(f"| | Current: {curc.topology.name} | Recommended: {best.topology.name} |\n|---|---|---|")
                out.append(f"| Score | {curc.score:+.1f} | {best.score:+.1f} |")
                out.append(f"| Est. latency | ~{curc.estimate.latency_s:.0f}s | ~{best.estimate.latency_s:.0f}s |")
                out.append(f"| Est. cost / request | ${curc.estimate.cost_usd:.3f} | ${best.estimate.cost_usd:.3f} |")
                out.append(f"| Tokens vs one call | {curc.estimate.token_multiplier:.0f}x | {best.estimate.token_multiplier:.0f}x |")
                worst = sorted(curc.signals, key=lambda s: s.delta)[:3]
                if worst:
                    out.append("\nWhy the current topology scores lower:")
                    for s in worst:
                        if s.delta < 0:
                            out.append(f"- ({s.delta:.1f}) {s.rationale} _[{CITATIONS.get(s.citation, s.citation)}]_")
                out.append("")

    out.append("## Why this topology\n")
    positives = [s for s in sorted(best.signals, key=lambda s: -s.delta) if s.delta > 0]
    for s in positives:
        out.append(f"- (+{s.delta:.1f}) {s.rationale} _[{CITATIONS.get(s.citation, s.citation)}]_")
    if not positives:
        out.append("- No rule specifically favours this topology; it ranks first because it is viable and has the best combined latency and cost fit. Treat the alternatives below as close calls.")
    negatives = [s for s in best.signals if s.delta < 0]
    if negatives:
        out.append("\nCounter-signals to keep in mind:")
        for s in sorted(negatives, key=lambda s: s.delta):
            out.append(f"- ({s.delta:.1f}) {s.rationale} _[{CITATIONS.get(s.citation, s.citation)}]_")
    out.append("")

    out.append("## Ranked candidates\n")
    out.append("| # | Topology | Score | Fit | Latency (p50 est.) | Budget fit | Cost / request | Tokens vs 1 call | LLM calls |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for i, c in enumerate(rec.candidates, 1):
        e = c.estimate
        name = c.topology.name if c.viable else f"~~{c.topology.name}~~ (not viable: {c.infeasible_reason})"
        out.append(f"| {i} | {name} | {c.score:+.1f} | {c.fit:+.1f} | ~{e.latency_s:.0f}s | {c.latency_verdict} | ${e.cost_usd:.3f} | {e.token_multiplier:.0f}x | {e.llm_calls} |")
    out.append("")
    out.append(f"Latency/accuracy frontier (no candidate is both faster and a better structural fit): "
               + ", ".join(f"{c.topology.name} (~{c.estimate.latency_s:.0f}s, fit {c.quality_proxy:+.1f})" for c in rec.frontier) + ".\n")

    out.append("## Decomposition plan\n")
    out.append(f"Topology: **{best.topology.name}** - {best.topology.summary}\n")
    out.append("| Component | Role | Model | Effort | Tools | Parallel group |")
    out.append("|---|---|---|---|---|---|")
    for c in rec.plan.components:
        out.append(f"| {c.name} | {c.role} | {c.model_id} | {c.effort} | {c.tools or '-'} | {c.parallel_group or '-'} |")
    out.append("")
    if rec.plan.briefing_rules:
        out.append("Briefing / coordination rules:")
        for b in rec.plan.briefing_rules:
            out.append(f"- {b}")
        out.append("")
    out.append("```mermaid")
    out.append(to_mermaid(rec.plan))
    out.append("```\n")

    if rec.selection is not None:
        out.append(selection_markdown(rec))

    out.append("## Cross-cutting recommendations\n")
    for a in rec.plan.augmentations:
        out.append(f"- **{a.title}.** {a.why} _[{CITATIONS.get(a.citation, a.citation)}]_")
    out.append("")

    out.append("## Estimate assumptions\n")
    for n in best.estimate.assumptions:
        out.append(f"- {n}")
    out.append("- Serving assumptions (reference model per capability level from the catalog): " + "; ".join(f"{t.model_id} ~{t.ttft_s}s TTFT, ~{t.tokens_per_s:.0f} tok/s" for t in rec.tiers.values()) + f"; tool call ~{p.tool_latency_s}s.")
    out.append(f"- Reading load per task {p.context_tokens_per_task:,} tokens (context pressure: {p.context_pressure}); output type {p.output_type}.")
    out.append("- Latency is the critical path (parallel branches count once); cost sums every call at list prices without caching. Treat both as order-of-magnitude.\n")

    out.append("## Alternatives\n")
    for c in [c for c in rec.candidates[1:] if c.viable][:3]:
        top = [s for s in sorted(c.signals, key=lambda s: -s.delta) if s.delta > 0][:2]
        why = "; ".join(s.rationale.rstrip(".") for s in top) or c.topology.when_to_use
        out.append(f"- **{c.topology.name}** (score {c.score:+.1f}, ~{c.estimate.latency_s:.0f}s, {c.estimate.token_multiplier:.0f}x tokens): {why}")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- server-side SVG (no external dependency)

_TIER_FILL = {"opus": "#0f1a33", "sonnet": "#1f5eff", "haiku": "#6f9bff", "code": "#e9edf3"}
_TIER_INK = {"opus": "#ffffff", "sonnet": "#ffffff", "haiku": "#0f1a33", "code": "#1c2128"}


def _xml(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def layout_plan(plan: Plan, max_per_row: int = 5) -> dict:
    """Layered layout shared by the SVG and PDF renderers.

    Returns {"width", "height", "W", "H", "pos": {id: (x, y)}, "rank": {id: int},
             "frames": [(x0, y0, x1, y1, group)], "edges": [(src, dst, label, back)]}.
    """
    comps = plan.components
    ids = [c.id for c in comps]
    by_id = {c.id: c for c in comps}
    if not comps:
        return {"width": 10, "height": 10, "W": 0, "H": 0, "pos": {}, "rank": {}, "frames": [], "edges": []}
    incoming = {i: set() for i in ids}
    for e in plan.edges:
        if e.src in by_id and e.dst in by_id and e.src != e.dst:
            incoming[e.dst].add(e.src)
    rank: dict[str, int] = {}
    roots = [i for i in ids if not incoming[i]] or [ids[0]]
    for r in roots:
        rank[r] = 0
    changed = True
    while changed:
        changed = False
        for e in plan.edges:
            if e.src in rank and e.dst in by_id and e.dst not in rank:
                rank[e.dst] = rank[e.src] + 1
                changed = True
    for i in ids:
        rank.setdefault(i, 0)
    groups: dict[str, list[str]] = {}
    for c in comps:
        if c.parallel_group:
            groups.setdefault(c.parallel_group, []).append(c.id)
    for members in groups.values():
        top = max(rank[m] for m in members)
        for m in members:
            rank[m] = top

    W, H, GX, GY, PAD = 176, 50, 22, 44, 30
    layers: dict[int, list[str]] = {}
    for i in ids:
        layers.setdefault(rank[i], []).append(i)
    pos: dict[str, tuple[float, float]] = {}
    y = PAD + 24
    width = 0
    frames: list[tuple[float, float, float, float, str]] = []
    for r in sorted(layers):
        members = layers[r]
        blocks: list[tuple[str | None, list[str]]] = []
        for g, gm in groups.items():
            here = [m for m in members if m in gm]
            if here:
                blocks.append((g, here))
        loose = [m for m in members if not by_id[m].parallel_group]
        if loose:
            blocks.append((None, loose))
        for g, block in blocks:
            cols = min(len(block), max_per_row)
            rows = -(-len(block) // cols)
            width = max(width, cols * (W + GX) - GX + 2 * PAD)
            for k, i in enumerate(block):
                pos[i] = (PAD + (k % cols) * (W + GX), y + (k // cols) * (H + 18))
            if g is not None:
                xs = [pos[m][0] for m in block]
                ys = [pos[m][1] for m in block]
                frames.append((min(xs) - 8, min(ys) - 20, max(xs) + W + 8, max(ys) + H + 8, g))
                y += 12
            y += rows * (H + 18) + (GY if g is None else 10)
        y += 10
    edges = [(e.src, e.dst, e.label, rank[e.dst] <= rank[e.src]) for e in plan.edges if e.src in pos and e.dst in pos and e.src != e.dst]
    return {"width": width, "height": y, "W": W, "H": H, "pos": pos, "rank": rank, "frames": frames, "edges": edges}


def to_svg(plan: Plan, max_per_row: int = 5) -> str:
    """Layered flowchart of the plan as standalone SVG (no external dependencies)."""
    L = layout_plan(plan, max_per_row)
    by_id = {c.id: c for c in plan.components}
    width, height, W, H, pos = L["width"], L["height"], L["W"], L["H"], L["pos"]
    if not pos:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
           f'font-family="-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif" font-size="12">',
           '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
           '<path d="M0 0L10 5L0 10z" fill="#5b6470"/></marker></defs>',
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>']
    for x0, y0, x1, y1, g in L["frames"]:
        out.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="10" fill="#f3f6fb" stroke="#9db3e8" stroke-dasharray="5 4"/>')
        out.append(f'<text x="{x0 + 8}" y="{y0 + 13}" fill="#3c5aa6" font-size="11" font-weight="600">{_xml(g)} - parallel</text>')
    for src, dst, label, back in L["edges"]:
        (sx, sy), (dx, dy) = pos[src], pos[dst]
        if back:
            x1, y1 = sx + W * 0.7, sy + H if dy > sy else sy
            x2, y2 = dx + W * 0.7, dy if dy > sy else dy + H
            style = 'stroke="#9aa5b5" stroke-dasharray="4 3"'
        else:
            x1, y1, x2, y2 = sx + W * 0.4, sy + H, dx + W * 0.4, dy
            style = 'stroke="#5b6470"'
        out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" {style} stroke-width="1.4" marker-end="url(#arr)"/>')
        if label:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            out.append(f'<text x="{mx:.0f}" y="{my - 3:.0f}" fill="#5b6470" font-size="10" text-anchor="middle">{_xml(label)}</text>')
    for c in plan.components:
        x, yy = pos[c.id]
        fill, ink = _TIER_FILL.get(c.tier, "#cccccc"), _TIER_INK.get(c.tier, "#000")
        name = c.name if len(c.name) <= 26 else c.name[:25] + "…"
        out.append(f'<rect x="{x}" y="{yy}" width="{W}" height="{H}" rx="8" fill="{fill}" stroke="#0f1a33" stroke-opacity="0.15"/>')
        out.append(f'<text x="{x + W / 2}" y="{yy + 21}" fill="{ink}" text-anchor="middle" font-weight="600">{_xml(name)}</text>')
        out.append(f'<text x="{x + W / 2}" y="{yy + 38}" fill="{ink}" fill-opacity="0.85" text-anchor="middle" font-size="10">{_xml(c.model_id if c.tier != "code" else "code")} · effort {_xml(c.effort)}</text>')
    lx = 30
    for t in ("opus", "sonnet", "haiku", "code"):
        out.append(f'<rect x="{lx}" y="10" width="12" height="12" rx="3" fill="{_TIER_FILL[t]}" stroke="#0f1a33" stroke-opacity="0.2"/>')
        out.append(f'<text x="{lx + 16}" y="20" fill="#5b6470" font-size="10">{t}</text>')
        lx += 62
    out.append("</svg>")
    return "\n".join(out)
