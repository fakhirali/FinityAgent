from finityagent import tools


def test_simple_command(tmp_path):
    result = tools.run_bash("echo hello", str(tmp_path))
    assert result.exit_code == 0
    assert "hello" in result.output


def test_stderr_combined(tmp_path):
    result = tools.run_bash("echo err >&2", str(tmp_path))
    assert "err" in result.output


def test_exit_code(tmp_path):
    result = tools.run_bash("exit 3", str(tmp_path))
    assert result.exit_code == 3


def test_timeout_kills(tmp_path):
    result = tools.run_bash("sleep 30", str(tmp_path), timeout=1.0)
    assert result.timed_out
    assert result.exit_code == 124


def test_timeout_kills_children(tmp_path):
    import subprocess

    cmd = "(sleep 300 & echo $! > child.pid); wait"
    tools.run_bash(cmd, str(tmp_path), timeout=0.5)
    probe = subprocess.run(
        ["/bin/bash", "-c",
         f"cd {tmp_path} && [ -f child.pid ] && kill -0 $(cat child.pid)"
         " 2>/dev/null; echo $?"],
        capture_output=True, text=True,
    )
    assert probe.stdout.strip().endswith("1"), "child process should be dead"


def test_output_tail_capped(tmp_path):
    result = tools.run_bash("python3 -c \"print('x' * 40000)\"", str(tmp_path))
    assert "truncated" in result.output
    assert len(result.output) < 31_500


def test_execute_tool_call_roundtrip(tmp_path):
    import json

    result = tools.execute_tool_call(
        "bash", json.dumps({"command": "echo roundtrip"}), str(tmp_path))
    assert "roundtrip" in result
    assert "exit code: 0" in result


def test_execute_tool_call_bad_json(tmp_path):
    result = tools.execute_tool_call("bash", "{not json", str(tmp_path))
    assert result.startswith("error")


def test_execute_tool_call_unknown(tmp_path):
    result = tools.execute_tool_call("nope", "{}", str(tmp_path))
    assert "unknown tool" in result


def test_cancel_stops_running_process(tmp_path):
    import threading
    import time

    holder = {}
    t = threading.Thread(
        target=tools.run_bash,
        args=("sleep 20", str(tmp_path)),
        kwargs={"proc_holder": holder},
    )
    t.start()
    time.sleep(0.3)
    assert tools.cancel(holder)
    t.join(timeout=5)
    assert not t.is_alive()
