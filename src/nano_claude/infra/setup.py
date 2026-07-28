import os
import tomllib

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".nano_claude")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.toml")


def load_user_config() -> dict | None:
    if not os.path.exists(CONFIG_FILE):
        return None
    with open(CONFIG_FILE, "rb") as f:
        data = tomllib.load(f)
    return data.get("default", {})


def save_user_config(model: str, api_key: str, provider: str = "") -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    lines = ["[default]"]
    lines.append(f'model = "{model}"')
    if provider:
        lines.append(f'provider = "{provider}"')
    lines.append(f'api_key = "{api_key}"')
    with open(CONFIG_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")


def has_user_config() -> bool:
    return os.path.exists(CONFIG_FILE)
