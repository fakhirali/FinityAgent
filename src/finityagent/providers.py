import httpx
from openai import OpenAI

from .config import Config

MODEL_LIST_TIMEOUT = 10.0


def make_client(cfg: Config) -> OpenAI:
    return OpenAI(
        api_key=cfg.api_key or "not-set",
        base_url=cfg.base_url or None,
    )


def list_models(cfg: Config) -> list[str]:
    """Fetch /v1/models from the configured endpoint."""
    if not cfg.base_url:
        return []
    headers = {}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    try:
        resp = httpx.get(
            cfg.base_url.rstrip("/") + "/models",
            headers=headers,
            timeout=MODEL_LIST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return sorted(m["id"] for m in data if "id" in m)
    except (httpx.HTTPError, ValueError, KeyError):
        return []
