"""P0：统一契约数据模型单测。"""

from mira.api.protocol import (
    AgentReport,
    Message,
    MessageRole,
    ReportStatus,
    Session,
    SessionStatus,
    TaskSpec,
    ToolCall,
    ToolCallStatus,
)


def test_session_defaults():
    s = Session()
    assert s.id  # id = hashcode（短哈希）
    assert s.id.isalnum()
    assert s.status == SessionStatus.IDLE
    assert s.agent_type == "main"
    assert s.created_at  # 非空时间戳


def test_session_override():
    s = Session(workspace="write_test", model="mock/mock-model")
    assert s.workspace == "write_test"
    assert s.model == "mock/mock-model"


def test_message_fields():
    m = Message(session_id="sess_1", role=MessageRole.USER, content="hi", seq=3)
    assert m.id.startswith("msg_")
    assert m.role == MessageRole.USER
    assert m.seq == 3


def test_tool_call_defaults():
    tc = ToolCall(name="shell", arguments={"cmd": "ls"})
    assert tc.status == ToolCallStatus.PENDING
    assert tc.duration_ms is None
    assert tc.result is None


def test_task_spec_defaults():
    spec = TaskSpec(target_agent="investigator", goal="调查 X")
    assert spec.task_id.startswith("task_")
    assert spec.context == []
    assert spec.expected_output is None


def test_agent_report():
    report = AgentReport(
        task_id="task_1",
        agent_id="investigator",
        summary="现状已查明",
        findings=["a", "b"],
        recommendation="建议 A",
        risks=["风险1"],
        report_path="telemetry/reports/task_1.md",
    )
    assert report.status == ReportStatus.SUCCEEDED
    assert report.report_path is not None
    assert report.findings == ["a", "b"]
