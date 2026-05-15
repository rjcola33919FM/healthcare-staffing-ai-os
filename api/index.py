"""
Vercel entry point.
Wraps the import in a try/except so startup errors surface as readable
JSON instead of a generic 500, making them diagnosable without log access.
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_import_error: str | None = None

try:
    from src.main import app
except Exception:
    _import_error = traceback.format_exc()
    from fastapi import FastAPI
    app = FastAPI(title="Healthcare Staffing AI OS — startup error")

    @app.get("/{path:path}")
    async def _startup_error(path: str = ""):
        return {
            "status": "startup_failed",
            "error": _import_error,
        }
