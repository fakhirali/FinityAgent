import os
import tomllib

import pytest

from finityagent import config as cfg_mod
from finityagent.config import Config, load_config, save_config


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_mod, "FINITY_DIR", tmp_path / ".finityagent")
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / ".finityagent" / "config.toml")
    monkeypatch.delenv("FINITYAGENT_API_KEY", raising=False)
    return tmp_path


def test_load_missing_returns_default(config_home):
    cfg = load_config()
    assert cfg.base_url == "" and not cfg.is_configured


def test_save_and_load_roundtrip(config_home):
    cfg = Config(base_url="https://opencode.ai/zen/go/v1",
                 api_key="sk-test", model="kimi-k3", preset="opencode-go")
    save_config(cfg)
    loaded = load_config()
    assert loaded.base_url == cfg.base_url
    assert loaded.api_key == "sk-test"
    assert loaded.model == "kimi-k3"
    assert loaded.preset == "opencode-go"
    assert loaded.is_configured


def test_env_var_overrides_key(config_home, monkeypatch):
    cfg = Config(base_url="u", api_key="file-key", model="m")
    save_config(cfg)
    monkeypatch.setenv("FINITYAGENT_API_KEY", "env-key")
    assert load_config().api_key == "env-key"


def test_config_file_is_valid_toml(config_home):
    cfg = Config(base_url="u", api_key="k'quote", model="m")
    save_config(cfg)
    with open(cfg_mod.CONFIG_PATH, "rb") as f:
        data = tomllib.load(f)
    assert data["model"] == "m"
