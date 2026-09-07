"""FastAPI application exposing VG Select: 3A as a service.

Run:  vgselect-service            (or: uvicorn vgselect3a.service.app:app)
Docs: /docs (Swagger UI), /redoc, /openapi.json
UI:   /
Config (environment variables):
  VGSELECT_SCAN_ROOTS        colon-separated directories that may be scanned by path (default: none)
  VGSELECT_ALLOW_GIT_CLONE   "1" to allow POST /api/v1/scan with git_url (default: off)
  VGSELECT_MAX_UPLOAD_MB     max zip upload size (default 50)
  VGSELECT_CORS_ORIGINS      comma-separated origins for CORS (default: none)
  VGSELECT_HOST / VGSELECT_PORT  bind address for `vgselect-service` (default 0.0.0.0:8080)
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import PRODUCT_NAME, __version__
from ..profile import FIELD_SPECS, WorkloadProfile
from ..recommender import recommend
from ..render import CITATIONS
from ..scanner import ScanResult, merge_profile, scan_repository
from ..topologies import TOPOLOGIES
from .schemas import DeliverableRequest, DescribeRequest, HealthOut, RecommendRequest, RecommendationOut, ScanOut, ScanRequest

TAGS = [
    {"name": "recommend", "description": "Rank topologies for a workload profile and return a decomposition plan."},
    {"name": "scan", "description": "Scan a code repository to infer the workload profile before recommending."},
    {"name": "deliverables", "description": "Architecture document (PDF) and downloadable agent skeleton (zip) for the recommendation."},
    {"name": "reference", "description": "Field definitions, bundled examples, topology catalog."},
]

app = FastAPI(
    title=PRODUCT_NAME,
    version=__version__,
    summary="Scans a repository and workload profile, then recommends an agentic application architecture that balances latency and accuracy.",
    description=(
        "VG Select: 3A ranks ten agent topologies (single call, single agent, prompt chain, router, parallel sectioning, "
        "voting, evaluator-optimizer, orchestrator + workers, hierarchical, handoffs) using evidence-cited rules, estimates "
        "latency and cost for each, and produces a concrete orchestrator/subagent decomposition plan.\n\n"
        "Typical flow: `POST /api/v1/scan` (or `/api/v1/scan/upload`) to infer a profile from code, review the inferred "
        "fields, then `POST /api/v1/recommend` with corrections."
    ),
    openapi_tags=TAGS,
    contact={"name": "VG Select: 3A"},
    license_info={"name": "MIT"},
)

_origins = [o.strip() for o in os.environ.get("VGSELECT_CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ helpers

def _scan_roots() -> list[Path]:
    raw = os.environ.get("VGSELECT_SCAN_ROOTS", "")
    return [Path(p).resolve() for p in raw.split(":") if p.strip()]


def _git_allowed() -> bool:
    return os.environ.get("VGSELECT_ALLOW_GIT_CLONE", "0") in ("1", "true", "yes")


def _describe_enabled() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("VGSELECT_DESCRIBE_ENABLED"))


def _profile_dict(model: Any) -> dict[str, Any]:
    if model is None:
        return {}
    return {k: v for k, v in model.model_dump(exclude_none=True).items()}


def _rec_out(profile_data: dict[str, Any], scan: ScanResult | None, include_markdown: bool) -> RecommendationOut:
    try:
        profile = WorkloadProfile.from_dict(profile_data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    rec = recommend(profile, scan=scan)
    data = rec.to_dict()
    data["product"] = PRODUCT_NAME
    data["version"] = __version__
    data["report_markdown"] = rec.to_markdown() if include_markdown else None
    return RecommendationOut(**data)


def _check_path(path: str) -> Path:
    roots = _scan_roots()
    if not roots:
        raise HTTPException(status_code=403, detail="Path scanning is disabled: set VGSELECT_SCAN_ROOTS on the server, or upload a zip.")
    target = Path(path).resolve()
    if not any(target == r or r in target.parents for r in roots):
        raise HTTPException(status_code=403, detail=f"{path} is outside the allowed scan roots.")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"{path} is not a directory.")
    return target


def _clone(url: str) -> Path:
    if not _git_allowed():
        raise HTTPException(status_code=403, detail="Git cloning is disabled: set VGSELECT_ALLOW_GIT_CLONE=1.")
    if not (url.startswith("https://") or url.startswith("ssh://") or url.startswith("git@")):
        raise HTTPException(status_code=422, detail="git_url must be an https://, ssh:// or git@ URL.")
    tmp = Path(tempfile.mkdtemp(prefix="vgselect-"))
    try:
        subprocess.run(["git", "clone", "--depth", "1", "--quiet", url, str(tmp / "repo")], check=True, timeout=300, capture_output=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise HTTPException(status_code=502, detail=f"git clone failed: {getattr(e, 'stderr', b'')!r}") from e
    return tmp / "repo"


def _scan_and_maybe_recommend(root: Path, overrides: dict[str, Any], do_recommend: bool, include_markdown: bool) -> ScanOut:
    scan = scan_repository(root)
    profile = merge_profile(scan, overrides)
    out = ScanOut(scan=scan.to_dict(), profile=profile)
    if do_recommend:
        out.recommendation = _rec_out(profile, scan, include_markdown)
    return out


# ------------------------------------------------------------------ routes

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def ui() -> str:
    return (resources.files("vgselect3a") / "service" / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/health", response_model=HealthOut, tags=["reference"])
def health() -> HealthOut:
    try:
        import reportlab  # noqa: F401
        pdf_ok = True
    except ImportError:
        pdf_ok = False
    return HealthOut(status="ok", product=PRODUCT_NAME, version=__version__, scan_roots=[str(r) for r in _scan_roots()],
                     git_clone_enabled=_git_allowed(), describe_enabled=_describe_enabled(), pdf_enabled=pdf_ok)


@app.get("/api/v1/fields", tags=["reference"], summary="Profile field definitions")
def fields() -> list[dict[str, Any]]:
    return [{"name": s.name, "kind": s.kind, "description": s.description, "choices": list(s.choices), "default": s.default,
             "minimum": s.minimum, "maximum": s.maximum, "group": s.group} for s in FIELD_SPECS]


@app.get("/api/v1/citations", tags=["reference"], summary="Citation keys used in rules and recommendations")
def citations() -> dict[str, str]:
    return dict(CITATIONS)


@app.get("/api/v1/topologies", tags=["reference"], summary="Topology catalog")
def topologies() -> list[dict[str, Any]]:
    return [t.__dict__ for t in TOPOLOGIES.values()]


@app.get("/api/v1/examples", tags=["reference"], summary="Bundled example profiles")
def examples() -> list[dict[str, Any]]:
    pkg = resources.files("vgselect3a") / "examples"
    out = []
    for p in sorted(pkg.iterdir()):
        if p.name.endswith(".json"):
            d = json.loads(p.read_text())
            out.append({"name": p.name[:-5], "description": d.get("description", ""), "profile": d})
    return out


@app.post("/api/v1/recommend", response_model=RecommendationOut, tags=["recommend"], summary="Recommend a topology for a profile")
def api_recommend(req: RecommendRequest) -> RecommendationOut:
    return _rec_out(_profile_dict(req.profile), None, req.include_markdown)


def _rec_for_deliverable(req: DeliverableRequest):
    scan = ScanResult.from_dict(req.scan) if req.scan else None
    try:
        profile = WorkloadProfile.from_dict(_profile_dict(req.profile))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return recommend(profile, scan=scan)


@app.post("/api/v1/recommend/pdf", tags=["deliverables"], summary="Architecture document (PDF)",
          responses={200: {"content": {"application/pdf": {}}, "description": "PDF architecture document"}}, response_class=Response)
def api_recommend_pdf(req: DeliverableRequest) -> Response:
    rec = _rec_for_deliverable(req)
    try:
        data = rec.to_pdf()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in rec.profile.name) or "app"
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}-architecture.pdf"'})


@app.post("/api/v1/recommend/skeleton", tags=["deliverables"], summary="Downloadable agent skeleton (zip) for the recommended topology",
          responses={200: {"content": {"application/zip": {}}, "description": "Zip archive of a runnable project skeleton"}}, response_class=Response)
def api_recommend_skeleton(req: DeliverableRequest) -> Response:
    rec = _rec_for_deliverable(req)
    data = rec.to_skeleton(req.framework)
    name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in rec.profile.name) or "app"
    return Response(content=data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}-{req.framework}-skeleton.zip"'})


@app.post("/api/v1/scan", response_model=ScanOut, tags=["scan"], summary="Scan a repository by server path or git URL")
def api_scan(req: ScanRequest) -> ScanOut:
    if bool(req.path) == bool(req.git_url):
        raise HTTPException(status_code=422, detail="Provide exactly one of `path` or `git_url`.")
    tmp: Path | None = None
    try:
        if req.path:
            root = _check_path(req.path)
        else:
            root = _clone(req.git_url or "")
            tmp = root.parent
        return _scan_and_maybe_recommend(root, _profile_dict(req.overrides), req.recommend, req.include_markdown)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


@app.post("/api/v1/scan/upload", response_model=ScanOut, tags=["scan"], summary="Scan an uploaded zip archive of a repository")
async def api_scan_upload(
    archive: UploadFile = File(..., description="Zip archive of the repository (node_modules, .git etc. are skipped)."),
    overrides: str = Form("{}", description="JSON object of profile fields that override scan inferences."),
    recommend: bool = Form(True),
    include_markdown: bool = Form(True),
) -> ScanOut:
    limit = int(os.environ.get("VGSELECT_MAX_UPLOAD_MB", "50")) * 1024 * 1024
    data = await archive.read()
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"Archive exceeds {limit // (1024 * 1024)} MB.")
    try:
        ov = json.loads(overrides or "{}")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"overrides is not valid JSON: {e}") from e
    tmp = Path(tempfile.mkdtemp(prefix="vgselect-"))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.infolist():
                name = member.filename
                if name.startswith("/") or ".." in Path(name).parts:
                    raise HTTPException(status_code=422, detail=f"Unsafe path in archive: {name}")
            zf.extractall(tmp)
        # if the archive wraps everything in one top-level folder, descend into it
        entries = [p for p in tmp.iterdir() if not p.name.startswith("__MACOSX")]
        root = entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp
        return _scan_and_maybe_recommend(root, ov, recommend, include_markdown)
    except zipfile.BadZipFile as e:
        raise HTTPException(status_code=422, detail="Upload is not a valid zip archive.") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.post("/api/v1/describe", response_model=RecommendationOut, tags=["recommend"], summary="Infer a profile from prose with Claude, then recommend")
def api_describe(req: DescribeRequest) -> RecommendationOut:
    if not _describe_enabled():
        raise HTTPException(status_code=503, detail="Describe is unavailable: install the `llm` extra and configure Anthropic credentials on the server.")
    from ..intake_llm import profile_from_description

    profile = profile_from_description(req.text, model=req.model)
    data = profile.to_dict()
    data.update(_profile_dict(req.overrides))
    return _rec_out(data, None, req.include_markdown)


@app.exception_handler(NotADirectoryError)
async def _not_dir(_, exc: NotADirectoryError):
    return JSONResponse(status_code=404, content={"detail": f"Not a directory: {exc}"})


def run() -> None:
    import uvicorn

    uvicorn.run("vgselect3a.service.app:app", host=os.environ.get("VGSELECT_HOST", "0.0.0.0"), port=int(os.environ.get("VGSELECT_PORT", "8080")))


if __name__ == "__main__":
    run()
