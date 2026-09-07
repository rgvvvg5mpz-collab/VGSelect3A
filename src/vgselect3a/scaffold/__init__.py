"""Downloadable agent skeletons for the recommended topology.

    from vgselect3a.scaffold import build_skeleton
    zip_bytes = build_skeleton(recommendation, framework="langgraph")
"""

from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING

from . import langgraph as _lg

if TYPE_CHECKING:
    from ..recommender import Recommendation

FRAMEWORKS = {"langgraph": _lg.generate}


def skeleton_files(rec: "Recommendation", framework: str = "langgraph") -> dict[str, str]:
    """Return {relative path: file content} for the skeleton."""
    if framework not in FRAMEWORKS:
        raise ValueError(f"Unknown framework {framework!r}; choose from {sorted(FRAMEWORKS)}")
    return FRAMEWORKS[framework](rec)


def build_skeleton(rec: "Recommendation", framework: str = "langgraph") -> bytes:
    files = skeleton_files(rec, framework)
    buf = io.BytesIO()
    root = f"{_lg.slug(rec.profile.name)}-agent"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(f"{root}/{path}", content)
    return buf.getvalue()
