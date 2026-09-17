from __future__ import annotations

import json
import threading
from collections import defaultdict

from openai import OpenAI

from . import tools
from .permissions import command_prefix, is_denied
from .prompts import build_system_prompt


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


class Agent:
    def __init__(self, client: OpenAI, model: str, cwd: str):
        self.client = client
        self.model = model
        self.cwd = cwd
        self.auto_approve = False
        self.session_approved: set[str] = set()
        self.pending_approval: dict | None = None
        self.approval_event = threading.Event()
        self.cancel_flag = threading.Event()
        self.proc_holder: dict = {}

    def resolve_approval(self, decision: str, prefix: str | None = None) -> None:
        if decision == "always" and prefix:
            self.session_approved.add(prefix)
        self.pending_approval = {"decision": decision, "prefix": prefix}
        self.approval_event.set()

    def cancel(self) -> None:
        self.cancel_flag.set()
        tools.cancel(self.proc_holder)
        if self.pending_approval is not None:
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
        messages = [{"role": "system", "content": build_system_prompt()},
                    *history]
        while True:
            if self.cancel_flag.is_set():
                return messages
            assistant_text = ""
            calls: dict = defaultdict(dict)
            call_order: list[int] = []
            try:
                stream = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=[tools.tool_schema()],
                    stream=True,
                )
                for chunk in stream:
                    if self.cancel_flag.is_set():
                        stream.close()
                        return messages
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
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
                            decision_info["decision"] != "allow":
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
