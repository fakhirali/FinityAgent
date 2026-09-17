import json

from fasthtml.common import *
from starlette.responses import FileResponse, StreamingResponse

from . import db, providers
from .agent import Agent
from .config import PRESETS, Config, load_config, save_config

app = FastHTML(pico=False, default_hdrs=False,
               hdrs=(Link(rel="stylesheet", href="/static/style.css"),))

agents: dict[int, Agent] = {}


def _head(title):
    return (Title(title),
            Link(rel="stylesheet", href="/static/style.css"))


# ---------- wizard ----------

def wizard_page(error: str = ""):
    options = [Option(v["label"], value=k, selected=(k == "opencode-go"))
               for k, v in PRESETS.items()]
    err = P(error, cls="error") if error else None
    return _head("FinityAgent Setup"), Div(
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
            Input(name="model", id="model", required=True,
                  placeholder="kimi-k3"),
            Button("Start", type="submit"),
            err,
            action="/setup", method="post", id="setup-form"),
        Script(src="/static/wizard.js"),
        cls="setup-card")


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
    return _head("FinityAgent"), Div(
        Aside(
            Button("+ New chat", id="new-chat"),
            Ul(id="session-list"),
            id="sidebar"),
        Main(
            Header(
                Div(Select(id="model-switcher"), id="model-switcher-wrap"),
                Div(
                    Label(Input(type="checkbox", id="auto-mode"), " Auto",
                          cls="switch"),
                    Label(Input(type="checkbox", id="show-tools",
                                checked=True), " Tool calls", cls="switch"),
                    id="mode-wrap"),
                id="topbar"),
            Div(id="transcript"),
            Form(
                Input(id="chat-input", autocomplete="off",
                      placeholder="Ask anything — answers arrive as "
                                  "interactive HTML"),
                Button("Send", id="send", type="submit"),
                id="composer"),
            id="main"),
        id="app") + (
        Script(src="/static/app.js"),
        Body_attrs(session=str(session_id), cwd=cwd))


def Body_attrs(**attrs):
    """Attach data attributes to <body> via a marker script."""
    import json as _json
    data = _json.dumps(attrs)
    return Script(f"document.body.dataset = Object.assign("
                  f"document.body.dataset, {data});")


@app.get("/")
def index():
    cfg = load_config()
    if not cfg.is_configured:
        return RedirectResponse("/setup", status_code=303)
    cwd = _launch_cwd()
    session_id = db.create_session(cwd=cwd, model=cfg.model)
    return chat_shell(session_id, cfg, cwd)


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

@app.get("/api/sessions")
def api_sessions():
    return [{"id": s.id, "title": s.title} for s in db.list_sessions()]


@app.get("/api/messages/{session_id}")
def api_messages(session_id: int):
    return [{"role": m.role, "content": m.content, "kind": m.kind,
             "meta": m.meta} for m in db.get_messages(session_id)]


@app.get("/api/models")
def api_models():
    cfg = load_config()
    return providers.list_models(cfg)


@app.post("/api/models/{model}")
def api_set_model(model: str):
    cfg = load_config()
    cfg.model = model
    save_config(cfg)
    return {"ok": True}


@app.post("/api/approve/{session_id}")
def api_approve(session_id: int, decision: str, prefix: str = ""):
    agent = agents.get(session_id)
    if agent:
        agent.resolve_approval(decision, prefix or None)
    return {"ok": True}


@app.post("/api/cancel/{session_id}")
def api_cancel(session_id: int):
    agent = agents.get(session_id)
    if agent:
        agent.cancel()
    return {"ok": True}


@app.post("/api/chat/{session_id}")
def api_chat(session_id: int, message: str):
    import asyncio
    from starlette.responses import StreamingResponse

    cfg = load_config()
    agent = agents.get(session_id)
    if agent is None:
        sess = db.get_session(session_id)
        agent = Agent(providers.make_client(cfg),
                      sess.model or cfg.model, sess.cwd)
        agents[session_id] = agent
    agent.cancel_flag.clear()

    history = [
        {"role": m.role, "content": m.content}
        for m in db.get_messages(session_id)
        if m.role in ("user", "assistant")
        and m.kind in ("text", "html_response")
    ]
    db.add_message(session_id, "user", message)
    history.append({"role": "user", "content": message})

    def sse():
        yield sse_event("user_message", {"text": message})
        final_html = ""
        for event in agent.run_turn(history):
            etype = event.pop("type")
            if etype == "html_response":
                final_html = event.get("html", "")
                event["html"] = ""
            yield sse_event(etype, event)
        if final_html:
            db.add_message(session_id, "assistant", final_html,
                           kind="html_response")
        yield sse_event("turn_complete", {})

    return StreamingResponse(sse(), media_type="text/event-stream")


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


@app.get("/healthz")
def healthz():
    return {"ok": True}
