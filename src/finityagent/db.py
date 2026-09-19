import time
from pathlib import Path

from fastlite import database

FINITY_DIR = Path.home() / ".finityagent"
DB_PATH = FINITY_DIR / "sessions.db"


class Session:
    id: int
    title: str
    cwd: str
    model: str
    effort: str
    hidden: int
    created_at: float
    updated_at: float


class Message:
    id: int
    session_id: int
    role: str
    content: str
    kind: str
    meta: str
    created_at: float


class Artifact:
    id: int
    session_id: int
    name: str
    content: str
    updated_at: float


_cache: dict = {"path": None, "tables": None}


def _tables():
    path = str(DB_PATH)
    if _cache["path"] != path:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        db = database(path)
        _cache["tables"] = (
            db.create(Session, transform=True),
            db.create(Message, transform=True),
            db.create(Artifact, transform=True))
        _cache["path"] = path
    return _cache["tables"]


def create_session(cwd: str, model: str = "") -> int:
    sessions, _, _ = _tables()
    now = time.time()
    row = sessions.insert(cwd=cwd, model=model, title="New chat", effort="",
                          hidden=0, created_at=now, updated_at=now)
    return row.id


def list_sessions() -> list:
    sessions, _, _ = _tables()
    return sessions(where="hidden = 0", order_by="updated_at DESC")


def get_session(session_id: int):
    sessions, _, _ = _tables()
    try:
        return sessions[session_id]
    except Exception:  # noqa: BLE001 - fastlite raises NotFoundError
        return None


def find_session_by_title(title: str):
    sessions, _, _ = _tables()
    rows = sessions(where="title = ?", where_args=(title,))
    return rows[0] if rows else None


def update_session(session_id: int, **fields) -> None:
    sessions, _, _ = _tables()
    row = get_session(session_id)
    if row is None:
        return
    allowed = ("title", "model", "cwd", "effort", "hidden")
    data = {k: getattr(row, k) for k in allowed}
    data.update({k: v for k, v in fields.items() if k in allowed})
    data["updated_at"] = time.time()
    data["id"] = session_id
    sessions.update(data)


def add_message(session_id: int, role: str, content: str,
                kind: str = "text", meta: str = "{}") -> int:
    _, messages, _ = _tables()
    row = messages.insert(session_id=session_id, role=role,
                          content=content, kind=kind, meta=meta,
                          created_at=time.time())
    update_session(session_id)
    return row.id


def get_messages(session_id: int) -> list:
    _, messages, _ = _tables()
    return messages(where="session_id = ?", where_args=(session_id,),
                    order_by="id")


def save_artifact(session_id: int, name: str, content: str) -> int:
    _, _, artifacts = _tables()
    d = {"session_id": session_id, "name": name, "content": content,
         "updated_at": time.time()}
    existing = list_artifacts(session_id, name)
    if existing:
        d["id"] = existing[0].id
        artifacts.update(d)
        return d["id"]
    return artifacts.insert(**d).id


def list_artifacts(session_id: int, name: str = None) -> list:
    _, _, artifacts = _tables()
    if name:
        return artifacts(where="session_id = ? AND name = ?",
                         where_args=(session_id, name))
    return artifacts(where="session_id = ?", where_args=(session_id,),
                     order_by="updated_at DESC")


def get_artifact(artifact_id: int):
    _, _, artifacts = _tables()
    try:
        return artifacts[artifact_id]
    except Exception:  # noqa: BLE001
        return None
