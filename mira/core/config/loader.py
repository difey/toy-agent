"""配置加载原语：TOML 读取、递归合并、环境变量覆盖。"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Mapping

# 环境变量 → 配置路径映射（点分路径，如 ("session", "max_concurrent_sessions")）
ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "MIRA_SESSION_MAX_CONCURRENT_SESSIONS": ("session", "max_concurrent_sessions"),
    "MIRA_DEFAULT_AGENT": ("session", "default_agent"),
    "MIRA_DEFAULT_MODEL": ("session", "default_model"),
    "MIRA_APPROVAL_MODE": ("approval", "mode"),
    "MIRA_TELEMETRY_ENABLED": ("telemetry", "enabled"),
    "MIRA_TELEMETRY_LOG_DIR": ("telemetry", "log_dir"),
    "MIRA_METRIC_INTERVAL_S": ("telemetry", "metric_interval_s"),
}


def read_toml(path: Path) -> dict[str, Any]:
    """读取 TOML 文件为 dict（Python 3.11+ 内置 tomllib）。"""
    with path.open("rb") as f:
        return tomllib.load(f)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并两个 dict，override 覆盖 base（仅 dict 递归，list 整体替换）。"""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def merge_list_by_key(
    base: list[Any], override: list[Any], key: str = "id"
) -> list[Any]:
    """按 key（默认 id）合并对象列表：同 id 深层合并，异 id 追加。"""
    items: dict[Any, Any] = {}
    for item in base:
        if isinstance(item, dict) and key in item:
            items[item[key]] = item
    for item in override:
        if isinstance(item, dict) and key in item:
            items[item[key]] = deep_merge(dict(items.get(item[key], {})), item)
        else:
            items[f"__anonymous_{len(items)}"] = item
    return list(items.values())


def merge_config_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """合并整份配置文件：dict 递归；list（且元素为带 id 的 dict）按 id 合并。"""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge_config_dict(out[k], v)
        elif (
            k in out
            and isinstance(out[k], list)
            and isinstance(v, list)
            and v
            and all(isinstance(i, dict) and "id" in i for i in v)
        ):
            out[k] = merge_list_by_key(out[k], v)
        else:
            out[k] = v
    return out


def _coerce(value: str, current: Any) -> Any:
    """按目标当前类型将环境变量字符串转成对应类型。"""
    if isinstance(current, bool):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return value


def apply_env_overrides(
    cfg: dict[str, Any], env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """应用环境变量覆盖（如 MIRA_SESSION_MAX_CONCURRENT_SESSIONS）。"""
    env = os.environ if env is None else env
    out = deep_merge({}, cfg)
    for env_name, path in ENV_OVERRIDES.items():
        if env_name not in env:
            continue
        node = out
        for key in path[:-1]:
            node = node.setdefault(key, {})
        current = node.get(path[-1])
        node[path[-1]] = _coerce(env[env_name], current)
    return out
