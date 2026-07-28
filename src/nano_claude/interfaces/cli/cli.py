import argparse
import os
from pathlib import Path
from nano_claude.interfaces.web.app import start_web_ui

def _ensure_cwd(cwd: str) -> str:
    resolved = str(Path(cwd).resolve())
    os.makedirs(resolved, exist_ok=True)
    return resolved

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="nano-claude",
        description="nanoClaude - a CLI coding assistant with web UI.",
    )
    parser.add_argument("--cwd", default=None,
                        help="Working directory (default: current directory)")
    parser.add_argument("--port", type=int, default=8080,
                        help="Port for web UI server (default: 8080)")

    args = parser.parse_args()
    resolved_cwd = _ensure_cwd(args.cwd or os.getcwd())
    start_web_ui(resolved_cwd, port=args.port)

if __name__ == "__main__":
    main()
