"""
Vercel entry point — imports the FastAPI app so Vercel's Python runtime
can serve it as a serverless ASGI function.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.main import app  # noqa: F401  (Vercel looks for `app`)
