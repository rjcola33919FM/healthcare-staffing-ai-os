"""
Vercel entry point.
`app` must be an unconditional top-level name so Vercel's builder can find it.
We define a fallback FastAPI app first, then attempt to replace it with the
real app — if the real import fails the error is surfaced as a JSON response.
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI

# Placeholder — replaced below if the real import succeeds.
app = FastAPI(title="Healthcare Staffing AI OS")

_import_error: str | None = None
try:
    from src.main import app  # overwrites placeholder with the real app
except Exception:
    _import_error = traceback.format_exc()

    @app.get("/{path:path}")
    async def _startup_error(path: str = ""):
        return {"status": "startup_failed", "error": _import_error}
