import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

FINITY_DIR = Path.home() / ".finityagent"
CONFIG_PATH = FINITY_DIR / "config.toml"

PRESETS = {
    "opencode-go": {
        "label": "OpenCode Go",
        "base_url": "https://opencode.ai/zen/go/v1",
        "key_env": "OPENCODE_API_KEY",
        "default_model": "kimi-k3",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4.1",
    },
    "custom": {
        "label": "Custom",
        "base_url": "",
        "key_env": "",
        "default_model": "",
    },
}


@dataclass
class Config:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    preset: str = "custom"
    extra: dict = field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


def load_config() -> Config:
    data = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
    cfg = Config(
        base_url=data.get("base_url", ""),
        model=data.get("model", ""),
        preset=data.get("preset", "custom"),
        extra={k: v for k, v in data.items()
               if k not in ("base_url", "api_key", "model", "preset")},
    )
    cfg.api_key = os.environ.get("FINITYAGENT_API_KEY", data.get("api_key", ""))
    return cfg


def save_config(cfg: Config) -> None:
    FINITY_DIR.mkdir(parents=True, exist_ok=True)
    doc = {"base_url": cfg.base_url, "api_key": cfg.api_key,
           "model": cfg.model, "preset": cfg.preset}
    doc.update(cfg.extra)
    lines = []
    for key, value in doc.items():
        if isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key} = {value}")
    CONFIG_PATH.write_text("\n".join(lines) + "\n")
