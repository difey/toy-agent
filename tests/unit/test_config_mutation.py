"""P5 前：配置中心读写（决策 #10）—— 逻辑位于 core/config（queries / mutation）。"""

import pytest

from mira.core.config import mutation, queries
from mira.core.config.store import ConfigStore


def _store() -> ConfigStore:
    # conftest 已把 MIRA_HOME 隔离到 tmp，global_dir = <tmp>/.mira-code/configs（已播种）
    return ConfigStore()


def test_get_config_returns_all_sections():
    cfg = queries.get_config(_store())
    assert set(cfg) == {"general", "providers", "mcp", "skills", "agents"}
    assert cfg["general"]["src"] == "configs/mira.toml"
    assert cfg["general"]["data"]["session"]["default_agent"] == "main"
    assert cfg["providers"]["data"]["providers"]
    assert cfg["agents"]["data"]["agents"]
    assert cfg["mcp"]["data"]["mcp"]["servers"]
    assert cfg["skills"]["data"]["skills"]


def test_update_general_writes_back_and_reloads():
    store = _store()
    before = queries.get_config(store)["general"]["data"]
    data = dict(before)
    data["session"] = dict(before["session"], max_concurrent_sessions=7)
    data["approval"] = dict(before["approval"], mode="auto")

    mutation.update_config(store, "general", data)

    # 缓存失效后重新读取生效
    after = queries.get_config(store)["general"]["data"]
    assert after["session"]["max_concurrent_sessions"] == 7
    assert after["approval"]["mode"] == "auto"
    # 写回全局配置层文件
    f = store.global_dir / "mira.toml"
    assert f.exists()
    assert "max_concurrent_sessions = 7" in f.read_text(encoding="utf-8")


def test_update_providers_and_agents(tmp_path):
    store = _store()
    # providers 写回
    cfg = queries.get_config(store)
    providers = cfg["providers"]["data"]["providers"]
    new_p = dict(providers[0], max_retries=9)
    mutation.update_config(store, "providers", {"providers": [new_p]})
    after = queries.get_config(store)["providers"]["data"]["providers"]
    assert after[0]["max_retries"] == 9

    # agents 整组重写为独立文件
    agents = cfg["agents"]["data"]["agents"]
    new_a = dict(agents[0], name="改名后的主 Agent")
    mutation.update_config(store, "agents", {"agents": [new_a]})
    files = sorted(p.name for p in (store.global_dir / "agents").glob("*.toml"))
    assert files == [f"{new_a['id']}.toml"]
    after_agents = queries.get_config(store)["agents"]["data"]["agents"]
    assert after_agents[0]["name"] == "改名后的主 Agent"


def test_update_invalid_data_raises():
    store = _store()
    with pytest.raises(ValueError):
        mutation.update_config(store, "general", {"session": {"max_concurrent_sessions": "x"}})
    with pytest.raises(ValueError):
        mutation.update_config(store, "providers", {"providers": [{"id": 5}]})


def test_update_providers_duplicate_id_raises():
    """决策：provider 显示名（id）全局唯一——重复 id 写回被拒绝。"""
    store = _store()
    providers = queries.get_config(store)["providers"]["data"]["providers"]
    dup = [dict(providers[0]), dict(providers[0])]
    with pytest.raises(ValueError, match="重复"):
        mutation.update_config(store, "providers", {"providers": dup})


def test_update_providers_type_duplicate_raises():
    """决策：每种 provider 只允许一个配置（type 唯一）。"""
    store = _store()
    with pytest.raises(ValueError, match="只允许一个配置"):
        mutation.update_config(
            store, "providers", {"providers": [{"id": "openai", "type": "openai"}, {"id": "openai-2", "type": "openai"}]}
        )


def test_update_providers_id_must_equal_type():
    """决策：id 即 type（模型串 {provider}/{model} 的 provider = type）。"""
    store = _store()
    with pytest.raises(ValueError, match="id 即 type"):
        mutation.update_config(
            store, "providers", {"providers": [{"id": "my-ds", "type": "deepseek"}]}
        )


def test_update_unknown_section_raises():
    with pytest.raises(ValueError):
        mutation.update_config(_store(), "nope", {})


def test_get_models_aggregates_with_thinking():
    res = queries.get_models(_store())
    ids = {m["id"] for m in res["models"]}
    assert ids == {"mock-model"}
    mock_model = next(m for m in res["models"] if m["id"] == "mock-model")
    assert mock_model["supports_thinking"] is False
    assert mock_model["thinking_efforts"] == []
    # models.dev 供应商目录（供「选择供应商 / 模型」）
    assert res["providers"]
    assert any(p["id"] == "openai" for p in res["providers"])


def test_get_models_filtered_by_provider():
    res = queries.get_models(_store(), provider_id="mock")
    ids = {m["id"] for m in res["models"]}
    assert "mock-model" in ids
    assert ids == {"mock-model"}


def test_provider_plaintext_api_key_writeback():
    store = _store()
    cfg = queries.get_config(store)
    providers = cfg["providers"]["data"]["providers"]
    new_p = dict(providers[0], api_key="sk-plaintext-demo")
    mutation.update_config(store, "providers", {"providers": [new_p]})
    after = queries.get_config(store)["providers"]["data"]["providers"][0]
    assert after["api_key"] == "sk-plaintext-demo"
    f = store.global_dir / "providers.toml"
    assert "sk-plaintext-demo" in f.read_text(encoding="utf-8")
