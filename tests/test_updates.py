"""Tests for hermes-updates features."""
import os
import time

import pytest

import finityagent.tools as tools
from finityagent import db, envstore, memory
from finityagent.agent import Agent, compact_messages
from finityagent.permissions import is_denied
from finityagent.prompts import build_system_prompt


def test_memory_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "MEMORY.md"
    monkeypatch.setattr(memory, "MEMORY_PATH", p)
    assert memory.read_memory() == ""
    assert memory.append_memory("likes terse answers")
    assert "terse" in memory.read_memory()
    assert not memory.write_memory("x" * (memory.MAX_CHARS + 1))


def test_envstore_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    monkeypatch.setattr(envstore, "ENV_PATH", p)
    envstore.set_var("TELEGRAM_TOKEN", "abc")
    envstore.set_var("github_token", "xyz")  # gets uppercased
    assert envstore.list_keys() == ["GITHUB_TOKEN", "TELEGRAM_TOKEN"]
    merged = envstore.inject_into({"OTHER": "1"})
    assert merged["TELEGRAM_TOKEN"] == "abc" and merged["OTHER"] == "1"
    # existing env wins
    assert envstore.inject_into({"TELEGRAM_TOKEN": "keep"})["TELEGRAM_TOKEN"] == "keep"
    assert envstore.remove_var("TELEGRAM_TOKEN")
    assert "TELEGRAM_TOKEN" not in envstore.list_keys()


def test_detached_command_returns_promptly(tmp_path):
    # plain bash replaces the old finity-bg facility: redirect + & + nohup
    log = tmp_path / "job.log"
    t0 = time.time()
    r = tools.run_bash(f"nohup sleep 30 > {log} 2>&1 & echo launched $!",
                       cwd=str(tmp_path), timeout=10)
    assert "launched" in r.output
    assert time.time() - t0 < 2  # did not wait for the detached child


def test_long_output_saved_to_file():
    result = tools.run_bash("python3 -c 'print(\"x\"*40000)'", cwd="/tmp",
                            timeout=30)
    assert "[output truncated" in result.output
    assert "~/.finityagent/files/output-" in result.output


class FakeAgent:
    def __init__(self):
        from unittest.mock import MagicMock
        self.client = MagicMock()
        self.client.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content="brief summary"))]
        self.model = "m"
        self.compact_summary = ""


def test_compaction_small_history_untouched():
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"}]
    assert compact_messages(msgs, FakeAgent()) is msgs


def test_compaction_prunes_tool_outputs_without_llm_call():
    from unittest.mock import MagicMock
    agent = FakeAgent()
    agent.client.chat.completions.create = MagicMock(
        side_effect=AssertionError("LLM must not be called"))
    # big tool output outside the protected tail (last 12 messages)
    msgs = [{"role": "tool", "content": "y" * 600}] \
        + [{"role": "user", "content": "hi"}] * 13 \
        + [{"role": "user", "content": "recent"}]
    total = sum(len(m["content"]) for m in msgs)
    assert total < 400_000  # pruning, not summarizing, is what's tested
    compact_messages(msgs, agent)
    assert "pruned" in msgs[0]["content"]
    assert agent.client.chat.completions.create.call_count == 0


def test_compaction_trims_old():
    agent = FakeAgent()
    msgs = ([{"role": "user", "content": "x" * 400_100}] * (5)
            + [{"role": "user", "content": "recent"}])
    out = compact_messages(msgs, agent)
    assert out[0]["role"] == "user"
    assert "brief summary" in out[0]["content"]
    assert "REFERENCE ONLY" in out[0]["content"]
    assert out[-1]["content"] == "recent"
    assert "recent" not in out[0]["content"]  # summary only over old turns
    assert agent.compact_summary == "brief summary"  # anchored for next time


def test_compaction_anchored_summary_updated():
    agent = FakeAgent()
    agent.compact_summary = "old summary"
    msgs = [{"role": "user", "content": "x" * 400_100}] * 5
    compact_messages(msgs, agent)
    req = agent.client.chat.completions.create.call_args
    content = req.kwargs["messages"][0]["content"]
    assert "old summary" in content  # previous summary passed for update


def test_compaction_never_splits_tool_pair():
    agent = FakeAgent()
    msgs = ([{"role": "user", "content": "x" * 400_800}] * 5
            + [{"role": "assistant", "content": None,
                "tool_calls": [{"id": "1"}]},
               {"role": "tool", "content": "res"}])
    out = compact_messages(msgs, agent)
    # summary first, then the cut history - and the cut history must not
    # start with a tool result whose assistant call was compacted away
    assert out[0]["content"].startswith("[CONTEXT COMPACTION")
    assert out[1].get("role") != "tool"


def test_session_effort_and_hidden_fields():
    sid = db.create_session(cwd="/tmp", model="m1")
    db.update_session(sid, effort="high", hidden=1)
    row = db.get_session(sid)
    assert row.effort == "high" and row.hidden == 1
    assert all(s.id != sid for s in db.list_sessions())
    db.update_session(sid, hidden=0)
    assert any(s.id == sid for s in db.list_sessions())


def test_artifacts_upsert():
    sid = db.create_session(cwd="/tmp")
    a1 = db.save_artifact(sid, "chart", "<div>v1</div>")
    a2 = db.save_artifact(sid, "chart", "<div>v2</div>")
    assert a1 == a2
    got = db.list_artifacts(sid, name="chart")[0]
    assert got.content == "<div>v2</div>"


def test_sessions_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "db.sqlite")
    sid = db.create_session(cwd="/tmp", model="m")
    db.update_session(sid, title="cron helper")
    from finityagent.__main__ import _print_sessions
    _print_sessions()
    out = capsys.readouterr().out
    assert f"{sid}\tcron helper" in out


def test_resolve_session(tmp_path, monkeypatch):
    from finityagent.__main__ import _resolve_session
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "db.sqlite")
    sid = db.create_session(cwd="/tmp", model="m")
    db.update_session(sid, title="mail-check")
    # int id hits existing session, title hits it too, unknown creates new
    assert _resolve_session(str(sid), "/tmp").id == sid
    assert _resolve_session("mail-check", "/tmp").id == sid
    created = _resolve_session("weather", "/tmp")
    assert created.title == "weather"
    # bare --session with no match creates a fresh session
    fresh = _resolve_session(None, "/tmp")
    assert fresh.id != created.id


def test_prompt_includes_session_id():
    p = build_system_prompt(7)
    assert "session id is 7" in p
    assert "session id is" not in build_system_prompt()


def test_server_fragments():
    from finityagent.server import (_mini_md, _slash_to_skill, _strip_fences,
                                    _wrap_scripts, sse_event)
    assert _slash_to_skill("/writer draft a haiku") == \
        "[skill: writer] draft a haiku"
    assert _slash_to_skill("plain message") == "plain message"
    assert _mini_md("**bold** `code`") == \
        "<strong>bold</strong> <code>code</code>"
    assert _mini_md("<script>") == "&lt;script&gt;"
    assert _strip_fences("```html\n<div>x</div>\n```") == "<div>x</div>"
    out = _wrap_scripts("<div><script>let a = 1</script></div>")
    assert "function(){let a = 1}" in out
    # every SSE fragment line is a data line (blank lines don't split events)
    ev = sse_event("html_response", '<div class="x">\n\nok</div>')
    assert ev.count("\n\n") == 1 and ev.endswith("\n\n")
