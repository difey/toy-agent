"""Textual TUI：简单会话界面（复用 AppClient 与 REPL 的渲染行）。"""

from __future__ import annotations

import threading
from typing import Any

from mira.api.client import AppClient
from mira.cli.repl import event_is_terminal, event_lines

try:  # textual 为可选界面（REPL 不依赖它）
    from textual.app import App, ComposeResult
    from textual.widgets import Footer, Header, Input, RichLog
except ImportError:  # pragma: no cover
    App = None  # type: ignore[assignment]


class MiraTUI(App):  # type: ignore[misc]
    """Textual 会话界面：上为消息日志，下为输入框。"""

    CSS = """
    RichLog { border: round $primary; height: 1fr; padding: 0 1; }
    Input { dock: bottom; margin: 0 1 1 1; }
    """

    def __init__(
        self,
        client: AppClient,
        workspace,
        agent: str = "main",
        model: str | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.workspace = workspace
        self.agent = agent
        self.model = model
        self.session = None
        self._last_seq = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="log", markup=True, wrap=True)
        yield Input(placeholder="输入消息…（/exit 退出）")
        yield Footer()

    def on_mount(self) -> None:
        self.session = self.client.create_session(
            self.workspace, agent_type=self.agent, model=self.model
        )
        self._log(f"[bold cyan]会话 {self.session.id}[/bold cyan]")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text in ("/exit", "/quit"):
            self.exit()
            return
        if text == "/help":
            self._log("[dim]/exit 退出 · /session 会话信息[/dim]")
            return
        if text == "/session":
            self._log(f"[dim]{self.session.id} · {self.session.agent_type} · {self.session.status.value}[/dim]")
            return
        self._log(f"[bold]你[/bold] {text}")
        self.client.send_message(self.session.id, text, model=self.session.model)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for ev in self.client.events(self.session.id, start_seq=self._last_seq + 1):
            self._last_seq = max(self._last_seq, ev.seq)
            for line in event_lines(ev):
                self.call_from_thread(self._log, line)
            if event_is_terminal(ev):
                break

    def _log(self, text: str) -> None:
        self.query_one(RichLog).write(text)


def run_tui(client: AppClient, args: Any) -> int:
    if App is None:  # pragma: no cover
        from rich.console import Console

        Console().print("[red]Textual 未安装：pip install textual 后可用 tui（或使用默认 REPL）。[/red]")
        return 1
    MiraTUI(
        client,
        args.workspace,
        agent=args.agent,
        model=args.model,
    ).run()
    return 0
