"""配置中心变更（写回侧，决策 #10）：校验 → TOML 落盘 → 缓存失效。

- 写回：pydantic 校验 → tomli-w 序列化 → 写到全局配置目录（~/.mira-code/configs/，
  可编辑层）→ 失效缓存（ConfigStore.invalidate）+ SessionManager 热重载。
- API key 只显示引用（env:MIRA_*），不落盘明文（决策 #8a）。
- 读取侧见同层 queries.py。
"""

from __future__ import annotations

import shutil
from typing import Any

import tomli_w

from mira.core.config.queries import get_config
from mira.core.config.schemas import (
    AgentConfig,
    MCPServerConfig,
    ProviderConfig,
    RuntimeConfig,
    SkillConfig,
)
from mira.core.config.store import ConfigStore

_SECTIONS = ("general", "providers", "mcp", "skills", "agents")


def update_config(store: ConfigStore, section: str, data: dict[str, Any]) -> dict[str, Any]:
    """校验并写回指定分区；返回更新后的全部配置。"""
    if section not in _SECTIONS:
        raise ValueError(f"未知配置分区: {section!r}（可用: {', '.join(_SECTIONS)}）")
    _UPDATERS[section](store, data)
    store.invalidate()
    return get_config(store)


# ── 各分区写回 ──────────────────────────────────────────────


def _write_file(store: ConfigStore, rel: str, data: dict[str, Any]) -> None:
    path = store.global_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(data), encoding="utf-8")


def _update_general(store: ConfigStore, data: dict[str, Any]) -> None:
    RuntimeConfig.model_validate(data)  # pydantic 校验，失败抛 ValidationError
    _write_file(store, "mira.toml", data)


def _update_providers(store: ConfigStore, data: dict[str, Any]) -> None:
    items = data.get("providers", [])
    for it in items:
        ProviderConfig.model_validate(it)
    # 决策：每种 provider 只允许一个配置，id 即 type（模型串 {provider}/{model} 的 provider = type）
    types = [str(it.get("type", "")).strip() for it in items]
    if any(not t for t in types):
        raise ValueError("provider type 不能为空")
    if len(types) != len(set(types)):
        raise ValueError("每种 provider 只允许一个配置（type 重复）")
    for it in items:
        if str(it.get("id", "")).strip() != str(it.get("type", "")).strip():
            raise ValueError("provider id 需等于 type（id 即 type）")
    _write_file(store, "providers.toml", {"providers": items})


def _update_mcp(store: ConfigStore, data: dict[str, Any]) -> None:
    servers = data.get("mcp", {}).get("servers", [])
    for s in servers:
        MCPServerConfig.model_validate(s)
    _write_file(store, "mcp.toml", {"mcp": {"servers": servers}})


def _update_skills(store: ConfigStore, data: dict[str, Any]) -> None:
    items = data.get("skills", [])
    for it in items:
        SkillConfig.model_validate(it)
    # 整组重写为标准 SKILL.md 目录（configs/skills/<id>/SKILL.md），可直接复制生效
    skills_dir = store.global_dir / "skills"
    if skills_dir.exists():
        for child in skills_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    for it in items:
        sid = it.get("id") or "skill"
        d = skills_dir / sid
        d.mkdir(parents=True, exist_ok=True)
        fm = [f"name: {sid}", f"description: {it.get('description', '')}", "type: prompt"]
        tools = it.get("tools") or []
        if tools:
            fm.append("tools:")
            fm.extend(f"- {t}" for t in tools)
        text = "---\n" + "\n".join(fm) + "\n---\n\n" + (it.get("prompt") or "")
        (d / "SKILL.md").write_text(text, encoding="utf-8")


def _update_agents(store: ConfigStore, data: dict[str, Any]) -> None:
    items = data.get("agents", [])
    for it in items:
        AgentConfig.model_validate(it)
    agents_dir = store.global_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for old in agents_dir.glob("*.toml"):  # 整组重写，保持文件与 id 一一对应
        old.unlink()
    for it in items:
        aid = it.get("id") or "agent"
        (agents_dir / f"{aid}.toml").write_text(
            tomli_w.dumps({"agents": [it]}), encoding="utf-8"
        )


_UPDATERS = {
    "general": _update_general,
    "providers": _update_providers,
    "mcp": _update_mcp,
    "skills": _update_skills,
    "agents": _update_agents,
}
