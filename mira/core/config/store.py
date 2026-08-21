"""配置存储：分层加载（内置默认 → 全局 ~/.mira-code/configs → 可选层 → env 覆盖）。

数据存储布局见 docs/implementation-plan.md「数据存储布局」。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from mira.core.config.loader import (
    apply_env_overrides,
    merge_config_dict,
    read_toml,
)
from mira.core.config.schemas import (
    AgentConfig,
    MCPServerConfig,
    ProviderConfig,
    RuntimeConfig,
    SkillConfig,
)
from mira.paths import global_config_dir


def bundled_config_dir() -> Path:
    """内置默认配置目录（随代码分发，作为种子源）：优先 MIRA_CONFIG_DIR，否则仓库 configs/。"""
    env = os.environ.get("MIRA_CONFIG_DIR")
    if env:
        return Path(env)
    # mira/core/config/store.py -> parents[3] = 仓库根
    return Path(__file__).resolve().parents[3] / "configs"


def seed_global_config(global_dir: Path | None = None) -> Path:
    """确保全局配置目录 ~/.mira-code/configs/ 存在；缺失的默认配置从内置 configs/ 复制（首次运行播种）。"""
    global_dir = global_dir or global_config_dir()
    bundled = bundled_config_dir()
    global_dir.mkdir(parents=True, exist_ok=True)
    if not bundled.exists():
        return global_dir
    for src in bundled.rglob("*"):
        rel = src.relative_to(bundled)
        dst = global_dir / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        elif not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return global_dir


class ConfigStore:
    """分层配置源。

    层顺序（后者覆盖前者）：
        bundled（内置默认）→ global（~/.mira-code/configs）→ project_dirs → user_dir → env 覆盖。
    include_global=False 时跳过 global 层（测试 / 精简场景用）。
    """

    def __init__(
        self,
        default_dir: str | Path | None = None,
        global_dir: str | Path | None = None,
        project_dirs: list[str | Path] | None = None,
        user_dir: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        *,
        include_global: bool = True,
        seed: bool = True,
    ) -> None:
        self.default_dir = Path(default_dir) if default_dir else bundled_config_dir()
        if include_global:
            if global_dir is None:
                self.global_dir = global_config_dir()
                if seed:
                    seed_global_config(self.global_dir)
            else:
                self.global_dir = Path(global_dir)
        else:
            self.global_dir = None
        self.project_dirs = [Path(p) for p in (project_dirs or [])]
        self.user_dir = Path(user_dir) if user_dir else None
        self.env = dict(env) if env is not None else None
        self._cache: dict[str, dict[str, Any]] = {}

    def _layers(self) -> list[Path]:
        layers = [self.default_dir]
        if self.global_dir is not None:
            layers.append(self.global_dir)
        layers.extend(self.project_dirs)
        if self.user_dir:
            layers.append(self.user_dir)
        return layers

    def _merged_file(self, name: str) -> dict[str, Any]:
        """按层合并单个配置文件（同 id 的 list 元素按 id 覆盖合并）。"""
        if name in self._cache:
            return self._cache[name]
        merged: dict[str, Any] = {}
        for layer in self._layers():
            path = layer / name
            if path.exists():
                merged = merge_config_dict(merged, read_toml(path))
        self._cache[name] = merged
        return merged

    def raw_config(self, name: str) -> dict[str, Any]:
        """合并后的原始配置字典（配置中心展示 / 写回用）。"""
        return dict(self._merged_file(name))

    def raw_agents(self) -> list[dict[str, Any]]:
        """跨层收集的原始 agent 字典（配置中心展示 / 写回用）。"""
        return list(self._collect_agents().values())

    def invalidate(self) -> None:
        """配置写回后失效缓存，下次读取重新合并。"""
        self._cache.clear()

    def _collect_agents(self) -> dict[str, dict[str, Any]]:
        """跨层收集 configs/agents/*.toml，按 agent id 合并。"""
        collected: dict[str, dict[str, Any]] = {}
        for layer in self._layers():
            agents_dir = layer / "agents"
            if not agents_dir.exists():
                continue
            for path in sorted(agents_dir.glob("*.toml")):
                data = read_toml(path)
                entries = data.get("agents") or ([data["agent"]] if "agent" in data else [data])
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    key = entry.get("id") or path.stem
                    if key in collected:
                        collected[key] = merge_config_dict(collected[key], entry)
                    else:
                        collected[key] = dict(entry)
        return collected

    # ── 类型化访问器 ─────────────────────────────────────────

    def runtime(self) -> RuntimeConfig:
        cfg = self._merged_file("mira.toml")
        cfg = apply_env_overrides(cfg, self.env)
        return RuntimeConfig.model_validate(cfg)

    def providers(self) -> list[ProviderConfig]:
        data = self._merged_file("providers.toml")
        return [ProviderConfig.model_validate(p) for p in data.get("providers", [])]

    def agents(self) -> dict[str, AgentConfig]:
        collected = self._collect_agents()
        return {
            key: AgentConfig.model_validate(entry)
            for key, entry in collected.items()
        }

    def mcp_servers(self) -> dict[str, MCPServerConfig]:
        data = self._merged_file("mcp.toml")
        servers = data.get("mcp", {}).get("servers", [])
        return {s.id: s for s in (MCPServerConfig.model_validate(x) for x in servers)}

    def skills(self) -> dict[str, SkillConfig]:
        data = self._merged_file("skills.toml")
        return {s.id: s for s in (SkillConfig.model_validate(x) for x in data.get("skills", []))}
