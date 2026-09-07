"""Write the service's OpenAPI document to openapi/vgselect-3a.openapi.json."""
import json
from pathlib import Path

from vgselect3a.service.app import app

out = Path(__file__).resolve().parents[1] / "openapi" / "vgselect-3a.openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2))
print(f"wrote {out}")
