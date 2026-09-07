"""Minimal Markdown -> styled HTML converter for the VG Select: 3A docs.

Supports headings, paragraphs, bullet and numbered lists, tables, fenced code
blocks, horizontal rules, inline code, bold, italics and links. Usage:

    python scripts/md_to_html.py docs/FILE.md [--title "Page title"] > docs/FILE.html
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

STYLE = """
  body{font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1c2128;max-width:960px;margin:0 auto;padding:32px 24px;background:#fff}
  h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 10px;border-bottom:1px solid #e1e5ea;padding-bottom:6px}h3{font-size:16px;margin:22px 0 6px;color:#96151D}h4{font-size:15px;margin:18px 0 4px}
  code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;background:#f1f3f6;padding:1px 5px;border-radius:4px}
  pre{background:#0f1a33;color:#e6ecff;padding:14px;border-radius:8px;overflow:auto;font-size:13px;line-height:1.45}pre code{background:none;color:inherit;padding:0}
  table{border-collapse:collapse;width:100%;font-size:14px;margin:10px 0}th,td{text-align:left;padding:7px 9px;border-bottom:1px solid #e1e5ea;vertical-align:top}th{color:#5b6470;font-size:13px;background:#faf9f7}
  .wrap{overflow-x:auto}
  a{color:#96151D}
  ul li,ol li{margin:4px 0}
  hr{border:0;border-top:1px solid #e1e5ea;margin:28px 0}
  blockquote{border-left:4px solid #96151D;background:#f8eced;padding:10px 14px;border-radius:6px;margin:14px 0}
  .sub{color:#5b6470;margin-bottom:24px}
"""


def inline(text: str) -> str:
    """Escape, then apply inline markdown (code first so its contents stay literal)."""
    parts = re.split(r"(`[^`]*`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) >= 2:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
        else:
            s = html.escape(part, quote=False)
            s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', s)
            s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
            s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
            s = s.replace(" -> ", " &rarr; ")
            s = re.sub(r'(?<!href=")(?<!">)(https?://[^\s<"]+?)(?=[\s<;),]|$)', lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', s)
            out.append(s)
    return "".join(out)


def convert(md: str) -> tuple[str, str]:
    lines = md.splitlines()
    out: list[str] = []
    title = ""
    i = 0
    para: list[str] = []

    def flush_para():
        nonlocal para
        if para:
            out.append(f"<p>{inline(' '.join(l.strip() for l in para))}</p>")
            para = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # fenced code
        if stripped.startswith("```"):
            flush_para()
            lang = stripped[3:].strip()
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            cls = f' class="lang-{html.escape(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(buf))}</code></pre>")
            continue
        # heading
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            flush_para()
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 1 and not title:
                title = re.sub(r"[*`]", "", text)
            anchor = re.sub(r"[^a-z0-9]+", "-", re.sub(r"[*`]", "", text).lower()).strip("-")
            out.append(f'<h{level} id="{anchor}">{inline(text)}</h{level}>')
            i += 1
            continue
        # horizontal rule
        if re.match(r"^-{3,}$", stripped):
            flush_para(); out.append("<hr>"); i += 1; continue
        # table
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{2,}", lines[i + 1].strip()):
            flush_para()
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")]); i += 1
            out.append('<div class="wrap"><table><tr>' + "".join(f"<th>{inline(h)}</th>" for h in header) + "</tr>")
            for r in rows:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            out.append("</table></div>")
            continue
        # blockquote
        if stripped.startswith(">"):
            flush_para()
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip()); i += 1
            out.append(f"<blockquote>{inline(' '.join(buf))}</blockquote>")
            continue
        # lists (with continuation lines indented by 2+ spaces)
        lm = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if lm:
            flush_para()
            ordered = lm.group(2)[0].isdigit()
            tag = "ol" if ordered else "ul"
            items = []
            while i < len(lines):
                lm2 = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", lines[i])
                if lm2 and (lm2.group(2)[0].isdigit()) == ordered and len(lm2.group(1)) == len(lm.group(1)):
                    item = [lm2.group(3)]; i += 1
                    while i < len(lines) and lines[i].strip() and not re.match(r"^(\s*)([-*]|\d+\.)\s+", lines[i]) and lines[i].startswith(" "):
                        item.append(lines[i].strip()); i += 1
                    items.append(" ".join(item))
                else:
                    break
            out.append(f"<{tag}>" + "".join(f"<li>{inline(it)}</li>" for it in items) + f"</{tag}>")
            continue
        if not stripped:
            flush_para(); i += 1; continue
        para.append(line); i += 1
    flush_para()
    return title, "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--title")
    ap.add_argument("--out")
    args = ap.parse_args()
    title, body = convert(Path(args.source).read_text(encoding="utf-8"))
    title = args.title or title or Path(args.source).stem
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{STYLE}</style>
</head>
<body>
{body}
</body>
</html>
"""
    if args.out:
        Path(args.out).write_text(page, encoding="utf-8")
    else:
        sys.stdout.write(page)


if __name__ == "__main__":
    main()
