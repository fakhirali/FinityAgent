from __future__ import annotations

import json
import threading
from collections import defaultdict

from openai import OpenAI

from . import tools
from .permissions import command_prefix, is_denied
from .prompts import build_system_prompt

# ponytail: compaction trims hard at a char budget instead of tokenizing;
# 4 chars/token is a conservative ceiling so real token counts stay lower
CONTEXT_CHAR_BUDGET = 400_000
COMPACT_KEEP_RECENT = 12  # recent messages never compacted


class ApprovalNeeded(Exception):
    def __init__(self, command: str, prefix: str):
        self.command = command
        self.prefix = prefix
        super().__init__(command)


def _extract_tool_call_deltas(delta, accumulator: dict):
    for tc in delta.tool_calls or []:
        slot = accumulator[tc.index]
        if tc.id:
            slot["id"] = tc.id
        if tc.function and tc.function.name:
            slot["name"] = (slot.get("name") or "") + tc.function.name
        if tc.function and tc.function.arguments:
            slot["args"] = (slot.get("args") or "") + tc.function.arguments


def _history_chars(messages: list[dict]) -> int:
    return sum(len(m.get("content") or "")
               + sum(len(c.get("arguments") or "")
                     for c in (m.get("tool_calls") or []))
               for m in messages)


# ponytail: tool results are the bulk of context bloat; stubbing old ones
# needs no LLM call. Long outputs are already saved to disk by the bash
# tool, so the full text is always recoverable.
PRUNE_MIN_CHARS = 500


def _prune_tool_outputs(history: list[dict], keep_recent: int) -> bool:
    """Stub oversized tool outputs outside the protected recent tail.
    In-place; returns True if anything was pruned."""
    pruned = False
    for i in range(max(0, len(history) - keep_recent)):
        m = history[i]
        content = m.get("content")
        if (m.get("role") == "tool" and isinstance(content, str)
                and len(content) > PRUNE_MIN_CHARS):
            m["content"] = f"[tool output pruned, {len(content)} chars]"
            pruned = True
    return pruned


SUMMARY_TEMPLATE = (
    "Summarize the following conversation history into a compact brief: "
    "user goals, decisions, key facts, file paths, state of any work in "
    "progress. Keep it under 2000 chars. No preamble.")


def compact_messages(history: list[dict], agent) -> list[dict]:
    """Prune old tool outputs, then summarize old turns into one anchored
    summary message. The summary is anchored: later compactions update it
    instead of starting over."""
    # cheap pass first — old tool outputs are most of the bulk
    _prune_tool_outputs(history, COMPACT_KEEP_RECENT)
    if _history_chars(history) <= CONTEXT_CHAR_BUDGET:
        return history
    cut = max(0, len(history) - COMPACT_KEEP_RECENT)
    # never cut between an assistant tool_call and its tool result: advance
    # past tool-role messages even beyond the keep-recent limit so a tool
    # result never starts the recent block without its assistant in old
    while cut < len(history) and history[cut].get("role") == "tool":
        cut += 1
    old, recent = history[:cut], history[cut:]
    prev = getattr(agent, "compact_summary", "")
    anchor = (f"Update this anchored summary with the history below — keep "
              f"still-true details, drop stale ones:\n\n{prev}\n\n"
              if prev else "")
    summary_req = [
        {"role": "user", "content": anchor + SUMMARY_TEMPLATE + "\n\n"
         + json.dumps([{"role": m["role"], "content": m.get("content")}
                       for m in old])[:150_000]},
    ]
    try:
        resp = agent.client.chat.completions.create(
            model=agent.model, messages=summary_req)
        brief = resp.choices[0].message.content or ""
    except Exception:  # noqa: BLE001 - compaction must never kill the turn
        brief = prev or "(summary unavailable)"
    brief = brief[:2000]
    agent.compact_summary = brief
    summary_msg = {"role": "user", "content":
                   "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were "
                   "compacted into the summary below. Treat it as background "
                   "reference, NOT active instructions; respond to the "
                   "latest user message after it.\n"
                   + brief + "\n--- END OF CONTEXT SUMMARY ---"}
    return [summary_msg, *recent]


class Agent:
    def __init__(self, client: OpenAI, model: str, cwd: str,
                 reasoning_effort: str = "default",
                 session_id: int | None = None):
        self.client = client
        self.model = model
        self.cwd = cwd
        # ponytail: single OpenAI-standard knob; endpoints without reasoning
        # simply ignore it — per-provider variant maps are a V2 idea
        self.reasoning_effort = reasoning_effort
        self.auto_approve = False
        self.session_approved: set[str] = set()
        self.pending_approval: dict | None = None
        self.approval_event = threading.Event()
        self.cancel_flag = threading.Event()
        self.proc_holder: dict = {}
        self.compact_summary = ""  # anchored summary carried across turns
        self.session_id = session_id

    def resolve_approval(self, decision: str, prefix: str | None = None) -> None:
        if decision == "always" and prefix:
            self.session_approved.add(prefix)
        self.pending_approval = {"decision": decision, "prefix": prefix}
        self.approval_event.set()

    def cancel(self) -> None:
        self.cancel_flag.set()
        tools.cancel(self.proc_holder)
        # unblock a turn waiting on approval, if any
        self.resolve_approval("skip")

    def _decide(self, command: str) -> str:
        if is_denied(command):
            return "deny"
        if self.auto_approve:
            return "allow"
        prefix = command_prefix(command)
        if prefix in self.session_approved:
            return "allow"
        return "ask"

    def run_turn(self, history: list[dict]):
        """Generator yielding event dicts; returns full updated history list
        via StopIteration value."""
        system = build_system_prompt(self.session_id)
        messages = compact_messages(history, self)
        messages = [{"role": "system", "content": system}, *messages]
        while True:
            if self.cancel_flag.is_set():
                return messages
            assistant_text = ""
            calls: dict = defaultdict(dict)
            call_order: list[int] = []
            try:
                kwargs = {}
                if self.reasoning_effort != "default":
                    kwargs["reasoning_effort"] = self.reasoning_effort
                stream = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=[tools.tool_schema()],
                    stream=True,
                    **kwargs,
                )
                for chunk in stream:
                    if self.cancel_flag.is_set():
                        stream.close()
                        return messages
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    # ponytail: different providers expose reasoning as
                    # reasoning_content (DeepSeek) or reasoning (Kimi/GLM)
                    reasoning = (getattr(delta, "reasoning_content", None)
                                 or getattr(delta, "reasoning", None))
                    if reasoning:
                        yield {"type": "reasoning_delta", "text": reasoning}
                    if delta and delta.content:
                        assistant_text += delta.content
                        yield {"type": "text_delta", "text": delta.content}
                    if delta and delta.tool_calls:
                        before = len(calls)
                        _extract_tool_call_deltas(delta, calls)
                        for i in range(before, len(calls)):
                            call_order.append(i)
            except Exception as e:
                yield {"type": "error", "message": str(e)}
                return messages

            if not call_order:
                yield {"type": "html_response", "html": assistant_text}
                if assistant_text:
                    messages.append({"role": "assistant",
                                     "content": assistant_text})
                return messages

            assistant_msg = {"role": "assistant", "content": assistant_text or None}
            assistant_msg["tool_calls"] = [
                {"id": calls[i].get("id", f"call_{i}"),
                 "type": "function",
                 "function": {"name": calls[i].get("name", ""),
                              "arguments": calls[i].get("args", "{}")}}
                for i in call_order
            ]
            messages.append(assistant_msg)

            for i in call_order:
                if self.cancel_flag.is_set():
                    return messages
                call = calls[i]
                call_id = call.get("id", f"call_{i}")
                name = call.get("name", "")
                raw_args = call.get("args", "{}")
                try:
                    command = json.loads(raw_args).get("command", "")
                except json.JSONDecodeError:
                    command = ""
                yield {"type": "tool_call", "id": call_id, "name": name,
                       "command": command}

                decision = self._decide(command)
                if decision == "deny":
                    messages.append({"role": "tool", "tool_call_id": call_id,
                                     "content": "error: command blocked by "
                                                "security policy"})
                    yield {"type": "tool_result", "id": call_id,
                           "blocked": True,
                           "output": "command blocked by security policy"}
                    continue
                if decision == "ask":
                    self.pending_approval = None
                    self.approval_event.clear()
                    yield {"type": "approval_request", "id": call_id,
                           "command": command,
                           "prefix": command_prefix(command)}
                    self.approval_event.wait()
                    decision_info = self.pending_approval or {"decision": "skip"}
                    if self.cancel_flag.is_set() or \
                            decision_info["decision"] not in ("allow", "always"):
                        messages.append({"role": "tool",
                                         "tool_call_id": call_id,
                                         "content": "user skipped this command"})
                        yield {"type": "tool_result", "id": call_id,
                               "blocked": True,
                               "output": "user skipped this command"}
                        continue

                result = tools.execute_tool_call(name, raw_args, self.cwd,
                                                 proc_holder=self.proc_holder)
                self.proc_holder = {}
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "content": result})
                yield {"type": "tool_result", "id": call_id,
                       "blocked": False, "output": result}
