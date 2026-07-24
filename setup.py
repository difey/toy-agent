"""Setup script with automatic frontend build integration.

When ``uv pip install .`` or ``pip install .`` is run, setuptools will:
1. Install frontend Node dependencies (``npm install``)
2. Build the frontend (``npm run build`` → outputs to static/dist/)
3. Package everything into the Python wheel
"""

import subprocess
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"


def _build_frontend() -> None:
    """Run ``npm install`` and ``npm run build`` in the frontend directory."""
    if not FRONTEND_DIR.is_dir():
        print(
            "[frontend-build] frontend/ directory not found, skipping",
            file=sys.stderr,
        )
        return

    # Check if node is available
    try:
        subprocess.run(
            ["node", "--version"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        print(
            "[frontend-build] Node.js is not available, skipping frontend build",
            file=sys.stderr,
        )
        return

    print("[frontend-build] Installing frontend dependencies...", file=sys.stderr, flush=True)
    result = subprocess.run(
        ["npm", "install", "--loglevel=warn"],
        cwd=str(FRONTEND_DIR),
    )
    if result.returncode != 0:
        print("[frontend-build] npm install failed", file=sys.stderr)
        raise RuntimeError("npm install failed")

    print("[frontend-build] Building frontend...", file=sys.stderr, flush=True)
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=str(FRONTEND_DIR),
    )
    if result.returncode != 0:
        print("[frontend-build] npm run build failed", file=sys.stderr)
        raise RuntimeError("npm run build failed")

    print("[frontend-build] Frontend built successfully → static/dist/", file=sys.stderr)


class BuildFrontendFirst(build_py):
    """Custom ``build_py`` command that builds the frontend first."""

    def run(self) -> None:
        _build_frontend()
        super().run()


setup(cmdclass={"build_py": BuildFrontendFirst})
