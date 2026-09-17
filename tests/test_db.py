import pytest

from finityagent import db as dbm


@pytest.fixture
def db_home(tmp_path, monkeypatch):
    monkeypatch.setattr(dbm, "FINITY_DIR", tmp_path / ".finityagent")
    monkeypatch.setattr(dbm, "DB_PATH", tmp_path / ".finityagent" / "sessions.db")
    return tmp_path


def test_create_and_list_session(db_home):
    sid = dbm.create_session(cwd="/tmp", model="kimi-k3")
    sessions = dbm.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].cwd == "/tmp"
    assert sessions[0].title == "New chat"
    assert sessions[0].model == "kimi-k3"


def test_add_and_get_messages(db_home):
    sid = dbm.create_session(cwd="/tmp")
    dbm.add_message(sid, "user", "hi")
    dbm.add_message(sid, "assistant", "<h1>hi</h1>", kind="html_response")
    msgs = dbm.get_messages(sid)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[1].kind == "html_response"


def test_update_session_title(db_home):
    sid = dbm.create_session(cwd="/tmp")
    dbm.update_session(sid, title="My chat")
    assert dbm.get_session(sid).title == "My chat"


def test_message_updates_session_timestamp(db_home):
    import time

    sid = dbm.create_session(cwd="/tmp")
    before = dbm.get_session(sid).updated_at
    time.sleep(0.01)
    dbm.add_message(sid, "user", "hi")
    after = dbm.get_session(sid).updated_at
    assert after >= before


def test_concurrent_threads(db_home):
    import threading

    errors = []

    def worker(i):
        try:
            sid = dbm.create_session(cwd="/tmp")
            dbm.add_message(sid, "user", f"msg-{i}")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(dbm.list_sessions()) == 8
