"""Copy the user guide into the package so the service can serve it at /guide.

    python scripts/sync_docs.py
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "USER_GUIDE.html"
DST = ROOT / "src" / "vgselect3a" / "service" / "static" / "user_guide.html"
shutil.copyfile(SRC, DST)
print(f"copied {SRC.relative_to(ROOT)} -> {DST.relative_to(ROOT)}")
