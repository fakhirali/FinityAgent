import json
import threading
import time

from fasthtml.common import *
from fasthtml.pico import picolink
from starlette.responses import FileResponse, StreamingResponse

from . import db, providers
from .agent import Agent
from .config import PRESETS, Config, load_config, save_config

app = FastHTML(hdrs=(picolink,
                     Link(rel="stylesheet", href="/static/style.css")),
               htmlkw={"data-theme": "dark"})

agents: dict[int, Agent] = {}


def _head(title):
    return (Title(title),)


# ---------- wizard ----------

def wizard_page(error: str = ""):
    options = [Option(v["label"], value=k, selected=(k == "opencode-go"))
               for k, v in PRESETS.items()]
    err = P(error, cls="error") if error else None
    card = Div(
        H1("FinityAgent"),
        P("One tool. Bash. Interactive HTML answers.", cls="muted"),
        Form(
            Label("Provider preset"),
            Select(*options, name="preset", id="preset"),
            Label("Base URL"),
            Input(name="base_url", id="base_url", required=True,
                  placeholder="https://opencode.ai/zen/go/v1"),
            Label("API key"),
            Input(name="api_key", id="api_key", type="password",
                  required=True, placeholder="paste your API key"),
            Label("Model"),
            Select(name="model", id="model", required=True),
            Button("Start", type="submit"),
            err,
            action="/setup", method="post", id="setup-form"),
        Script(src="/static/wizard.js"),
        cls="setup-card")
    return _head("FinityAgent Setup"), Div(card, cls="setup-center")


@app.get("/setup")
def setup_get():
    return wizard_page()


@app.post("/setup")
def setup_post(preset: str, base_url: str, api_key: str, model: str):
    cfg = Config(base_url=base_url.strip(), api_key=api_key.strip(),
                 model=model.strip(), preset=preset)
    save_config(cfg)
    return RedirectResponse("/", status_code=303)


# ---------- chat page ----------

def chat_shell(session_id: int, cfg: Config, cwd: str):
    return Title("FinityAgent"), Div(
        Aside(
            Button("+ New chat", id="new-chat"),
            # HTMX loads and refreshes the list; server renders the <li>s
            Ul(id="session-list",
               hx_get="/api/sessions-list", hx_trigger="load, finity:refresh from:body",
               hx_swap="innerHTML"),
            id="sidebar"),
        Main(
            Header(
                Div(Select(id="model-switcher"),
                    Select(
                        Option("Default", value="default", selected=True),
                        Option("Reasoning: low", value="low"),
                        Option("Reasoning: medium", value="medium"),
                        Option("Reasoning: high", value="high"),
                        id="effort-switcher"),
                    id="model-switcher-wrap"),
                Div(
                    Label(Input(type="checkbox", id="auto-mode"), " Auto",
                          cls="switch"),
                    Label(Input(type="checkbox", id="show-tools",
                                checked=True), " Tool calls", cls="switch"),
                    id="mode-wrap"),
                id="topbar"),
            Div(id="transcript"),
            Form(
                Textarea(id="chat-input", rows="1", autocomplete="off",
                         placeholder="Ask anything — answers arrive as "
                                     "interactive HTML"),
                Button("Send", id="send", type="submit"),
                id="composer"),
            id="main"),
        Script(src="/static/app.js"),
        id="app")


@app.get("/")
def index():
    cfg = load_config()
    if not cfg.is_configured:
        return RedirectResponse("/setup", status_code=303)
    cwd = _launch_cwd()
    session_id = db.create_session(cwd=cwd, model=cfg.model)
    # ponytail: one URL = one session id; app.js reads it from the path
    return RedirectResponse(f"/chat/{session_id}", status_code=303)


@app.get("/chat/{session_id}")
def chat(session_id: int):
    cfg = load_config()
    if not cfg.is_configured:
        return RedirectResponse("/setup", status_code=303)
    sess = db.get_session(session_id)
    if sess is None:
        return RedirectResponse("/", status_code=303)
    return chat_shell(session_id, cfg, sess.cwd)


def _launch_cwd() -> str:
    import os
    return os.environ.get("FINITYAGENT_CWD") or os.getcwd()


# ---------- API ----------

@app.get("/api/sessions-list")
def api_sessions_list():
    return [Li(s.title, data_sid=str(s.id)) for s in db.list_sessions()]


@app.get("/api/sessions")
def api_sessions():
    return [{"id": s.id, "title": s.title} for s in db.list_sessions()]


@app.get("/api/messages/{session_id}")
def api_messages(session_id: int):
    return {"messages": [
        {"role": m.role, "content": m.content, "kind": m.kind, "meta": m.meta}
        for m in db.get_messages(session_id)]}


@app.get("/api/wizard-models")
def wizard_models(base_url: str, api_key: str = ""):
    cfg = Config(base_url=base_url.strip(), api_key=api_key.strip(),
                 model="", preset="custom")
    return {"models": providers.list_models(cfg)}


@app.get("/api/models")
def api_models():
    cfg = load_config()
    return {"models": providers.list_models(cfg), "current": cfg.model}


@app.post("/api/models/{model}")
def api_set_model(model: str):
    cfg = load_config()
    cfg.model = model
    save_config(cfg)
    for agent in agents.values():
        agent.model = model
    return {"ok": True}


@app.get("/api/reasoning-options")
def reasoning_options():
    # ponytail: levels come from models.dev (what OpenCode uses); unknown
    # providers get the generic OpenAI ladder. toggle/budget_tokens variants
    # are V2 — effort-only for now.
    cfg = load_config()
    fallback = ["default", "low", "medium", "high"]
    pid = _provider_id(cfg)
    if not pid:
        return {"options": fallback}
    try:
        m = _models_dev()[pid]["models"].get(cfg.model, {})
        efforts = [o.get("values", []) for o in m.get("reasoning_options", [])
                   if o.get("type") == "effort"]
    except Exception:  # noqa: BLE001 - offline or unknown provider
        return {"options": fallback}
    values = efforts[0] if efforts else []
    return {"options": ["default", *dict.fromkeys(values)]}


_md_cache = None


def _models_dev():
    global _md_cache
    if _md_cache is None:
        import urllib.request
        req = urllib.request.Request(
            "https://models.dev/api.json",
            headers={"User-Agent": "finityagent/0.1"})
        with urllib.request.urlopen(req, timeout=15) as r:
            _md_cache = json.load(r)
    return _md_cache


def _provider_id(cfg) -> str | None:
    if "opencode.ai/zen" in cfg.base_url:
        return "opencode-go"
    if "api.openai.com" in cfg.base_url:
        return "openai"
    return None


@app.post("/api/effort/{level}")
def api_set_effort(level: str):
    cfg = load_config()
    if level in ("default", "low", "medium", "high"):
        cfg.reasoning_effort = level
        save_config(cfg)
    for agent in agents.values():
        agent.reasoning_effort = level
    return {"ok": True}


@app.get("/api/effort")
def api_get_effort():
    return {"effort": load_config().reasoning_effort}


@app.post("/api/approve/{session_id}")
def api_approve(session_id: int, decision: str, prefix: str = ""):
    agent = agents.get(session_id)
    if agent:
        agent.resolve_approval(decision, prefix or None)
    return {"ok": True}


@app.post("/api/auto/{session_id}")
def api_auto(session_id: int, on: bool = False):
    cfg = load_config()
    cfg.auto_approve = on
    save_config(cfg)
    for agent in agents.values():
        agent.auto_approve = on
    return {"ok": True}


@app.get("/api/auto")
def api_get_auto():
    return {"auto": load_config().auto_approve}


@app.post("/api/cancel/{session_id}")
def api_cancel(session_id: int):
    agent = agents.get(session_id)
    if agent:
        agent.cancel()
    return {"ok": True}


@app.post("/api/chat/{session_id}")
def api_chat(session_id: int, message: str):
    if session_id in turns and turns[session_id]["running"]:
        return {"error": "a turn is already running in this conversation"}
    cfg = load_config()
    agent = agents.get(session_id)
    if agent is None:
        sess = db.get_session(session_id)
        agent = Agent(providers.make_client(cfg, session_id),
                      sess.model or cfg.model, sess.cwd,
                      reasoning_effort=cfg.reasoning_effort)
    agents[session_id] = agent
    agent.cancel_flag.clear()
    agent.model = cfg.model
    agent.reasoning_effort = cfg.reasoning_effort
    agent.auto_approve = cfg.auto_approve

    history = [
        {"role": m.role, "content": m.content}
        for m in db.get_messages(session_id)
        if m.role in ("user", "assistant")
        and m.kind in ("text", "html_response")
    ]
    db.add_message(session_id, "user", message)
    if db.get_session(session_id).title == "New chat":
        db.update_session(session_id, title=message[:60])
    history.append({"role": "user", "content": message})

    # turn runs in a background thread — independent of any browser
    # connection, so switching chats or closing the tab doesn't kill it
    turn = turns.setdefault(session_id, {
        "events": [], "running": False,
        "cond": threading.Condition()})
    turn["events"] = []
    turn["running"] = True
    threading.Thread(target=_run_turn,
                     args=(session_id, agent, history), daemon=True).start()
    return {"ok": True, "user_message": message}


turns: dict[int, dict] = {}


def _run_turn(session_id: int, agent: Agent, history: list):
    turn = turns[session_id]

    def emit(etype: str, event: dict) -> None:
        turn["events"].append((etype, event))
        with turn["cond"]:
            turn["cond"].notify_all()

    try:
        for event in agent.run_turn(history):
            etype = event.pop("type")
            if etype == "html_response":
                db.add_message(session_id, "assistant",
                               event.get("html", ""), kind="html_response")
            emit(etype, event)
    finally:
        emit("turn_complete", {})
        agents.pop(session_id, None)
        turn["running"] = False
        with turn["cond"]:
            turn["cond"].notify_all()


@app.get("/api/stream/{session_id}")
def api_stream(session_id: int, since: int = 0):
    # ponytail: 5Hz polling per open tab — trivial load, no missed events
    def sse():
        yield "retry: 1000\n\n"
        idx = since
        while True:
            turn = turns.get(session_id)
            if turn is None:
                yield sse_event("turn_complete", {})
                return
            events = turn["events"]
            while idx < len(events):
                etype, event = events[idx]
                idx += 1
                yield sse_event(etype, event)
            if not turn["running"] and idx >= len(turn["events"]):
                return
            time.sleep(0.2)

    return StreamingResponse(sse(), media_type="text/event-stream")


@app.get("/api/turn-status/{session_id}")
def api_turn_status(session_id: int):
    turn = turns.get(session_id)
    return {"running": bool(turn and turn["running"])}


def sse_event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


@app.get("/static/{fname:path}")
def static_files(fname: str):
    import pathlib
    pkg = pathlib.Path(__file__).parent / "static"
    path = pkg / fname
    if not path.is_file():
        return RedirectResponse("/", status_code=404)
    return FileResponse(path)


@app.get("/files/{fname:path}")
def files(fname: str):
    # ponytail: serves the launch directory as-is; the agent already has
    # full shell access to it, so HTTP read access adds no new risk
    import pathlib
    root = pathlib.Path(_launch_cwd()).resolve()
    path = (root / fname).resolve()
    if not path.is_file() or not str(path).startswith(str(root)):
        return RedirectResponse("/", status_code=404)
    return FileResponse(path)


@app.get("/healthz")
def healthz():
    return {"ok": True}
