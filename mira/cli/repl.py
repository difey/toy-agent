"""REPL：交互式单会话 CLI，渲染事件流（流式 token / 工具卡片 / 状态）。

消费同一份 EventStream，与未来 Web 拿到的事件同构。
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console

from mira import paths
from mira.api.client import AppClient
from mira.telemetry.events import Event, EventType

BANNER = """[bold]Mira Code[/bold] — Coding Agent 平台（P1 · 核心循环 + CLI）
输入消息开始对话；/help 查看命令。"""


def event_is_terminal(ev: Event) -> bool:
    """一个回合是否结束：会话进入 idle / failed。"""
    return ev.type == EventType.SESSION_STATUS and ev.payload.get("status") in ("idle", "failed")


def event_lines(ev: Event) -> list[str]:
    """把事件转成一组（带 markdown 标记的）渲染行，供 REPL / Textual 复用。"""
    t = ev.type
    if t == EventType.USER_MESSAGE:
        return [f"[bold cyan]你[/bold cyan] {ev.payload.get('content', '')}"]
    if t == EventType.LLM_STREAM_CHUNK:
        return [ev.payload.get("text", "")]
    if t == EventType.AGENT_MESSAGE:
        return [f"\n[bold]main[/bold] {ev.payload.get('content', '')}"]
    if t == EventType.TOOL_CALL:
        args = ev.payload.get("arguments")
        return [f"[dim]⚙ {ev.payload.get('name')}[/dim] {json.dumps(args, ensure_ascii=False)}"]
    if t in (EventType.TOOL_RESULT, EventType.TOOL_ERROR):
        ok = t == EventType.TOOL_RESULT
        mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
        name = ev.payload.get("name")
        dur = ev.payload.get("duration_ms")
        out = (ev.payload.get("result") or ev.payload.get("error") or "").strip()
        lines = [f"  {mark} [dim]{name}[/dim]（{dur}ms）"]
        if out:
            lines.append(f"[dim]  {out[:600]}[/dim]")
        return lines
    if t == EventType.APPROVAL_REQUESTED:
        return [f"[yellow]⏸ 审批请求：{ev.payload.get('tool')}[/yellow]"]
    if t == EventType.APPROVAL_RESOLVED:
        return [f"[yellow]  审批：{ev.payload.get('decision')}（自动放行）[/yellow]"]
    if t == EventType.QUESTION_REQUESTED:
        p = ev.payload
        prog = ""
        if p.get("total") and int(p.get("total", 0) or 0) > 1:
            prog = f"（{p.get('index')}/{p.get('total')}）"
        lines = [f"[yellow]Agent 需要确认{prog}：{p.get('question')}[/yellow]"]
        for i, o in enumerate(p.get("options") or [], 1):
            lines.append(f"[cyan]  {i}. {o}[/cyan]")
        return lines
    if t == EventType.QUESTION_ANSWERED:
        return [f"[yellow]  回答：{ev.payload.get('answer')}[/yellow]"]
    if t == EventType.SESSION_STATUS:
        return [f"[dim]· 会话状态: {ev.payload.get('status')}[/dim]"]
    if t == EventType.ERROR_RAISED:
        return [f"[red]错误: {ev.payload.get('message')}[/red]"]
    return []


def render_event(console: Console, ev: Event) -> bool:
    """渲染单个事件；返回是否应结束本次回合。"""
    for line in event_lines(ev):
        console.print(line, end="" if ev.type == EventType.LLM_STREAM_CHUNK else "\n")
    return event_is_terminal(ev)


def handle_question(console: Console, client: AppClient, session_id: str, payload: dict) -> None:
    """渲染提问并读取用户作答：输入选项编号或自由输入回答（回车=跳过）。"""
    opts = payload.get("options") or []
    console.print("[dim]输入选项编号或直接输入回答（回车=跳过）[/dim]")
    try:
        ans = input("  回答> ").strip()
    except (EOFError, KeyboardInterrupt):
        ans = ""
    if not ans:
        ans = "（用户未回答）"
    elif opts:
        try:
            idx = int(ans)
            if 1 <= idx <= len(opts):
                ans = opts[idx - 1]
        except ValueError:
            pass
    try:
        client.answer_question(session_id, payload["request_id"], ans)
    except KeyError:
        console.print("[red]提问已失效 / 会话不存在[/red]")


def run_once(client: AppClient, args: Any) -> int:
    """单次执行：发送一条消息，渲染事件直到回合结束。"""
    console = Console()
    session = client.create_session(
        args.workspace, agent_type=args.agent, model=args.model
    )
    if not args.quiet:
        console.print(f"[dim]会话 {session.id} · {session.model}[/dim]")
    client.send_message(session.id, args.prompt, model=session.model)
    reply: str | None = None
    for ev in client.events(session.id):
        if ev.type == EventType.QUESTION_REQUESTED:
            render_event(console, ev)
            handle_question(console, client, session.id, ev.payload)
            continue
        if args.quiet:
            if ev.type == EventType.AGENT_MESSAGE:
                reply = ev.payload.get("content")
            elif ev.type == EventType.ERROR_RAISED:
                console.print(f"[red]{ev.payload.get('message')}[/red]")
        else:
            render_event(console, ev)
        if event_is_terminal(ev):
            break
    if args.quiet and reply:
        console.print(reply)
    return 0


def run_repl(client: AppClient, args: Any) -> int:
    console = Console()
    console.print(BANNER)
    session = client.create_session(
        args.workspace, agent_type=args.agent, model=args.model
    )
    console.print(
        f"[dim]会话 {session.id} · workspace {paths.workspace_id(args.workspace)} · "
        f"agent {session.agent_type} · {session.model}[/dim]"
    )
    last_seq = 0
    while True:
        try:
            raw = input("mira> ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n再见 👋")
            break
        text = raw.strip()
        if not text:
            continue
        if text in ("/exit", "/quit"):
            break
        if text == "/help":
            console.print("[dim]/help 帮助 · /session 会话信息 · /exit 退出[/dim]")
            continue
        if text == "/session":
            s = client.get_session(session.id)
            console.print(
                f"[dim]{s.id} · {s.agent_type} · {s.provider} / {s.model} · {s.status.value}[/dim]"
            )
            continue
        if text.startswith("/"):
            console.print(f"[dim]未知命令 {text}（/help 查看）[/dim]")
            continue

        client.send_message(session.id, text, model=session.model)
        for ev in client.events(session.id, start_seq=last_seq + 1):
            last_seq = max(last_seq, ev.seq)
            if ev.type == EventType.QUESTION_REQUESTED:
                render_event(console, ev)
                handle_question(console, client, session.id, ev.payload)
                continue
            if render_event(console, ev):
                break
    return 0
