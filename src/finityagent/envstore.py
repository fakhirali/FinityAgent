"""Platform env-var store: KEY=VALUE lines in ~/.finityagent/.env."""
import os
from pathlib import Path

from .config import FINITY_DIR

ENV_PATH = FINITY_DIR / ".env"


def _parse() -> dict:
    data = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"')
    return data


def list_keys() -> list[str]:
    return sorted(_parse())


def set_var(key: str, value: str) -> None:
    key = key.strip().replace(" ", "_").upper()
    data = _parse()
    data[key] = value
    FINITY_DIR.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("".join(f"{k}={v}\n" for k, v in sorted(data.items())))


def remove_var(key: str) -> bool:
    data = _parse()
    if key not in data:
        return False
    del data[key]
    ENV_PATH.write_text("".join(f"{k}={v}\n" for k, v in sorted(data.items())))
    return True


def inject_into(env: dict) -> dict:
    """Return env dict with stored platform vars merged in (existing win)."""
    merged = dict(env)
    for k, v in _parse().items():
        merged.setdefault(k, v)
    return merged
