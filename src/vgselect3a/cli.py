"""Command-line interface for VG Select: 3A.

    vgselect scan PATH [--format md|json] [--profile-out inferred.json]
    vgselect recommend --scan PATH [--profile overrides.json] [--set key=value]
    vgselect recommend --profile app.json [--format md|json|mermaid|svg|pdf] [--out FILE]
    vgselect scaffold --scan PATH --out my-agent.zip [--framework langgraph]
    vgselect catalog [--catalog models.json]            (list the model ecosystem)
    vgselect report-card --scan PATH [--traces runs.jsonl] [--profile overrides.json] [--format md|json]
    (recommend also accepts --traces to add the report card to the report/PDF)
    (recommend/scaffold accept --catalog, --providers, --platforms, --regions, --allow-unverified, --prefer-provider)
    vgselect recommend --example deep_research
    vgselect recommend --set task_complexity=open_ended --set latency_budget_s=600 ...
    vgselect wizard [--out profile.json]
    vgselect describe "free-text description of the app"   (needs `pip install vgselect[llm]`)
    vgselect examples
    vgselect fields
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib import resources
from pathlib import Path

from .catalog import Catalog
from .model_selector import SelectionPolicy
from .profile import FIELD_SPECS, SPEC_BY_NAME, WorkloadProfile
from .recommender import recommend
from .scanner import merge_profile, scan_markdown, scan_repository
from .traces import load_traces


def _load_example(name: str) -> dict:
    pkg = resources.files("vgselect3a") / "examples"
    path = pkg / f"{name}.json"
    if not path.is_file():
        available = sorted(p.name[:-5] for p in pkg.iterdir() if p.name.endswith(".json"))
        raise SystemExit(f"Unknown example {name!r}. Available: {', '.join(available)}")
    return json.loads(path.read_text())


def _apply_sets(data: dict, sets: list[str]) -> dict:
    for item in sets:
        if "=" not in item:
            raise SystemExit(f"--set expects key=value, got {item!r}")
        k, v = item.split("=", 1)
        if k in SPEC_BY_NAME:
            spec = SPEC_BY_NAME[k]
            if spec.kind == "int":
                data[k] = int(v)
            elif spec.kind == "float":
                data[k] = float(v)
            elif spec.kind == "bool":
                data[k] = v.strip().lower() in ("1", "true", "yes", "y")
            else:
                data[k] = v
        else:
            try:
                data[k] = json.loads(v)
            except json.JSONDecodeError:
                data[k] = v
    return data


def _emit(rec, fmt: str, out: str | None = None) -> None:
    if fmt == "pdf":
        if not out:
            raise SystemExit("--format pdf needs --out FILE.pdf")
        Path(out).write_bytes(rec.to_pdf())
        print(f"Wrote architecture document to {out}", file=sys.stderr)
        return
    if out:
        text = rec.to_json() if fmt == "json" else rec.to_mermaid() if fmt == "mermaid" else rec.to_svg() if fmt == "svg" else rec.to_markdown()
        Path(out).write_text(text)
        print(f"Wrote {fmt} report to {out}", file=sys.stderr)
        return
    if fmt == "json":
        print(rec.to_json())
    elif fmt == "mermaid":
        print(rec.to_mermaid())
    elif fmt == "svg":
        print(rec.to_svg())
    else:
        print(rec.to_markdown())


def _catalog_and_policy(args: argparse.Namespace):
    catalog = Catalog.load(args.catalog) if getattr(args, "catalog", None) else Catalog.default()
    split = lambda v: [x.strip() for x in v.split(",") if x.strip()] if v else None  # noqa: E731
    policy = SelectionPolicy(
        allowed_providers=split(getattr(args, "providers", None)),
        allowed_platforms=split(getattr(args, "platforms", None)),
        regions=split(getattr(args, "regions", None)),
        require_verified=not getattr(args, "allow_unverified", False),
        prefer_provider=getattr(args, "prefer_provider", None),
    )
    return catalog, policy


def _profile_and_scan(args: argparse.Namespace):
    data: dict = {}
    scan = None
    if args.example:
        data = _load_example(args.example)
    if args.scan:
        scan = scan_repository(args.scan)
        data = merge_profile(scan, data)
    if args.profile:
        data.update(json.loads(Path(args.profile).read_text()))
    data = _apply_sets(data, args.set or [])
    if not data:
        raise SystemExit("Provide --scan PATH, --profile, --example, or --set key=value.")
    return WorkloadProfile.from_dict(data), scan


def _traces(args: argparse.Namespace):
    path = getattr(args, "traces", None)
    return load_traces(path) if path else None


def cmd_recommend(args: argparse.Namespace) -> None:
    profile, scan = _profile_and_scan(args)
    catalog, policy = _catalog_and_policy(args)
    _emit(recommend(profile, scan=scan, catalog=catalog, policy=policy, traces=_traces(args)), args.format, getattr(args, "out", None))


def cmd_report_card(args: argparse.Namespace) -> None:
    profile, scan = _profile_and_scan(args)
    catalog, policy = _catalog_and_policy(args)
    traces = _traces(args)
    rec = recommend(profile, scan=scan, catalog=catalog, policy=policy, traces=traces)
    card = rec.report_card
    if card is None:
        from .report_card import build_report_card
        card = build_report_card(profile, scan=scan, traces=traces, rec=rec)
    text = json.dumps(card.to_dict(), indent=2) if args.format == "json" else card.to_markdown()
    if args.out:
        Path(args.out).write_text(text)
        print(f"Wrote report card to {args.out}", file=sys.stderr)
    else:
        print(text)


def cmd_scaffold(args: argparse.Namespace) -> None:
    profile, scan = _profile_and_scan(args)
    catalog, policy = _catalog_and_policy(args)
    rec = recommend(profile, scan=scan, catalog=catalog, policy=policy)
    rec._catalog = catalog
    Path(args.out).write_bytes(rec.to_skeleton(args.framework))
    print(f"Wrote {args.framework} skeleton for '{rec.primary.topology.name}' to {args.out}", file=sys.stderr)


def cmd_scan(args: argparse.Namespace) -> None:
    scan = scan_repository(args.path)
    if args.profile_out:
        Path(args.profile_out).write_text(json.dumps(merge_profile(scan), indent=2))
        print(f"Saved inferred profile to {args.profile_out}", file=sys.stderr)
    if args.format == "json":
        print(scan.to_json())
    else:
        print(scan_markdown(scan))


def cmd_wizard(args: argparse.Namespace) -> None:
    print("Answer each question (Enter keeps the default).", file=sys.stderr)
    data: dict = {}
    for spec in FIELD_SPECS:
        if spec.name == "description":
            prompt = f"{spec.name} [{spec.default!r}]: "
        elif spec.kind == "enum":
            prompt = f"{spec.name} ({'/'.join(spec.choices)}) [{spec.default}]: "
        else:
            prompt = f"{spec.name} [{spec.default}]: "
        print(f"\n{spec.description}", file=sys.stderr)
        raw = input(prompt).strip()
        if raw:
            data[spec.name] = raw
    profile = WorkloadProfile.from_dict(data)
    if args.out:
        Path(args.out).write_text(profile.to_json())
        print(f"Saved profile to {args.out}", file=sys.stderr)
    _emit(recommend(profile), args.format)


def cmd_describe(args: argparse.Namespace) -> None:
    from .intake_llm import profile_from_description

    text = args.text if args.text != "-" else sys.stdin.read()
    profile = profile_from_description(text, model=args.model)
    if args.out:
        Path(args.out).write_text(profile.to_json())
        print(f"Saved inferred profile to {args.out}", file=sys.stderr)
    else:
        print("Inferred profile:\n" + profile.to_json() + "\n", file=sys.stderr)
    _emit(recommend(profile), args.format)


def cmd_catalog(args: argparse.Namespace) -> None:
    cat = Catalog.load(args.catalog) if args.catalog else Catalog.default()
    print(f"{cat.name} ({cat.source}): {len(cat.models)} models; providers {', '.join(cat.providers())}\n")
    print(f"{'id':22s} {'provider':12s} tier tools ctx        $/M in/out   ttft  tok/s  approved verified data")
    for m in cat.models:
        print(f"{m.id:22s} {m.provider:12s} {m.reasoning_tier:>4} {m.tool_use:>5} {m.context_window:>10,} {m.input_price:>5.2f}/{m.output_price:<6.2f} {m.ttft_s:>4.1f} {m.tokens_per_s:>6.0f}  {'yes' if m.approved else 'no ':8s} {'no ' if m.illustrative else 'yes':8s} {','.join(m.data_classes)}")


def cmd_examples(_: argparse.Namespace) -> None:
    pkg = resources.files("vgselect3a") / "examples"
    for p in sorted(pkg.iterdir()):
        if p.name.endswith(".json"):
            d = json.loads(p.read_text())
            print(f"{p.name[:-5]:28s} {d.get('description', '')}")


def cmd_fields(_: argparse.Namespace) -> None:
    for spec in FIELD_SPECS:
        rng = ""
        if spec.kind == "enum":
            rng = " | ".join(spec.choices)
        elif spec.minimum is not None or spec.maximum is not None:
            rng = f"{spec.minimum}..{spec.maximum}"
        print(f"{spec.name:24s} {spec.kind:6s} default={spec.default!r:12} {rng}\n    {spec.description}")


def _add_policy_args(sp: argparse.ArgumentParser) -> None:
    g = sp.add_argument_group("model ecosystem")
    g.add_argument("--catalog", help="Path to a model catalog JSON file (default: bundled).")
    g.add_argument("--providers", help="Comma-separated allowed providers, e.g. anthropic,openai,self_hosted.")
    g.add_argument("--platforms", help="Comma-separated allowed platforms, e.g. bedrock,vertex.")
    g.add_argument("--regions", help="Comma-separated regions a model must be served in, e.g. eu.")
    g.add_argument("--allow-unverified", action="store_true", help="Let illustrative (placeholder) catalog entries be selected.")
    g.add_argument("--prefer-provider", help="Small selection bonus for this provider.")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vgselect", description="VG Select: 3A (Automated Agentic Architecture) - recommend an architecture for an agentic LLM application.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("recommend", help="Recommend a topology from a profile.")
    r.add_argument("--scan", metavar="PATH", help="Scan a repository first and use the inferred profile (overridden by --profile/--set).")
    r.add_argument("--profile", help="Path to a profile JSON file.")
    r.add_argument("--example", help="Name of a bundled example profile (see `examples`).")
    r.add_argument("--set", action="append", metavar="KEY=VALUE", help="Override a field (repeatable).")
    r.add_argument("--format", choices=("md", "json", "mermaid", "svg", "pdf"), default="md")
    r.add_argument("--out", help="Write the output to this file (required for pdf).")
    r.add_argument("--traces", metavar="FILE", help="Run-time traces (JSONL, see docs/REPORT_CARD.html) to add the agent report card.")
    _add_policy_args(r)
    r.set_defaults(fn=cmd_recommend)

    rc = sub.add_parser("report-card", help="Grade an existing agent: design complexity from the code, behavioural complexity from traces.")
    rc.add_argument("--scan", metavar="PATH", help="Repository to scan for design metrics.")
    rc.add_argument("--traces", metavar="FILE", help="Run-time traces (JSONL / JSON array / LangSmith export / OTel spans).")
    rc.add_argument("--profile")
    rc.add_argument("--example")
    rc.add_argument("--set", action="append", metavar="KEY=VALUE")
    rc.add_argument("--format", choices=("md", "json"), default="md")
    rc.add_argument("--out")
    _add_policy_args(rc)
    rc.set_defaults(fn=cmd_report_card)

    sk = sub.add_parser("scaffold", help="Generate a downloadable agent project skeleton for the recommended topology.")
    sk.add_argument("--scan", metavar="PATH")
    sk.add_argument("--profile")
    sk.add_argument("--example")
    sk.add_argument("--set", action="append", metavar="KEY=VALUE")
    sk.add_argument("--framework", choices=("langgraph",), default="langgraph")
    sk.add_argument("--out", required=True, help="Zip file to write.")
    _add_policy_args(sk)
    sk.set_defaults(fn=cmd_scaffold)

    ct = sub.add_parser("catalog", help="List the model ecosystem catalog.")
    ct.add_argument("--catalog", help="Path to a catalog JSON file (default: bundled).")
    ct.set_defaults(fn=cmd_catalog)

    sc = sub.add_parser("scan", help="Scan a repository and print what it reveals about the workload.")
    sc.add_argument("path")
    sc.add_argument("--format", choices=("md", "json"), default="md")
    sc.add_argument("--profile-out", help="Write the inferred profile JSON here.")
    sc.set_defaults(fn=cmd_scan)

    w = sub.add_parser("wizard", help="Interactive questionnaire.")
    w.add_argument("--out", help="Save the resulting profile JSON here.")
    w.add_argument("--format", choices=("md", "json", "mermaid", "svg"), default="md")
    w.set_defaults(fn=cmd_wizard)

    d = sub.add_parser("describe", help="Infer the profile from a prose description using Claude, then recommend.")
    d.add_argument("text", help="Description text, or '-' to read stdin.")
    d.add_argument("--model", default="claude-opus-5")
    d.add_argument("--out", help="Save the inferred profile JSON here.")
    d.add_argument("--format", choices=("md", "json", "mermaid", "svg"), default="md")
    d.set_defaults(fn=cmd_describe)

    sub.add_parser("examples", help="List bundled example profiles.").set_defaults(fn=cmd_examples)
    sub.add_parser("fields", help="Describe every profile field.").set_defaults(fn=cmd_fields)
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
