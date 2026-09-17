import os
import socket
import threading
from urllib.request import urlopen

import uvicorn

from .config import load_config
from .server import app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="finityagent")
    parser.add_argument("--port", type=int, default=8377)
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if args.cwd:
        os.environ["FINITYAGENT_CWD"] = args.cwd

    url = f"http://localhost:{args.port}"
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
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def _open_browser(url: str) -> None:
    import webbrowser
    cfg = load_config()
    webbrowser.open(url + ("/setup" if not cfg.is_configured else "/"))


if __name__ == "__main__":
    main()
