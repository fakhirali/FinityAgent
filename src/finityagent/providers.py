from openai import OpenAI

from .config import Config

# ponytail: the openai SDK already does endpoint + key + error handling;
# wrapping /models ourselves would be re-buying the same rope.
def make_client(cfg: Config, session_id: int | None = None):
    headers = {"User-Agent": "finityagent/0.1"}
    if session_id is not None:
        # opencode-go requires a stable per-conversation routing id
        headers["x-opencode-session"] = f"finityagent-{session_id}"
    return OpenAI(api_key=cfg.api_key or "not-set",
                  base_url=cfg.base_url or None, default_headers=headers)


def list_models(cfg: Config) -> list[str]:
    if not cfg.base_url:
        return []
    try:
        return sorted(m.id for m in make_client(cfg).models.list())
    except Exception:  # noqa: BLE001 - wizard just shows an empty list
        return []
