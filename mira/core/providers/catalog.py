"""models.dev 模型目录（决策 #24）：可选供应商 / 每供应商模型 / thinking 能力。

数据源：https://models.dev/api.json 快照。
- 默认内置快照 configs/models-dev.json（随代码分发，离线 / 测试默认源）；
- 可用 MIRA_MODELS_DEV_PATH 指定文件；或用 refresh() 下载缓存到 ~/.mira-code/models-dev.json 覆盖。
- reasoning 字段：当前 models.dev 为布尔（是否支持思考）；若未来出现 dict（含 effort），
  直接消费其 effort 作为 thinking_efforts；布尔 true 时用默认 effort 阶梯。
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from mira import paths
from mira.core.providers.base import ModelInfo

MODELS_DEV_URL = "https://models.dev/api.json"
# reasoning=true 但未提供 effort 枚举时的默认阶梯（models.dev 当前不提供枚举）
DEFAULT_EFFORTS = ("low", "medium", "high")
# models.dev provider id 与 litellm provider 前缀的别名映射（部分不一致，如 gemini→google）
PROVIDER_ALIASES = {
    "gemini": "google",
    "azure": "azure",
    "bedrock": "amazon",
    "amazon": "amazon",
}

# 模块级缓存（按路径）：避免每次查询重复解析 ~3.6MB 快照
_CACHE: dict[str, dict[str, Any]] = {}


def _load_json(path: Path) -> dict[str, Any]:
    key = str(path)
    if key not in _CACHE:
        try:
            _CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001  （快照缺失 / 损坏 → 空目录）
            _CACHE[key] = {}
    return _CACHE[key]


def bundled_snapshot_path() -> Path:
    """内置 models.dev 快照（mira/core/providers/catalog.py -> parents[3] = 仓库根）。"""
    return Path(__file__).resolve().parents[3] / "configs" / "models-dev.json"


class ModelCatalog:
    """models.dev 数据目录（只读查询 + refresh 刷新）。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else self._default_path()
        self._data: dict[str, Any] = {}
        self._load()

    @staticmethod
    def _default_path() -> Path:
        env = os.environ.get("MIRA_MODELS_DEV_PATH")
        if env:
            return Path(env)
        cached = paths.mira_home() / "models-dev.json"
        if cached.exists():
            return cached
        return bundled_snapshot_path()

    def _load(self) -> None:
        self._data = _load_json(self.path)

    def refresh(self) -> Path:
        """从 models.dev 下载最新快照到 ~/.mira-code/models-dev.json。"""
        target = paths.mira_home() / "models-dev.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(MODELS_DEV_URL, headers={"User-Agent": "mira/0.1"})
        data = json.load(urllib.request.urlopen(req, timeout=60))
        target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self._data = data
        self.path = target
        _CACHE[str(target)] = data  # 更新缓存
        return target

    # ── 查询 ───────────────────────────────────────────────

    def provider_ids(self) -> list[str]:
        return sorted(self._data)

    def providers(self) -> list[dict]:
        """可选供应商列表：[{id, name, base_url, env_key}]（供配置中心自动填充）。

        base_url 来自 models.dev 的 api 字段（仅部分供应商有；无则留空 → litellm 用默认端点）；
        env_key 来自 env 字段（如 OPENAI_API_KEY），供参考（已取消 env 引用设计）。
        """
        out = []
        for pid, p in self._data.items():
            env = p.get("env") or []
            out.append(
                {
                    "id": pid,
                    "name": p.get("name") or pid,
                    "base_url": p.get("api") or "",
                    "env_key": env[0] if env else "",
                }
            )
        out.sort(key=lambda x: (x["name"].lower(), x["id"]))
        return out

    def resolve_provider(self, provider_type: str) -> str | None:
        """把 litellm provider 前缀解析为 models.dev provider id（含别名）。"""
        if provider_type in self._data:
            return provider_type
        alias = PROVIDER_ALIASES.get(provider_type)
        if alias and alias in self._data:
            return alias
        return None

    @staticmethod
    def _reasoning_to(reasoning: Any) -> tuple[bool, list[str]]:
        """models.dev reasoning → (supports_thinking, thinking_efforts)。"""
        if isinstance(reasoning, dict):
            efforts = reasoning.get("effort") or list(DEFAULT_EFFORTS)
            return True, [str(e) for e in efforts]
        if reasoning is True:
            return True, list(DEFAULT_EFFORTS)
        return False, []

    def models_for(self, provider_type: str) -> list[ModelInfo]:
        """某供应商（litellm 前缀）的模型目录（含 thinking_efforts）。"""
        pid = self.resolve_provider(provider_type)
        if not pid:
            return []
        models = (self._data.get(pid) or {}).get("models") or {}
        out: list[ModelInfo] = []
        for mid, m in models.items():
            supports, efforts = self._reasoning_to(m.get("reasoning"))
            out.append(
                ModelInfo(
                    id=mid,
                    name=m.get("name") or mid,
                    supports_thinking=supports,
                    thinking_efforts=efforts,
                )
            )
        out.sort(key=lambda x: x.id)
        return out
