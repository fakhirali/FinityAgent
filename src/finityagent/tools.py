from __future__ import annotations

import json
import os
import signal
import subprocess

DEFAULT_TIMEOUT = 120.0
MAX_TIMEOUT = 600.0
MAX_OUTPUT = 30_000

TRUNCATION_NOTICE = "\n... [output truncated, showing last {} of {} chars]"


class BashResult:
    def __init__(self, output: str, exit_code: int, timed_out: bool = False):
        self.output = output
        self.exit_code = exit_code
        self.timed_out = timed_out

    def as_tool_result(self) -> str:
        suffix = ""
        if self.timed_out:
            suffix = "\n[command timed out and was killed]"
        return f"exit code: {self.exit_code}\n{self.output}{suffix}"


def _tail_cap(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    notice = TRUNCATION_NOTICE.format(MAX_OUTPUT, len(text))
    return text[-MAX_OUTPUT:] + notice


def run_bash(command: str, cwd: str, timeout: float = DEFAULT_TIMEOUT,
             on_start=None, proc_holder: dict | None = None) -> BashResult:
    timeout = min(max(float(timeout), 1.0), MAX_TIMEOUT)
    env = {**os.environ, "TERM": "dumb"}
    try:
        proc = subprocess.Popen(
            ["/bin/bash", "-c", command],
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except FileNotFoundError as e:
        return BashResult(f"failed to start: {e}", 127)

    if proc_holder is not None:
        proc_holder["proc"] = proc
    if on_start is not None:
        on_start(proc)

    timed_out = False
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(proc)
        out, _ = proc.communicate()
    except KeyboardInterrupt:
        _kill_process_group(proc)
        out, _ = proc.communicate()
        timed_out = True

    exit_code = proc.returncode if not timed_out else 124
    return BashResult(_tail_cap(out or ""), exit_code, timed_out)


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except OSError:
            pass


def cancel(proc_holder: dict) -> bool:
    proc = proc_holder.get("proc")
    if proc and proc.poll() is None:
        _kill_process_group(proc)
        return True
    return False


def tool_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run a bash command on the user's machine. Supports pipes, "
                "redirection, heredocs, and command chaining. Output is "
                "stdout+stderr combined, tail-capped at 30k chars. "
                "Default timeout 120s, maximum 600s."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string",
                                "description": "The bash command to run"},
                    "timeout": {"type": "number",
                                "description": "Timeout in seconds "
                                               "(1-600, default 120)"},
                },
                "required": ["command"],
            },
        },
    }


def execute_tool_call(name: str, arguments: str, cwd: str,
                      proc_holder: dict | None = None) -> str:
    if name != "bash":
        return f"error: unknown tool {name!r}"
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError as e:
        return f"error: invalid arguments ({e})"
    command = args.get("command")
    if not command or not isinstance(command, str):
        return "error: missing 'command' argument"
    result = run_bash(command, cwd,
                      timeout=args.get("timeout", DEFAULT_TIMEOUT),
                      proc_holder=proc_holder)
    return result.as_tool_result()
