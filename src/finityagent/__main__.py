import os
import socket
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import uvicorn

from .config import load_config
from .server import app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="finityagent")
    parser.add_argument("--port", type=int, default=8377)
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--prompt", default=None,
                        help="send a prompt into a session and exit")
    parser.add_argument("--session", default=None,
                        help="session id or title; created if missing")
    parser.add_argument("command", nargs="?", default=None,
                        choices=["sessions"])
    args = parser.parse_args()

    if args.cwd:
        os.environ["FINITYAGENT_CWD"] = args.cwd

    if args.command == "sessions":
        _print_sessions()
        return

    url = f"http://localhost:{args.port}"

    if args.prompt is not None:
        sender = threading.Thread(target=_send_prompt,
                                  args=(url, args.prompt, args.session),
                                  daemon=True)
        sender.start()
        if not _port_taken(args.port):
            print(f"FinityAgent serving on {url}")
            uvicorn.run(app, host="127.0.0.1", port=args.port,
                        log_level="warning")
            return
        sender.join()
        return

    if _port_taken(args.port):
        # server already running there — just reattach
        print(f"FinityAgent already running on {url}, opening browser")
        if not args.no_browser:
            _open_browser(url)
        return

    print(f"FinityAgent serving on {url}")
    if not args.no_browser:
        threading.Timer(1.0, _open_browser, args=(url,)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def _port_taken(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # SO_REUSEADDR matches how uvicorn binds: TIME_WAIT sockets from a
        # just-killed server no longer read as "already running"
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def _open_browser(url: str) -> None:
    import webbrowser
    cfg = load_config()
    webbrowser.open(url + ("/setup" if not cfg.is_configured else "/"))


def _print_sessions() -> None:
    from . import db
    for s in db.list_sessions():
        print(f"{s.id}\t{s.title}")


def _resolve_session(session: str | None, cwd: str):
    """Return the session row for --session (id, title, or fresh)."""
    from . import db
    if session:
        if session.isdigit():
            row = db.get_session(int(session))
            if row is not None:
                return row
        row = db.find_session_by_title(session)
        if row is not None:
            return row
    sid = db.create_session(cwd=cwd or os.environ.get("FINITYAGENT_CWD")
                            or str(os.path.expanduser("~")),
                            model=load_config().model)
    if session:
        from . import db as _db
        _db.update_session(sid, title=session)
    return db.get_session(sid)


def _send_prompt(url: str, prompt: str, session: str | None) -> None:
    cwd = os.environ.get("FINITYAGENT_CWD")
    for _ in range(200):  # wait up to 20s for a starting server
        try:
            urlopen(url + "/healthz", timeout=2)
            break
        except OSError:
            time.sleep(0.1)
    else:
        print("no finityagent server reachable at", url)
        return
    sid = _resolve_session(session, cwd).id
    req = Request(url + f"/api/chat/{sid}",
                  data=urlencode({"message": prompt}).encode())
    urlopen(req, timeout=30)
    print(f"prompt sent to session {sid} ({url}/chat/{sid})")


if __name__ == "__main__":
    main()
