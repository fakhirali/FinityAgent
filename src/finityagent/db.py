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


_cache = {"path": None, "sessions": None, "messages": None}


def _tables():
    path = str(DB_PATH)
    if _cache["path"] != path:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        db = database(path)
        _cache["sessions"] = db.create(Session, transform=True)
        _cache["messages"] = db.create(Message, transform=True)
        _cache["path"] = path
    return _cache["sessions"], _cache["messages"]


def create_session(cwd: str, model: str = "") -> int:
    sessions, _ = _tables()
    now = time.time()
    row = sessions.insert(cwd=cwd, model=model, title="New chat",
                          created_at=now, updated_at=now)
    return row.id


def list_sessions() -> list:
    sessions, _ = _tables()
    return sessions(order_by="updated_at DESC")


def get_session(session_id: int):
    sessions, _ = _tables()
    try:
        return sessions[session_id]
    except Exception:  # noqa: BLE001 - fastlite raises NotFoundError
        return None


def update_session(session_id: int, **fields) -> None:
    sessions, _ = _tables()
    row = get_session(session_id)
    if row is None:
        return
    allowed = ("title", "model", "cwd")
    data = {k: getattr(row, k) for k in allowed}
    data.update({k: v for k, v in fields.items() if k in allowed})
    data["updated_at"] = time.time()
    data["id"] = session_id
    sessions.update(data)


def add_message(session_id: int, role: str, content: str,
                kind: str = "text", meta: str = "{}") -> int:
    _, messages = _tables()
    row = messages.insert(session_id=session_id, role=role,
                          content=content, kind=kind, meta=meta,
                          created_at=time.time())
    update_session(session_id)
    return row.id


def get_messages(session_id: int) -> list:
    _, messages = _tables()
    return messages(where="session_id = ?", where_args=(session_id,),
                    order_by="id")
