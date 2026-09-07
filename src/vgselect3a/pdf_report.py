"""Architecture document (PDF) for a Recommendation. Requires the `pdf` extra (reportlab).

    from vgselect3a.pdf_report import build_pdf
    pdf_bytes = build_pdf(recommendation)
"""

from __future__ import annotations

import datetime as _dt
import io
from typing import TYPE_CHECKING

from . import PRODUCT_NAME, __version__
from .render import CITATIONS, layout_plan
from .topologies import MODEL_TIERS

if TYPE_CHECKING:
    from .recommender import Recommendation

VG_RED = "#96151D"
INK = "#1E1E1E"
MUTED = "#6F6F6F"
LINE = "#D9D6D2"
TINT = "#F8ECED"
TIER_FILL = {"opus": "#0f1a33", "sonnet": "#1f5eff", "haiku": "#6f9bff", "code": "#e9edf3"}
TIER_INK = {"opus": "#ffffff", "sonnet": "#ffffff", "haiku": "#0f1a33", "code": "#1c2128"}


def _require_reportlab():
    try:
        import reportlab  # noqa: F401
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("PDF output needs reportlab: pip install 'vg-select-3a[pdf]'") from e


def _esc(s: object) -> str:
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_inline(s: str) -> str:
    """Escape, then turn **bold** into <b>."""
    out = _esc(s)
    parts = out.split("**")
    return "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(parts))


def build_pdf(rec: "Recommendation") -> bytes:
    _require_reportlab()
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    p = rec.profile
    best = rec.primary
    by_id = {c.topology.id: c for c in rec.candidates}
    today = _dt.date.today().isoformat()

    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5, textColor=MUTED)
    cell = ParagraphStyle("cell", parent=body, fontSize=8.5, leading=11)
    cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")
    h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=VG_RED, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=INK, spaceBefore=12, spaceAfter=5)
    h3 = ParagraphStyle("h3", parent=body, fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=VG_RED, spaceBefore=8, spaceAfter=3)
    kicker = ParagraphStyle("kicker", parent=small, textColor=VG_RED, fontName="Helvetica-Bold")
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=2, spaceAfter=2)

    def bl(text: str) -> Paragraph:
        return Paragraph(text, bullet, bulletText="•")

    def cite(key: str) -> str:
        return f'<font size="7" color="{MUTED}">[{_esc(CITATIONS.get(key, key))}]</font>'

    def table(rows, widths, header=True, zebra=True, highlight_row: int | None = None):
        t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(LINE)),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FAF9F7")), ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor(LINE))]
        if zebra:
            for i in range(1 if header else 0, len(rows)):
                if i % 2 == 0:
                    style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FCFBFA")))
        if highlight_row is not None:
            style.append(("BACKGROUND", (0, highlight_row), (-1, highlight_row), colors.HexColor(TINT)))
        t.setStyle(TableStyle(style))
        return t

    class Diagram(Flowable):
        def __init__(self, plan, max_width):
            super().__init__()
            self.L = layout_plan(plan, max_per_row=4)
            self.plan = plan
            self.scale = min(1.0, max_width / max(self.L["width"], 1), 260 / max(self.L["height"], 1))
            self.width = self.L["width"] * self.scale
            self.height = self.L["height"] * self.scale

        def wrap(self, aw, ah):
            return self.width, self.height

        def draw(self):
            c = self.canv
            L, s = self.L, self.scale
            W, H, pos = L["W"], L["H"], L["pos"]
            Hh = L["height"]
            c.saveState()
            c.scale(s, s)

            def Y(y):  # flip
                return Hh - y

            for x0, y0, x1, y1, g in L["frames"]:
                c.setFillColor(colors.HexColor("#f3f6fb")); c.setStrokeColor(colors.HexColor("#9db3e8")); c.setDash(4, 3)
                c.roundRect(x0, Y(y1), x1 - x0, y1 - y0, 8, stroke=1, fill=1)
                c.setDash()
                c.setFillColor(colors.HexColor("#3c5aa6")); c.setFont("Helvetica-Bold", 9)
                c.drawString(x0 + 8, Y(y0 + 13), f"{g} - parallel")
            for src, dst, label, back in L["edges"]:
                (sx, sy), (dx, dy) = pos[src], pos[dst]
                if back:
                    x1, y1 = sx + W * 0.7, sy + H if dy > sy else sy
                    x2, y2 = dx + W * 0.7, dy if dy > sy else dy + H
                    c.setStrokeColor(colors.HexColor("#9aa5b5")); c.setDash(3, 3)
                else:
                    x1, y1, x2, y2 = sx + W * 0.4, sy + H, dx + W * 0.4, dy
                    c.setStrokeColor(colors.HexColor("#5b6470")); c.setDash()
                c.setLineWidth(1.2)
                c.line(x1, Y(y1), x2, Y(y2))
                # arrow head
                import math
                ang = math.atan2(Y(y2) - Y(y1), x2 - x1)
                for d in (-0.5, 0.5):
                    c.line(x2, Y(y2), x2 - 8 * math.cos(ang + d), Y(y2) - 8 * math.sin(ang + d))
                c.setDash()
                if label:
                    c.setFillColor(colors.HexColor("#5b6470")); c.setFont("Helvetica", 8)
                    c.drawCentredString((x1 + x2) / 2, Y((y1 + y2) / 2) + 3, label)
            by_id = {cc.id: cc for cc in self.plan.components}
            for cid, (x, y) in pos.items():
                comp = by_id[cid]
                c.setFillColor(colors.HexColor(TIER_FILL.get(comp.tier, "#cccccc"))); c.setStrokeColor(colors.HexColor("#c9cdd6"))
                c.roundRect(x, Y(y + H), W, H, 7, stroke=1, fill=1)
                c.setFillColor(colors.HexColor(TIER_INK.get(comp.tier, "#000")))
                name = comp.name if len(comp.name) <= 26 else comp.name[:25] + "…"
                c.setFont("Helvetica-Bold", 10); c.drawCentredString(x + W / 2, Y(y + 21), name)
                c.setFont("Helvetica", 8); c.drawCentredString(x + W / 2, Y(y + 38), f"{comp.model_id if comp.tier != 'code' else 'code'} · effort {comp.effort}")
            lx = 30
            for t in ("opus", "sonnet", "haiku", "code"):
                c.setFillColor(colors.HexColor(TIER_FILL[t])); c.setStrokeColor(colors.HexColor("#c9cdd6"))
                c.roundRect(lx, Y(22), 12, 12, 2, stroke=1, fill=1)
                c.setFillColor(colors.HexColor(MUTED)); c.setFont("Helvetica", 8); c.drawString(lx + 16, Y(20), t)
                lx += 62
            c.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=16 * mm,
                            title=f"Architecture recommendation: {p.name}", author=PRODUCT_NAME, subject="Agentic application architecture")
    avail = A4[0] - 36 * mm

    def on_page(canvas, doc_):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(VG_RED)); canvas.rect(0, A4[1] - 9 * mm, A4[0], 9 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white); canvas.setFont("Helvetica-Bold", 8.5)
        canvas.drawString(18 * mm, A4[1] - 6 * mm, "VG Select: 3A  ·  Automated Agentic Architecture")
        canvas.setFont("Helvetica", 8); canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 6 * mm, f"Architecture recommendation · {p.name}")
        canvas.setFillColor(colors.HexColor(MUTED)); canvas.setFont("Helvetica", 7.5)
        canvas.drawString(18 * mm, 9 * mm, f"Generated {today} by VG Select: 3A v{__version__} · estimates are order-of-magnitude for ranking, not measurements")
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    S: list = []
    # ------------------------------------------------------------ cover / summary
    S.append(Paragraph("ARCHITECTURE RECOMMENDATION", kicker))
    S.append(Paragraph(_esc(p.name), h1))
    if p.description:
        S.append(Paragraph(_esc(p.description), body))
    S.append(Spacer(1, 6))
    verdict = {"fits": "Fits the latency budget", "tight": "Tight against the budget", "exceeds": "Exceeds the budget", "far over": "Far over the budget"}[best.latency_verdict]
    summary_rows = [
        [Paragraph("Recommended architecture", cellb), Paragraph(f"<b>{_esc(best.topology.name)}</b> ({_esc(best.topology.family.replace('_', ' '))})", cell)],
        [Paragraph("Budget verdict", cellb), Paragraph(_esc(verdict), cell)],
        [Paragraph("Estimated p50 latency", cellb), Paragraph(f"~{best.estimate.latency_s:.0f} s of a {p.latency_budget_s:.0f} s budget", cell)],
        [Paragraph("Estimated cost per request", cellb), Paragraph(f"${best.estimate.cost_usd:.3f} at list prices, no caching", cell)],
        [Paragraph("Tokens vs. one model call", cellb), Paragraph(f"{best.estimate.token_multiplier:.0f}x ({best.estimate.llm_calls} model calls)", cell)],
        [Paragraph("Score", cellb), Paragraph(f"{best.score:+.1f} (fit {best.fit:+.1f}, latency {best.latency_adj:+.1f}, cost {best.cost_adj:+.1f})", cell)],
    ]
    if rec.scan is not None:
        cur = by_id.get(rec.scan.current_topology)
        summary_rows.append([Paragraph("Currently implemented", cellb), Paragraph(_esc(cur.topology.name if cur else rec.scan.current_topology) + (" (matches)" if rec.scan.current_topology == best.topology.id else " (changes)"), cell)])
    S.append(table(summary_rows, [50 * mm, avail - 50 * mm], header=False, zebra=False))
    S.append(Spacer(1, 8))
    S.append(Paragraph(_md_inline(rec.headline), body))

    S.append(Paragraph("1. Why this architecture", h2))
    pos_ = [s_ for s_ in sorted(best.signals, key=lambda s_: -s_.delta) if s_.delta > 0]
    neg_ = [s_ for s_ in sorted(best.signals, key=lambda s_: s_.delta) if s_.delta < 0]
    for s_ in pos_ or []:
        S.append(bl(f"<b>+{s_.delta:.1f}</b> {_esc(s_.rationale)} {cite(s_.citation)}"))
    if not pos_:
        S.append(bl("No rule specifically favours this topology; it ranks first because it is viable and has the best combined latency and cost fit."))
    if neg_:
        S.append(Paragraph("Counter-signals", h3))
        for s_ in neg_:
            S.append(bl(f"<b>{s_.delta:.1f}</b> {_esc(s_.rationale)} {cite(s_.citation)}"))

    # ------------------------------------------------------------ scan
    sec = 2
    if rec.scan is not None:
        sc = rec.scan
        S.append(Paragraph(f"{sec}. Repository scan", h2)); sec += 1
        S.append(Paragraph(f"{sc.files_scanned} files scanned under <font face='Courier'>{_esc(sc.root)}</font>. Frameworks: {_esc(', '.join(sc.frameworks) or 'none')}. "
                           f"Tools found: {len([t for t in sc.tools if not t.startswith('~')])}. Knowledge sources: {_esc(', '.join(sc.knowledge_sources) or 'none')}. "
                           f"Side effects: {_esc(', '.join(sc.side_effects) or 'none')}. Current topology as implemented: <b>{_esc(sc.current_topology)}</b> ({_esc(sc.current_topology_reason)}).", body))
        cur = by_id.get(sc.current_topology)
        if cur and cur.topology.id != best.topology.id:
            S.append(Paragraph("Current vs. recommended", h3))
            S.append(table([
                [Paragraph("", cellb), Paragraph(f"Current: {_esc(cur.topology.name)}", cellb), Paragraph(f"Recommended: {_esc(best.topology.name)}", cellb)],
                [Paragraph("Score", cell), Paragraph(f"{cur.score:+.1f}", cell), Paragraph(f"{best.score:+.1f}", cell)],
                [Paragraph("Est. latency", cell), Paragraph(f"~{cur.estimate.latency_s:.0f} s", cell), Paragraph(f"~{best.estimate.latency_s:.0f} s", cell)],
                [Paragraph("Est. cost / request", cell), Paragraph(f"${cur.estimate.cost_usd:.3f}", cell), Paragraph(f"${best.estimate.cost_usd:.3f}", cell)],
                [Paragraph("Tokens vs. one call", cell), Paragraph(f"{cur.estimate.token_multiplier:.0f}x", cell), Paragraph(f"{best.estimate.token_multiplier:.0f}x", cell)],
            ], [40 * mm, (avail - 40 * mm) / 2, (avail - 40 * mm) / 2]))
        S.append(Paragraph("Inferred profile fields", h3))
        rows = [[Paragraph("Field", cellb), Paragraph("Value", cellb), Paragraph("Conf.", cellb), Paragraph("Reason", cellb)]]
        for i in sc.inferred:
            rows.append([Paragraph(_esc(i.field), cell), Paragraph(_esc(i.value), cell), Paragraph(f"{i.confidence:.0%}", cell), Paragraph(_esc(i.reason), cell)])
        S.append(table(rows, [38 * mm, 24 * mm, 14 * mm, avail - 76 * mm]))
        if sc.evidence:
            S.append(Paragraph("Evidence (first hits per category)", h3))
            rows = [[Paragraph("Category", cellb), Paragraph("Label", cellb), Paragraph("Location", cellb), Paragraph("Snippet", cellb)]]
            for e in sc.evidence[:40]:
                rows.append([Paragraph(_esc(e.category), cell), Paragraph(_esc(e.label), cell), Paragraph(f"<font face='Courier' size='7'>{_esc(e.path)}:{e.line}</font>", cell), Paragraph(f"<font size='7'>{_esc(e.snippet[:90])}</font>", cell)])
            S.append(table(rows, [24 * mm, 30 * mm, 50 * mm, avail - 104 * mm]))

    # ------------------------------------------------------------ ranked options
    S.append(Paragraph(f"{sec}. Options compared", h2)); sec += 1
    S.append(Paragraph("Score = structural fit + latency adjustment + cost adjustment. Latency is the estimated p50 on the critical path; cost sums every call at list prices. Non-viable options cannot do the job and are listed last.", small))
    rows = [[Paragraph(h_, cellb) for h_ in ("#", "Architecture", "Score", "Fit", "Latency", "Budget", "Cost/req", "Tokens", "Calls")]]
    for i, c in enumerate(rec.candidates, 1):
        name = _esc(c.topology.name) + ("" if c.viable else f"<br/><font size='7' color='{MUTED}'>not viable: {_esc(c.infeasible_reason)}</font>")
        rows.append([Paragraph(str(i), cell), Paragraph(name, cell), Paragraph(f"{c.score:+.1f}", cell), Paragraph(f"{c.fit:+.1f}", cell),
                     Paragraph(f"~{c.estimate.latency_s:.0f} s", cell), Paragraph(_esc(c.latency_verdict), cell), Paragraph(f"${c.estimate.cost_usd:.3f}", cell),
                     Paragraph(f"{c.estimate.token_multiplier:.0f}x", cell), Paragraph(str(c.estimate.llm_calls), cell)])
    S.append(table(rows, [8 * mm, 58 * mm, 14 * mm, 12 * mm, 18 * mm, 18 * mm, 18 * mm, 15 * mm, 12 * mm], highlight_row=1))
    S.append(Spacer(1, 4))
    S.append(Paragraph("Latency/accuracy frontier (no option is both faster and a better structural fit): " +
                       _esc(", ".join(f"{c.topology.name} (~{c.estimate.latency_s:.0f} s, fit {c.quality_proxy:+.1f})" for c in rec.frontier)) +
                       f". Fastest viable within budget: <b>{_esc(rec.fastest_viable.topology.name if rec.fastest_viable else 'none')}</b>. "
                       f"Strongest structural fit: <b>{_esc(rec.most_accurate.topology.name if rec.most_accurate else '')}</b>.", body))
    S.append(Paragraph("Runners-up", h3))
    for c in [c for c in rec.candidates[1:] if c.viable][:3]:
        top = [s_ for s_ in sorted(c.signals, key=lambda s_: -s_.delta) if s_.delta > 0][:2]
        why = "; ".join(s_.rationale.rstrip(".") for s_ in top) or c.topology.when_to_use
        S.append(bl(f"<b>{_esc(c.topology.name)}</b> (score {c.score:+.1f}, ~{c.estimate.latency_s:.0f} s, {c.estimate.token_multiplier:.0f}x tokens): {_esc(why)}."))

    # ------------------------------------------------------------ plan
    S.append(KeepTogether([Paragraph(f"{sec}. Decomposition plan: {_esc(best.topology.name)}", h2), Paragraph(_esc(best.topology.summary), body), Spacer(1, 4), Diagram(rec.plan, avail)])); sec += 1
    S.append(Spacer(1, 6))
    rows = [[Paragraph(h_, cellb) for h_ in ("Component", "Role", "Model", "Effort", "Tools", "Parallel")]]
    for c in rec.plan.components:
        rows.append([Paragraph(_esc(c.name), cell), Paragraph(_esc(c.role), cell), Paragraph(f"<font face='Courier' size='7.5'>{_esc(c.model_id)}</font>", cell),
                     Paragraph(_esc(c.effort), cell), Paragraph(_esc(c.tools or "-"), cell), Paragraph(_esc(c.parallel_group or "-"), cell)])
    S.append(table(rows, [34 * mm, avail - 34 * mm - 30 * mm - 14 * mm - 34 * mm - 18 * mm, 30 * mm, 14 * mm, 34 * mm, 18 * mm]))
    if rec.plan.briefing_rules:
        S.append(Paragraph("Briefing and coordination rules", h3))
        for b in rec.plan.briefing_rules:
            S.append(bl(_esc(b)))

    # ------------------------------------------------------------ next steps
    S.append(Paragraph(f"{sec}. Cross-cutting recommendations", h2)); sec += 1
    for a in rec.plan.augmentations:
        S.append(bl(f"<b>{_esc(a.title)}.</b> {_esc(a.why)} {cite(a.citation)}"))

    # ------------------------------------------------------------ assumptions & appendix
    S.append(Paragraph(f"{sec}. Estimate assumptions", h2)); sec += 1
    for n in best.estimate.assumptions:
        S.append(bl(_esc(n)))
    S.append(bl("Serving assumptions: " + _esc("; ".join(f"{t.model_id} ~{t.ttft_s}s TTFT, ~{t.tokens_per_s:.0f} tok/s" for t in MODEL_TIERS.values())) + f"; tool call ~{p.tool_latency_s}s."))
    S.append(bl(f"Reading load per task {p.context_tokens_per_task:,} tokens (context pressure: {p.context_pressure}); output type {_esc(p.output_type)}."))
    S.append(bl("Latency is the critical path (parallel branches count once); cost sums every call at list prices without caching. Treat both as order-of-magnitude."))

    S.append(Paragraph(f"Appendix A. Workload profile used", h2))
    rows = [[Paragraph("Field", cellb), Paragraph("Value", cellb), Paragraph("Field", cellb), Paragraph("Value", cellb)]]
    items = [(k, v) for k, v in p.to_dict().items() if k not in ("description",)]
    for i in range(0, len(items), 2):
        left = items[i]
        right = items[i + 1] if i + 1 < len(items) else ("", "")
        rows.append([Paragraph(_esc(left[0]), cell), Paragraph(_esc(left[1]), cell), Paragraph(_esc(right[0]), cell), Paragraph(_esc(right[1]), cell)])
    S.append(table(rows, [avail * 0.22, avail * 0.28, avail * 0.22, avail * 0.28]))

    S.append(Paragraph("Appendix B. Sources", h2))
    used = sorted({s_.citation for c in rec.candidates for s_ in c.signals} | {a.citation for a in rec.plan.augmentations})
    for k in used:
        S.append(bl(f"<b>{_esc(k)}</b>: {_esc(CITATIONS.get(k, k))}"))
    S.append(Paragraph("Full evidence and the consolidated decision framework: docs/industry_guidance.md and docs/METHODOLOGY.md in the VG Select: 3A repository.", small))

    doc.build(S, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
