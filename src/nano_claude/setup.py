import os
import tomllib

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".nano_claude")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.toml")

PRESET_MODELS = [
    ("deepseek-v4-pro", "DeepSeek V4 Pro"),
    ("deepseek-v4-flash", "DeepSeek V4 Flash (fast, cheap)"),
    ("gpt-4o", "OpenAI GPT-4o"),
    ("gpt-4.1-mini", "OpenAI GPT-4.1 Mini (fast, cheap)"),
    ("claude-sonnet-4-20250514", "Anthropic Claude Sonnet 4"),
]


def load_user_config() -> dict | None:
    if not os.path.exists(CONFIG_FILE):
        return None
    with open(CONFIG_FILE, "rb") as f:
        data = tomllib.load(f)
    return data.get("default", {})


def save_user_config(model: str, api_key: str) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    content = f'[default]\nmodel = "{model}"\napi_key = "{api_key}"\n'
    with open(CONFIG_FILE, "w") as f:
        f.write(content)


def has_user_config() -> bool:
    return os.path.exists(CONFIG_FILE)


def run_wizard(console: Console) -> tuple[str, str]:
    console.print()
    console.print("[bold]Welcome to nanoClaude! :rocket:[/bold]")
    console.print("Let's set up your model and API key.")
    console.print()

    table = Table(title="Available Models")
    table.add_column("#", style="dim")
    table.add_column("Model")
    table.add_column("Description")
    for i, (model, desc) in enumerate(PRESET_MODELS, 1):
        table.add_row(str(i), model, desc)
    console.print(table)
    console.print()

    model = Prompt.ask(
        "Enter model name (or number)",
        default=PRESET_MODELS[0][0],
    )
    if model.isdigit():
        idx = int(model) - 1
        if 0 <= idx < len(PRESET_MODELS):
            model = PRESET_MODELS[idx][0]

    console.print()
    api_key = Prompt.ask(
        "Enter API key",
        password=True,
    )

    console.print()
    if Confirm.ask("Save configuration?", default=True):
        save_user_config(model, api_key)
        console.print(f"[dim]Saved to {CONFIG_FILE}[/dim]")
    console.print()

    return model, api_key
