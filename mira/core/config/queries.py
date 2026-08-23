"""配置中心查询（读取侧，决策 #10）。

- get_config：把各配置分区以「原始合并字典」形式返回（含来源文件标注），供前端渲染与编辑；
- get_models：聚合可用模型（含 thinking 能力）。
- 写回侧见同层 mutation.py。
"""

from __future__ import annotations

from typing import Any

from mira.core.config.store import ConfigStore
from mira.core.providers.catalog import ModelCatalog
from mira.core.providers.router import ProviderRouter


def get_models(
    store: ConfigStore,
    provider_id: str | None = None,
    provider_type: str | None = None,
) -> dict:
    """聚合可用模型（含 thinking_efforts），模型以 {provider}/{model} 规格串标识。

    - provider_id：按已配置的 provider id 过滤；
    - provider_type：按 litellm 前缀直接查 models.dev 目录（新供应商未保存时用）。
    同时返回 models.dev 可选供应商列表（供「选择供应商 / 模型」）。
    每个模型条目附 provider（配置 id = type）与 spec（{provider}/{id}），供前端分组/选择。
    """
    catalog = ModelCatalog()
    if provider_type:
        models = catalog.models_for(provider_type)
        items = [
            {**m.model_dump(), "provider": provider_type, "spec": f"{provider_type}/{m.id}"}
            for m in models
        ]
    else:
        router = ProviderRouter.from_configs(store.providers())
        cfgs = [c for c in store.providers() if not provider_id or c.id == provider_id]
        items = []
        for cfg in cfgs:
            for m in router.available_models(cfg.id):
                items.append({**m.model_dump(), "provider": cfg.id, "spec": f"{cfg.id}/{m.id}"})
    return {"models": items, "providers": catalog.providers()}


def get_config(store: ConfigStore) -> dict[str, Any]:
    """读取全部配置分区（含来源文件标注）。"""
    return {
        "general": {"src": "configs/mira.toml", "data": store.raw_config("mira.toml")},
        "providers": {
            "src": "configs/providers.toml",
            "data": store.raw_config("providers.toml"),
        },
        "mcp": {"src": "configs/mcp.toml", "data": store.raw_config("mcp.toml")},
        "skills": {
            "src": "configs/skills/*/SKILL.md",
            "data": {"skills": store.skills_raw()},
        },
        "agents": {"src": "configs/agents/*.toml", "data": {"agents": store.raw_agents()}},
    }
