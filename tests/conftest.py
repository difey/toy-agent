"""测试隔离：将数据根目录 MIRA_HOME 重定向到临时目录，避免触碰真实 ~/.mira-code/。"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_mira_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRA_HOME", str(tmp_path / ".mira-code"))
    yield


@pytest.fixture(autouse=True)
def _no_mcp_servers(monkeypatch):
    """P3：默认关闭真实 MCP 连接（避免测试触发 github http / npx 子进程）。

    MCP 专项测试（test_mcp.py）通过模块级 fixture 删除该 env 以恢复真实连接。
    """
    monkeypatch.setenv("MIRA_MCP_DISABLED", "1")
    yield


@pytest.fixture(autouse=True)
def _no_models_dev_background_refresh(monkeypatch):
    """关闭 AppClient 启动时的 models.dev 后台刷新（避免测试发起真实网络请求）。

    专项测试通过 monkeypatch.delenv 恢复默认以验证启动刷新逻辑。
    """
    monkeypatch.setenv("MIRA_MODELS_DEV_REFRESH", "0")
    yield
