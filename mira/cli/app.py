"""mira 命令行入口。

用法：
  mira                            # 交互式 REPL（默认，mock provider）
  mira chat                       # 同上
  mira tui                        # Textual 界面
  mira -p "让它改个文件"            # 单次执行后退出
  mira -m deepseek/deepseek-chat -p "..." -w /path/to/ws  # 以 {provider}/{model} 指定模型
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from mira.api.client import AppClient
from mira.cli.repl import run_once, run_repl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mira", description="Mira Code — Coding Agent 平台"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["chat", "tui"],
        default="chat",
        help="chat=交互 REPL（默认）；tui=Textual 界面",
    )
    parser.add_argument("-p", "--prompt", default=None, help="单次执行模式：发送该消息后退出")
    parser.add_argument("-w", "--workspace", type=Path, default=Path.cwd(), help="工作区目录（默认当前目录）")
    parser.add_argument("-a", "--agent", default="main", help="agent id（默认 main）")
    parser.add_argument("-m", "--model", default=None, help="模型名，格式 {provider}/{model}（如 deepseek/deepseek-chat；必须带 provider，无默认 provider）")
    parser.add_argument("-q", "--quiet", action="store_true", help="单次执行时只输出最终回复")
    return parser


def main(argv: list[str] | None = None, client: AppClient | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = client or AppClient()
    if args.prompt:
        return run_once(client, args)
    if args.command == "tui":
        from mira.cli.widgets import run_tui

        return run_tui(client, args)
    return run_repl(client, args)


if __name__ == "__main__":
    raise SystemExit(main())
