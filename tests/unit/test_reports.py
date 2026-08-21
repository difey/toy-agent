"""P3：子 agent 报告落盘（telemetry/reports.py）。"""

from mira.api.protocol import AgentReport, ReportStatus
from mira.telemetry import reports


def test_save_and_read_report(tmp_path):
    report = AgentReport(
        task_id="task_abc",
        agent_id="investigator",
        status=ReportStatus.SUCCEEDED,
        summary="摘要内容",
        findings=["发现一", "发现二"],
    )
    path = reports.save_report(tmp_path, "sess1", report, body="完整汇报正文")
    assert path.name == "task_abc.md"
    assert path.parent.name == "reports"
    text = path.read_text(encoding="utf-8")
    assert "task_abc" in text
    assert "investigator" in text
    assert "摘要内容" in text
    assert "完整汇报正文" in text
    assert "发现一" in text

    # 读取与列举
    assert reports.read_report(tmp_path, "sess1", "task_abc") == text
    assert reports.list_reports(tmp_path, "sess1") == ["task_abc"]


def test_report_path_layout(tmp_path):
    # 路径符合决策 #23：sessions/<session_id>/reports/<task_id>.md
    path = reports.report_path(tmp_path, "sess1", "task_x")
    assert str(path).endswith("sessions/sess1/reports/task_x.md")
