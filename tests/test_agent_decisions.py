import pytest

from finityagent.agent import Agent


def make_agent():
    class FakeCompletions:
        def create(self, **kwargs):
            raise RuntimeError("not used in decide tests")

    class FakeClient:
        chat = type("C", (), {})()
        chat.completions = FakeCompletions()

    return Agent(FakeClient(), "test-model", "/tmp")


def test_denied_command_blocked_even_in_auto():
    a = make_agent()
    a.auto_approve = True
    assert a._decide("sudo rm -rf /") == "deny"


def test_auto_mode_allows_everything_else():
    a = make_agent()
    a.auto_approve = True
    assert a._decide("npm test") == "allow"


def test_ask_mode_asks_by_default():
    a = make_agent()
    assert a._decide("npm test") == "ask"


def test_session_always_prefix():
    a = make_agent()
    a.session_approved.add("git status")
    assert a._decide("git status --porcelain") == "allow"
    assert a._decide("git push origin main") == "ask"


def test_resolve_approval_always_adds_prefix():
    a = make_agent()
    a.approval_event.clear()
    a.resolve_approval("always", "npm install")
    assert a.session_approved == {"npm install"}
    assert a.approval_event.is_set()


def test_resolve_approval_skip_does_not_persist():
    a = make_agent()
    a.resolve_approval("skip")
    assert a.session_approved == set()
