"""P3：子 agent 完整报告落盘（决策 #7 / #9）。

- 完整报告存 `sessions/<session_id>/reports/<task_id>.md`；
- 主 agent 只回填摘要；需要细节时用通用 `file_read` 按路径读取完整报告（不新增专用工具）；
- 汇报格式不强制（决策 #9），重点是信息充分性。
"""

from __future__ import annotations

from pathlib import Path

from mira import paths
from mira.api.protocol import AgentReport


def save_report(
    workspace: str | Path,
    session_id: str,
    report: AgentReport,
    body: str | None = None,
) -> Path:
    """把 AgentReport 落盘为 markdown，返回文件路径。

    body 为子 agent 的完整汇报文本（默认取 report.summary）。
    """
    body = body if body is not None else report.summary
    path = report_path(workspace, session_id, report.task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(report, body), encoding="utf-8")
    return path


def report_path(workspace: str | Path, session_id: str, task_id: str) -> Path:
    """完整报告的固定路径（决策 #7：按 task_id 命名）。"""
    return paths.session_reports_dir(workspace, session_id) / f"{task_id}.md"


def read_report(workspace: str | Path, session_id: str, task_id: str) -> str:
    """读取完整报告文本（不存在时返回空串）。"""
    path = report_path(workspace, session_id, task_id)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def list_reports(workspace: str | Path, session_id: str) -> list[str]:
    """列出某 session 已落盘的报告（task_id 列表，按名排序）。"""
    d = paths.session_reports_dir(workspace, session_id)
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.md"))


def _render(report: AgentReport, body: str) -> str:
    lines = [
        f"# 子 Agent 汇报 — {report.task_id}",
        "",
        f"- agent: `{report.agent_id}`",
        f"- 状态: {report.status.value}",
        f"- 摘要: {report.summary or '（无）'}",
        "",
        "## 汇报内容",
        body.strip() or "（无内容）",
    ]
    if report.findings:
        lines += ["", "## 发现"] + [f"- {f}" for f in report.findings]
    if report.recommendation:
        lines += ["", "## 建议", report.recommendation]
    if report.risks:
        lines += ["", "## 风险"] + [f"- {r}" for r in report.risks]
    if report.artifacts:
        lines += ["", "## 产物"] + [f"- {a}" for a in report.artifacts]
    return "\n".join(lines) + "\n"
