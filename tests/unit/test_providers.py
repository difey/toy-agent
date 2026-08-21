"""P0：Provider 层单测（mock / litellm / catalog / router / secret 解析）。"""

import json
import types

import pytest

from mira.core.config.schemas import ProviderConfig
from mira.core.providers.base import ChatMessage, ChatRole, ModelInfo
from mira.core.providers.catalog import DEFAULT_EFFORTS, ModelCatalog
from mira.core.providers.litellm import LiteLLMProvider
from mira.core.providers.mock import MockProvider
from mira.core.providers.router import ProviderRouter, build_provider
from mira.util import split_spec


# ── litellm 打桩工具 ────────────────────────────────────────

def _lit_chunk(text="", finish_reason=None, prompt=None, completion=None, tool_calls=None):
    delta = types.SimpleNamespace(content=text or None, tool_calls=tool_calls)
    choice = types.SimpleNamespace(delta=delta, finish_reason=finish_reason)
    usage = (
        types.SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=(prompt or 0) + (completion or 0),
        )
        if prompt is not None
        else None
    )
    return types.SimpleNamespace(choices=[choice], usage=usage)


def _tool_chunk(index, id=None, name=None, arguments=None):
    return types.SimpleNamespace(
        index=index,
        id=id,
        function=types.SimpleNamespace(name=name, arguments=arguments),
    )


def test_mock_stream_yields_chunks_and_usage():
    p = MockProvider(id="mock")
    chunks = list(
        p.stream_chat(
            [ChatMessage(role=ChatRole.USER, content="你好")], model="mock-model"
        )
    )
    assert chunks
    text = "".join(c.text for c in chunks if not c.done)
    assert text
    done = [c for c in chunks if c.done]
    assert len(done) == 1
    assert done[0].finish_reason == "stop"
    assert done[0].usage is not None
    assert done[0].usage.total > 0


def test_mock_chat_aggregates():
    p = MockProvider(id="mock", reply="hello world")
    resp = p.chat([ChatMessage(role=ChatRole.USER, content="x")])
    assert resp.content == "hello world"
    assert resp.usage.output_tokens > 0


def test_chat_message_images_to_api():
    """多模态：ChatMessage.images → OpenAI 多模态 content 数组（本地路径由 litellm 转 base64）。"""
    m = ChatMessage(
        role=ChatRole.USER, content="看看这张图", images=["/tmp/a.png", "/tmp/b.jpg"]
    )
    api = m.to_api()
    assert isinstance(api["content"], list)
    assert api["content"][0] == {"type": "text", "text": "看看这张图"}
    assert api["content"][1] == {"type": "image_url", "image_url": {"url": "/tmp/a.png"}}
    assert api["content"][2] == {"type": "image_url", "image_url": {"url": "/tmp/b.jpg"}}
    # 无 images 时保持纯文本 content
    m2 = ChatMessage(role=ChatRole.USER, content="hello")
    assert m2.to_api()["content"] == "hello"


def test_chat_message_images_local_path_to_data_uri(tmp_path):
    """多模态：本地图片路径自动转 base64 data URI（OpenAI 兼容端点不支持裸路径）；http 原样透传。"""
    (tmp_path / "p.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    m = ChatMessage(role=ChatRole.USER, content="x", images=[str(tmp_path / "p.png")])
    api = m.to_api()
    u = api["content"][1]["image_url"]["url"]
    assert u.startswith("data:image/png;base64,")
    m2 = ChatMessage(role=ChatRole.USER, content="x", images=["https://a.com/b.png"])
    assert m2.to_api()["content"][1]["image_url"]["url"] == "https://a.com/b.png"


def test_build_provider_uses_plaintext_api_key():
    p = build_provider(ProviderConfig(id="x", type="openai", api_key="sk-plain"))
    assert p.api_key == "sk-plain"


def test_litellm_openai_compatible_provider_prefix():
    """非 litellm 原生 provider（如 opencode-go，OpenAI 兼容端点）回退 openai 协议；litellm 原生 provider 保持原样。"""
    oc = build_provider(
        ProviderConfig(id="opencode-go", type="opencode-go", base_url="https://opencode.ai/zen/go/v1")
    )
    assert isinstance(oc, LiteLLMProvider)
    assert oc._provider_prefix == "openai"
    assert oc._full_model("gpt-5.6-luna") == "openai/gpt-5.6-luna"
    # litellm 原生 provider 前缀不变
    ds = build_provider(ProviderConfig(id="deepseek", type="deepseek"))
    assert ds._provider_prefix == "deepseek"
    assert ds._full_model("deepseek-chat") == "deepseek/deepseek-chat"


def test_split_spec():
    # 模型串 {provider}/{model} → (provider, model)
    assert split_spec("deepseek/deepseek-chat") == ("deepseek", "deepseek-chat")
    assert split_spec("mock/mock-model") == ("mock", "mock-model")
    # 缺 provider → ValueError（模型必须以 {provider}/{model} 形式；不设默认 provider）
    with pytest.raises(ValueError, match="provider"):
        split_spec("gpt-4o")
    with pytest.raises(ValueError, match="provider"):
        split_spec(None)
    with pytest.raises(ValueError, match="provider"):
        split_spec("")
    with pytest.raises(ValueError, match="provider"):
        split_spec("/model")


def test_build_real_provider_is_litellm():
    p = build_provider(
        ProviderConfig(id="o", type="openai", base_url="http://x/v1")
    )
    assert isinstance(p, LiteLLMProvider)
    assert p.provider_type == "openai"
    assert p.base_url == "http://x/v1"


def test_litellm_stream_unifies_chunks(monkeypatch):
    import litellm

    records: list[dict] = []

    def fake_completion(**kw):
        records.append(kw)
        return [
            _lit_chunk(text="你"),
            _lit_chunk(text="好"),
            _lit_chunk(text="", finish_reason="stop", prompt=3, completion=2),
        ]

    monkeypatch.setattr(litellm, "completion", fake_completion)
    p = LiteLLMProvider(id="o", provider_type="openai", api_key="sk")
    chunks = list(p.stream_chat([ChatMessage(role=ChatRole.USER, content="hi")], model="gpt-4o"))
    assert "".join(c.text for c in chunks if not c.done) == "你好"
    done = [c for c in chunks if c.done][0]
    assert done.finish_reason == "stop"
    assert done.usage.total == 5
    assert records[0]["model"] == "openai/gpt-4o"
    assert records[0]["api_key"] == "sk"
    assert "reasoning_effort" not in records[0]


def test_litellm_passes_reasoning_effort(monkeypatch):
    import litellm

    records: list[dict] = []

    def fake_completion(**kw):
        records.append(kw)
        return [_lit_chunk(text="", finish_reason="stop", prompt=1, completion=1)]

    monkeypatch.setattr(litellm, "completion", fake_completion)
    p = LiteLLMProvider(id="o", provider_type="openai")
    msgs = [ChatMessage(role=ChatRole.USER, content="x")]
    list(p.stream_chat(msgs, model="o3", effort="high"))
    assert records[0].get("reasoning_effort") == "high"
    list(p.stream_chat(msgs, model="o3", effort="off"))
    assert "reasoning_effort" not in records[1]  # off → 不透传


def test_litellm_drops_unsupported_params(monkeypatch):
    """stream_chat 始终传 drop_params=True：丢弃 provider 不支持的参数（如 openai 协议的 reasoning_effort）。"""
    import litellm

    records: list[dict] = []

    def fake_completion(**kw):
        records.append(kw)
        return [_lit_chunk(text="", finish_reason="stop", prompt=1, completion=1)]

    monkeypatch.setattr(litellm, "completion", fake_completion)
    p = LiteLLMProvider(id="oc", provider_type="opencode-go", base_url="https://opencode.ai/zen/go/v1")
    list(p.stream_chat([ChatMessage(role=ChatRole.USER, content="x")], model="qwen3.7-plus", effort="high"))
    assert records[0]["drop_params"] is True
    # reasoning_effort 仍传入，但 drop_params=True 让 litellm 对不支持的模型丢弃而不是抛 UnsupportedParamsError
    assert records[0]["reasoning_effort"] == "high"


def test_litellm_tool_calls_accumulate(monkeypatch):
    import litellm

    def fake_completion(**kw):
        return [
            _lit_chunk(tool_calls=[_tool_chunk(0, id="c1", name="shell", arguments='{"cmd":')]),
            _lit_chunk(tool_calls=[_tool_chunk(0, arguments=' "echo ok"}')]),
            _lit_chunk(text="", finish_reason="tool_calls", prompt=5, completion=1),
        ]

    monkeypatch.setattr(litellm, "completion", fake_completion)
    p = LiteLLMProvider(id="o", provider_type="openai")
    chunks = list(p.stream_chat([ChatMessage(role=ChatRole.USER, content="x")]))
    done = [c for c in chunks if c.done][0]
    assert done.finish_reason == "tool_calls"
    assert done.tool_calls
    assert done.tool_calls[0]["function"]["arguments"] == '{"cmd": "echo ok"}'


def test_catalog_loads_snapshot_and_efforts(tmp_path):
    snap = tmp_path / "models.json"
    snap.write_text(
        json.dumps(
            {
                "openai": {
                    "name": "OpenAI",
                    "models": {
                        "gpt-4o": {"name": "GPT-4o", "reasoning": False},
                        "o3": {"name": "o3", "reasoning": True},
                        "o4": {"name": "o4", "reasoning": {"effort": ["low", "high"]}},
                    },
                },
                "google": {
                    "name": "Google",
                    "models": {"gemini-x": {"name": "Gemini X", "reasoning": True}},
                },
            },
            ensure_ascii=False,
        )
    )
    cat = ModelCatalog(snap)
    assert any(p["id"] == "openai" and p["name"] == "OpenAI" for p in cat.providers())
    models = {m.id: m for m in cat.models_for("openai")}
    assert models["gpt-4o"].supports_thinking is False
    assert models["gpt-4o"].thinking_efforts == []
    assert models["o3"].supports_thinking is True
    assert models["o3"].thinking_efforts == list(DEFAULT_EFFORTS)
    assert models["o4"].thinking_efforts == ["low", "high"]  # dict reasoning → 直接消费 effort
    assert cat.resolve_provider("gemini") == "google"  # 别名映射
    assert cat.models_for("no-such") == []


def test_models_dev_refresh_async_downloads_to_mira_home_once(monkeypatch):
    """启动后台刷新：下载最新快照写回 mira-code，且同一进程只启动一次。"""
    import io
    import threading
    import time

    import mira.core.providers.catalog as cat_mod
    from mira import paths as mira_paths

    # 重置进程级去重标志，避免受其他测试影响
    monkeypatch.setattr(cat_mod, "_refresh_started", False)

    calls: list = []
    payload = io.BytesIO(json.dumps({"acme": {"name": "Acme"}}).encode("utf-8"))

    def fake_urlopen(req, timeout=60):
        calls.append(req)
        return payload

    monkeypatch.setattr(cat_mod.urllib.request, "urlopen", fake_urlopen)

    c1, c2 = ModelCatalog(), ModelCatalog()
    c1.refresh_async()
    c2.refresh_async()  # 进程级去重：不应再启动线程

    target = mira_paths.mira_home() / "models-dev.json"
    deadline = time.time() + 5
    data = {}
    while time.time() < deadline:
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if "acme" in data:
                break
        except FileNotFoundError:
            pass
        time.sleep(0.05)
    assert data.get("acme", {}).get("name") == "Acme"  # 快照已写回 mira-code
    assert len(calls) == 1  # 只下载一次（去重生效）


def test_app_client_starts_background_refresh_on_startup(monkeypatch):
    """AppClient 每次创建（启动入口）默认触发后台刷新；MIRA_MODELS_DEV_REFRESH=0 关闭。"""
    import mira.core.providers.catalog as cat_mod
    from mira.api.client import AppClient

    monkeypatch.delenv("MIRA_MODELS_DEV_REFRESH", raising=False)  # 恢复默认（启用）
    started: list = []
    monkeypatch.setattr(
        cat_mod.ModelCatalog, "refresh_async", lambda self: started.append(True)
    )
    AppClient()
    assert started == [True]

    monkeypatch.setenv("MIRA_MODELS_DEV_REFRESH", "0")  # 关闭
    AppClient()
    assert started == [True]  # 未再触发


def test_build_mock_provider():
    cfg = ProviderConfig(id="mock", type="mock")
    p = build_provider(cfg)
    assert p.id == "mock"
    assert isinstance(p, MockProvider)


def test_build_unknown_type_builds_litellm_without_models():
    # litellm 下任意非 mock type 都作为 litellm provider 前缀；catalog 无此供应商 → 空模型列表（无兜底默认模型）
    p = build_provider(ProviderConfig(id="x", type="no-such-type"))
    assert isinstance(p, LiteLLMProvider)
    assert p.provider_type == "no-such-type"
    assert p.list_models() == []


def test_router_routes_and_retries_fail():
    good = MockProvider(id="good", reply="ok")
    router = ProviderRouter([good])
    resp = router.chat("good", [ChatMessage(role=ChatRole.USER, content="hi")])
    assert "ok" in resp.content

    class Flaky(MockProvider):
        def __init__(self):
            super().__init__(id="flaky", reply="never")
            self.calls = 0

        def stream_chat(self, messages, **kw):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("boom")
            return super().stream_chat(messages, **kw)

    flaky = Flaky()
    router2 = ProviderRouter([flaky])
    resp2 = router2.chat("flaky", [ChatMessage(role=ChatRole.USER, content="hi")])
    assert resp2.content == "never"
    assert flaky.calls == 3  # 重试成功


def test_router_gives_up_after_retries():
    class AlwaysFail(MockProvider):
        def stream_chat(self, messages, **kw):
            raise RuntimeError("down")

    router = ProviderRouter([AlwaysFail(id="bad")])
    with pytest.raises(RuntimeError):
        list(router.stream_chat("bad", [ChatMessage(role=ChatRole.USER, content="hi")], max_retries=1))
