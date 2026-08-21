"""P0：配置层单测（分层加载 / 环境覆盖 / agent 解析）。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from mira.core.config.loader import apply_env_overrides, merge_list_by_key
from mira.core.config.schemas import AgentRole
from mira.core.config.store import ConfigStore, global_config_dir, seed_global_config


def test_defaults_load_from_repo():
    store = ConfigStore()
    rt = store.runtime()
    assert rt.session.default_agent == "main"
    assert rt.session.max_concurrent_sessions == 4
    assert rt.approval.mode.value == "ask"

    providers = store.providers()
    ids = {p.id for p in providers}
    # 默认只带本地可测 mock；真实 LLM 供应商由用户在配置中心自行添加（决策：删除预制供应商）
    assert "mock" in ids
    assert "openai-main" not in ids

    agents = store.agents()
    assert agents["main"].role == AgentRole.MAIN
    assert "dispatch_task" in agents["main"].tools.enabled
    assert agents["main"].permission.rules  # 权限规则已解析
    assert agents["investigator"].role == AgentRole.SUB
    assert agents["proto-tester"].role == AgentRole.SUB

    mcp = store.mcp_servers()


def test_vision_agent_registered():
    """视觉子 agent 从 bundled 配置注册（configs/agents/vision.toml）。"""
    agents = ConfigStore().agents()
    assert "vision" in agents
    vision = agents["vision"]
    assert vision.role == AgentRole.SUB
    assert vision.dispatch == "auto"
    assert vision.model  # 配置了视觉模型


def _write_toml(dir_: Path, name: str, content: str) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / name).write_text(content, encoding="utf-8")


def test_layered_merge(tmp_path: Path):
    default_dir = tmp_path / "default"
    project_dir = tmp_path / "project"
    user_dir = tmp_path / "user"

    _write_toml(
        default_dir,
        "mira.toml",
        "[session]\ndefault_agent = 'main'\nmax_concurrent_sessions = 2\n",
    )
    _write_toml(
        default_dir,
        "providers.toml",
        "[[providers]]\nid = 'openai-main'\ntype = 'openai'\nbase_url = 'https://default/v1'\n",
    )
    _write_toml(
        project_dir,
        "mira.toml",
        "[session]\nmax_concurrent_sessions = 5\n",
    )
    _write_toml(
        project_dir,
        "providers.toml",
        "[[providers]]\nid = 'openai-main'\nbase_url = 'https://project/v1'\n"
        "[[providers]]\nid = 'openai-local'\ntype = 'mock'\n",
    )
    _write_toml(user_dir, "mira.toml", "[session]\nmax_concurrent_sessions = 9\n")

    store = ConfigStore(
        default_dir=default_dir,
        project_dirs=[project_dir],
        user_dir=user_dir,
        include_global=False,
    )
    assert store.runtime().session.max_concurrent_sessions == 9  # 用户层覆盖

    providers = {p.id: p for p in store.providers()}
    assert providers["openai-main"].base_url == "https://project/v1"  # 同 id 合并覆盖
    assert "openai-local" in providers  # 异 id 追加


def test_env_override(tmp_path: Path):
    _write_toml(
        tmp_path / "default",
        "mira.toml",
        "[session]\nmax_concurrent_sessions = 2\n",
    )
    store = ConfigStore(default_dir=tmp_path / "default", include_global=False)
    env = {"MIRA_SESSION_MAX_CONCURRENT_SESSIONS": "7"}
    assert store.runtime().session.max_concurrent_sessions == 2
    assert (
        ConfigStore(default_dir=tmp_path / "default", env=env, include_global=False)
        .runtime()
        .session.max_concurrent_sessions
        == 7
    )


def test_env_override_bool():
    cfg = apply_env_overrides(
        {"telemetry": {"enabled": True}}, {"MIRA_TELEMETRY_ENABLED": "false"}
    )
    assert cfg["telemetry"]["enabled"] is False


def test_merge_list_by_key():
    base = [{"id": "a", "x": 1, "n": {"k": 1}}, {"id": "b", "x": 2}]
    override = [{"id": "a", "n": {"k2": 2}}, {"id": "c", "x": 3}]
    merged = merge_list_by_key(base, override)
    by_id = {i["id"]: i for i in merged}
    assert by_id["a"]["n"] == {"k": 1, "k2": 2}  # 深层合并
    assert "b" in by_id and "c" in by_id


def test_invalid_config_raises(tmp_path: Path):
    _write_toml(
        tmp_path / "default",
        "mira.toml",
        "[session]\nmax_concurrent_sessions = 'abc'\n",
    )
    store = ConfigStore(default_dir=tmp_path / "default", include_global=False)
    with pytest.raises(ValidationError):
        store.runtime()


def test_global_config_seeded_from_bundled():
    """首次运行：~/.mira-code/configs/ 从内置 configs/ 播种（conftest 已将 MIRA_HOME 指向临时目录）。"""
    gdir = seed_global_config()
    assert gdir == global_config_dir()
    assert gdir.exists()
    assert (gdir / "mira.toml").exists()
    assert (gdir / "providers.toml").exists()
    assert (gdir / "mcp.toml").exists()
    assert (gdir / "agents" / "main.toml").exists()
    assert (gdir / "agents" / "investigator.toml").exists()


def test_global_config_overrides_bundled():
    """全局配置（~/.mira-code/configs）覆盖内置默认。"""
    gdir = seed_global_config()
    (gdir / "mira.toml").write_text(
        "[session]\nmax_concurrent_sessions = 8\n", encoding="utf-8"
    )
    store = ConfigStore()
    assert store.runtime().session.max_concurrent_sessions == 8
