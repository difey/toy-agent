from nano_claude.infra.config import ProviderConfig, detect_provider, resolve_config, PROVIDERS


def test_detect_provider_openai():
    assert detect_provider("gpt-4o") == "openai"
    assert detect_provider("gpt-4.1-mini") == "openai"
    assert detect_provider("o1-preview") == "openai"
    assert detect_provider("o4-mini") == "openai"


def test_detect_provider_deepseek():
    assert detect_provider("deepseek-chat") == "deepseek"
    assert detect_provider("deepseek-reasoner") == "deepseek"
    assert detect_provider("deepseek-chat-v3") == "deepseek"


def test_detect_provider_anthropic():
    assert detect_provider("claude-sonnet-4-20250514") == "anthropic"
    assert detect_provider("claude-3-5-sonnet") == "anthropic"


def test_detect_provider_unknown():
    assert detect_provider("some-unknown-model") == "openai"


def test_resolve_config_deepseek(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("NANO_CLAUDE_MODEL", raising=False)
    config = resolve_config("deepseek-chat")
    assert config.name == "deepseek"
    assert config.api_key == "sk-test"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.default_model == "deepseek-chat"


def test_resolve_config_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.delenv("NANO_CLAUDE_MODEL", raising=False)
    config = resolve_config("gpt-4o")
    assert config.name == "openai"
    assert config.api_key == "sk-openai"
    assert config.default_model == "gpt-4o"


def test_resolve_config_ollama(monkeypatch):
    monkeypatch.setenv("NANO_CLAUDE_PROVIDER", "ollama")
    config = resolve_config("llama3")
    assert config.name == "ollama"


def test_resolve_config_generic_key(monkeypatch):
    monkeypatch.setenv("NANO_CLAUDE_API_KEY", "sk-generic")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = resolve_config("deepseek-chat")
    assert config.api_key == "sk-generic"


def test_providers_registered():
    assert "openai" in PROVIDERS
    assert "deepseek" in PROVIDERS
    assert "anthropic" in PROVIDERS
    assert "ollama" in PROVIDERS
    assert PROVIDERS["deepseek"].base_url == "https://api.deepseek.com/v1"


def test_user_config_save_load(tmp_path, monkeypatch):
    import nano_claude.infra.setup as setup
    config_dir = tmp_path / ".my_code"
    config_file = config_dir / "config.toml"
    monkeypatch.setattr(setup, "CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(setup, "CONFIG_FILE", str(config_file))

    assert not setup.has_user_config()

    setup.save_user_config("deepseek-chat", "sk-test-123")
    assert setup.has_user_config()

    cfg = setup.load_user_config()
    assert cfg["model"] == "deepseek-chat"
    assert cfg["api_key"] == "sk-test-123"


def test_resolve_config_uses_user_config(tmp_path, monkeypatch):
    import nano_claude.infra.setup as setup
    config_dir = tmp_path / "my_code"
    config_file = config_dir / "config.toml"
    monkeypatch.setattr(setup, "CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(setup, "CONFIG_FILE", str(config_file))

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NANO_CLAUDE_API_KEY", raising=False)
    monkeypatch.delenv("NANO_CLAUDE_MODEL", raising=False)

    setup.save_user_config("deepseek-chat", "sk-from-file")

    config = resolve_config()
    assert config.default_model == "deepseek-chat"
    assert config.api_key == "sk-from-file"
    assert config.name == "deepseek"



