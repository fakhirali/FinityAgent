import html
import json
import re
import threading
import time
import urllib.parse
from collections import defaultdict
from pathlib import Path

from fasthtml.common import *
from fasthtml.pico import picolink
from starlette.responses import FileResponse, Response, StreamingResponse

from . import db, envstore, providers
from .agent import Agent
from .config import PRESETS, Config, load_config, save_config

app = FastHTML(hdrs=(picolink,
                     Link(rel="stylesheet", href="/static/style.css"),
                     Script(src="/static/sse.js?v=3")),
               htmlkw={"data-theme": "dark"})

FINITY_FILES_DIR = Path.home() / ".finityagent" / "files"
FINITY_FILES_DIR.mkdir(parents=True, exist_ok=True)

agents: dict[int, Agent] = {}

# ponytail: one URL = one session id; every fragment renders server-side


def _esc(text) -> str:
    return html.escape(str(text))


def _head(title):
    return (Title(title),)


# ---------- html fragment helpers (all transcripts render server-side) ----------

def _dedupe(mid: int) -> str:
    # replayed SSE events re-append messages the page already renders;
    # a message keeps its db id, so a duplicate removes itself (setTimeout:
    # htmx evaluates swapped scripts before insertion, and without me())
    return (f'<script>setTimeout(function(){{ var n ='
            f' any("#m{mid}"); if (n.length > 1) n[n.length-1].remove()'
            f'}}, 0)</script>')


def _mini_md(text: str) -> str:
    # safety net: models slip markdown into plain-text answers
    t = _esc(text)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\*([^*\n]+)\*", r"<em>\1</em>", t)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    t = re.sub(r"(?m)^### (.*)$", r"<strong>\1</strong>", t)
    return t.replace("\n", "<br>")


def _strip_fences(html: str) -> str:
    html = re.sub(r"^\s*```(?:html)?\s*\n?", "", html)
    return re.sub(r"```\s*$", "", html).rstrip()


def _wrap_scripts(fragment: str) -> str:
    # IIFE-wrap inline scripts so multiple agent responses don't collide
    # in the page's global scope
    return re.sub(
        r"<script(\s[^>]*)?>(.*?)</script>",
        lambda m: f"<script{m.group(1) or ''}>(function(){{{m.group(2)}}})();</script>",
        fragment, flags=re.DOTALL)


def _is_html(text: str) -> bool:
    return bool(re.search(r"<[a-z][\s\S]*>", text, re.I))


def _html_answer(mid: int, content: str) -> str:
    # plain-text answers render as a normal message, not a fragment box
    if not _is_html(content):
        return (f'<div id="m{mid}" class="msg assistant">'
                f'<div class="bubble">{_mini_md(content)}</div>'
                f'{_dedupe(mid)}</div>')
    frag = _wrap_scripts(_strip_fences(content))
    return (f'<div id="m{mid}" class="agent-html">{frag}{_dedupe(mid)}</div>')


def _user_bubble(mid: int, text: str) -> str:
    return (f'<div id="m{mid}" class="msg user"><div class="bubble">'
            f'{_esc(text)}</div>{_dedupe(mid)}</div>')


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

def _session_lis(current: int = 0) -> str:
    return "".join(
        f'<li data-sid="{s.id}"'
        f' class="{"running " if turns.get(s.id, {}).get("running") else ""}'
        f'{"current" if s.id == current else ""}">'
        f'<a href="/chat/{s.id}">{_esc(s.title)}</a>'
        f'<button class="session-x" title="Delete conversation"'
        f' hx-post="/api/hide/{s.id}" hx-target="closest li" hx-swap="delete"'
        f' hx-confirm="Delete this conversation?">×</button></li>'
        for s in db.list_sessions())


def _artifact_lis(session_id: int) -> str:
    return "".join(
        f'<li hx-get="/api/artifact/{a.id}" hx-target="#transcript"'
        f' hx-swap="beforeend">{_esc(a.name)}</li>'
        for a in db.list_artifacts(session_id))


_md_cache = None


def _models_dev():
    global _md_cache
    if _md_cache is None:
        import urllib.request
        req = urllib.request.Request(
            "https://models.dev/api.json",
            headers={"User-Agent": "finityagent/0.1"})
        with urllib.request.urlopen(req, timeout=3) as r:
            _md_cache = json.load(r)
    return _md_cache


def _provider_id(cfg) -> str | None:
    if "opencode.ai/zen" in cfg.base_url:
        return "opencode-go"
    if "api.openai.com" in cfg.base_url:
        return "openai"
    return None


def _effort_options(cfg: Config) -> list[str]:
    # ponytail: levels come from models.dev (what OpenCode uses); unknown
    # providers get the generic OpenAI ladder. toggle/budget_tokens variants
    # are V2 — effort-only for now.
    fallback = ["default", "low", "medium", "high"]
    pid = _provider_id(cfg)
    if not pid:
        return fallback
    try:
        m = _models_dev()[pid]["models"].get(cfg.model, {})
        efforts = [o.get("values", []) for o in m.get("reasoning_options", [])
                   if o.get("type") == "effort"]
    except Exception:  # noqa: BLE001 - offline or unknown provider
        return fallback
    values = efforts[0] if efforts else []
    return ["default", *dict.fromkeys(values)]


def _option_lis(values: list[str], current: str) -> str:
    return "".join(
        f'<option value="{_esc(v)}"{" selected" if v == current else ""}>'
        f'{_esc(v)}</option>' for v in values)


def _composer_inner(session_id: int, running: bool = False) -> str:
    stop = (f'<button id="stop" type="button" hx-post="/api/cancel/'
            f'{session_id}" hx-swap="none">Stop</button>') if running else ""
    return (
        f'<textarea id="chat-input" name="message" rows="1" autocomplete="off"'
        f' placeholder="Ask anything — answers arrive as interactive HTML">'
        f'</textarea>'
        f'<button id="send">Send</button>{stop}'
        f'<input type="file" id="file-input" name="files" multiple'
        f' style="display:none" hx-post="/api/upload/{session_id}"'
        f' hx-encoding="multipart/form-data" hx-trigger="change"'
        f' hx-swap="none">'
        f'<button id="upload-btn" type="button" title="Upload files">📎'
        f'<script>me().on("click", _ => me("#file-input").click())</script>'
        f'</button>')


def _topbar(session_id: int, cfg: Config, sess) -> str:
    try:
        models = providers.list_models(cfg) or [cfg.model]
    except Exception:  # noqa: BLE001 - provider unreachable
        models = [cfg.model]
    if cfg.model not in models:
        models = [cfg.model, *models]
    effort = (sess.effort if sess else "") or cfg.reasoning_effort
    tools_js = ('me().on("change", _ => {'
                ' if (me().checked) { me("body").classRemove("hide-tools") }'
                ' else { me("body").classAdd("hide-tools") } })')
    return (
        '<header id="topbar"><div id="model-switcher-wrap">'
        f'<select id="model-switcher" name="model"'
        f' hx-post="/api/model/{session_id}" hx-swap="none">'
        f'{_option_lis(models, cfg.model)}</select>'
        f'<div id="effort-wrap"><select id="effort-switcher" name="effort"'
        f' hx-post="/api/effort/{session_id}" hx-swap="none">'
        f'{_option_lis(_effort_options(cfg), effort)}</select></div></div>'
        f'<div id="mode-wrap"><label class="switch">'
        f'<input type="checkbox" id="auto-mode" name="on"'
        f' hx-post="/api/auto/{session_id}" hx-swap="none"'
        f'{" checked" if cfg.auto_approve else ""}>Auto</label>'
        f'<label class="switch"><input type="checkbox" id="show-tools"'
        f' checked><script>{tools_js}</script>Tool calls</label></div>'
        '</header>')


def _transcript(session_id: int) -> str:
    msgs = "".join(
        _user_bubble(m.id, m.content)
        if m.role == "user" else _html_answer(m.id, m.content)
        for m in db.get_messages(session_id)
        if m.role in ("user", "assistant") and m.kind in ("text", "html_response")
        and m.content)
    # the empty receiver divs route stream events; oob fragments in event
    # data update stateful pieces (tool output, composer, sidebar) directly
    return (
        f'<div id="transcript" hx-ext="sse" sse-connect="/api/stream/'
        f'{session_id}">{msgs}'
        f'<div sse-swap="turn_start,user_message,text_delta,tool_call,'
        f'tool_result,approval_request,html_response,agent_error,'
        f'turn_complete"'
        f' hx-target="#transcript" hx-swap="beforeend"></div></div>')


def chat_shell(session_id: int, cfg: Config, cwd: str) -> tuple:
    sess = db.get_session(session_id)
    running = bool(turns.get(session_id, {}).get("running"))
    body = (
        '<aside id="sidebar">'
        '<button id="sidebar-toggle" type="button">☰'
        '<script>me().on("click", _ => me("#sidebar").classToggle("open"))'
        '</script></button>'
        '<a href="/"><button id="new-chat" type="button">+ New chat</button></a>'
        f'<ul id="session-list" hx-get="/api/sessions-list/{session_id}"'
        f' hx-trigger="load" hx-swap="innerHTML">{_session_lis(session_id)}</ul>'
        '<h3>Artifacts</h3>'
        f'<ul id="artifact-list">{_artifact_lis(session_id)}</ul>'
        '</aside>'
        '<main id="main">'
        f'{_topbar(session_id, cfg, sess)}'
        f'{_transcript(session_id)}'
        f'<form id="composer" hx-post="/api/chat/{session_id}"'
        f' hx-target="#transcript" hx-swap="beforeend">'
        f'{_composer_inner(session_id, running)}</form>'
        '</main>'
        # composer behavior lives at page level: the composer form is oob-
        # swapped mid-turn, and htmx-evaluated scripts have no parent
        # context (document-level listeners survive every swap)
        '<script>(() => {\n'
        '  document.addEventListener("keydown", ev => {\n'
        '    if (ev.target?.id !== "chat-input" || ev.key !== "Enter"\n'
        '        || ev.shiftKey) { return }\n'
        '    ev.preventDefault()\n'
        '    ev.target.closest("form").requestSubmit() })\n'
        '  document.addEventListener("htmx:afterRequest", ev => {\n'
        '    if (ev.target?.id !== "composer"\n'
        '        || !ev.detail.successful) { return }\n'
        '    const i = document.getElementById("chat-input")\n'
        '    if (i) { i.value = ""; i.focus() } })\n'
        '})()</script>'
        # keep the transcript pinned to the newest content
        '<script>me("#transcript").on("htmx:afterSwap", () => {'
        ' const t = me("#transcript");'
        ' if (t.scrollHeight - t.scrollTop - t.clientHeight < 240)'
        ' t.scrollTop = t.scrollHeight })</script>'
        # drop / paste file uploads (htmx covers the file-picker path)
        '<script>(() => {\n'
        '  const t = me("#transcript")\n'
        '  const upload = files => {\n'
        '    if (!files.length) { return }\n'
        '    const fd = new FormData()\n'
        '    for (const f of files) { fd.append("files", f) }\n'
        f'    fetch("/api/upload/{session_id}", {{ method: "POST", body: fd }})\n'
        '  }\n'
        '  t.on("dragover", ev => { halt(ev); t.classAdd("dragging") })\n'
        '  t.on("dragleave", ev => t.classRemove("dragging"))\n'
        '  t.on("drop", ev => { halt(ev); t.classRemove("dragging")\n'
        '    upload([...ev.dataTransfer.files]) })\n'
        '  me("body").on("paste", ev => {\n'
        '    const files = [...(ev.clipboardData?.files || [])]\n'
        '    if (files.length) { halt(ev); upload(files) } })\n'
        '})()</script>')
    return Title("FinityAgent"), Div(NotStr(body), id="app")


@app.get("/")
def index():
    cfg = load_config()
    if not cfg.is_configured:
        return RedirectResponse("/setup", status_code=303)
    cwd = _launch_cwd()
    session_id = db.create_session(cwd=cwd, model=cfg.model)
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


# ---------- API (HTML in, HTML out — htmx speaks fragments) ----------

@app.get("/api/sessions-list/{current}")
def api_sessions_list(current: int = 0):
    return Response(_session_lis(current), media_type="text/html")


@app.get("/api/messages/{session_id}")
def api_messages(session_id: int):
    return {"messages": [
        {"role": m.role, "content": m.content, "kind": m.kind, "meta": m.meta,
         "id": m.id}
        for m in db.get_messages(session_id)]}


@app.get("/api/wizard-models")
def wizard_models(base_url: str, api_key: str = ""):
    cfg = Config(base_url=base_url.strip(), api_key=api_key.strip(),
                 model="", preset="custom")
    return {"models": providers.list_models(cfg)}


@app.post("/api/model/{session_id}")
def api_model(session_id: int, model: str):
    cfg = load_config()
    cfg.model = model
    save_config(cfg)
    for agent in agents.values():
        agent.model = model
    sess = db.get_session(session_id)
    if sess:
        db.update_session(session_id, model=model)
    # effort options depend on the model — swap the select out of band
    return Response(
        f'<div id="effort-wrap" hx-swap-oob="true"><select id="effort-switcher"'
        f' name="effort" hx-post="/api/effort/{session_id}" hx-swap="none">'
        f'{_option_lis(_effort_options(cfg), "default")}</select></div>',
        media_type="text/html")


@app.post("/api/effort/{session_id}")
def api_effort(session_id: int, effort: str):
    if effort in _effort_options(load_config()):
        cfg = load_config()
        cfg.reasoning_effort = effort
        save_config(cfg)
        for agent in agents.values():
            agent.reasoning_effort = effort
        sess = db.get_session(session_id)
        if sess:
            db.update_session(session_id, effort=effort)
    return Response(status_code=204)


# ---------- env-var store (platform credentials) ----------

@app.get("/api/env")
def api_env():
    return {"keys": envstore.list_keys()}  # values never leave the server


@app.post("/api/env/{key}")
def api_env_set(key: str, value: str):
    envstore.set_var(key, value)
    return {"ok": True}


@app.delete("/api/env/{key}")
def api_env_del(key: str):
    return {"ok": envstore.remove_var(key)}


# ---------- artifacts ----------

@app.get("/api/artifact/{artifact_id}")
def api_artifact(artifact_id: int):
    a = db.get_artifact(artifact_id)
    if a is None:
        return Response("not found", status_code=404)
    return Response(f'<div class="artifact-open"><pre>{_esc(a.content[:5000])}'
                    '</pre></div>', media_type="text/html")


@app.post("/api/artifact/{session_id}")
def api_artifact_save(session_id: int, name: str, content: str):
    aid = db.save_artifact(session_id, name.strip(), content)
    return {"ok": True, "id": aid}


@app.delete("/api/artifact/{artifact_id}")
def api_artifact_del(artifact_id: int):
    a = db.get_artifact(artifact_id)
    if a:
        a.delete()
    return {"ok": True}


# ---------- sessions ----------

@app.post("/api/hide/{session_id}")
def api_hide(session_id: int):
    db.update_session(session_id, hidden=1)
    return Response(status_code=204)


@app.post("/api/approve/{session_id}")
def api_approve(session_id: int, decision: str, prefix: str = ""):
    agent = agents.get(session_id)
    if agent:
        agent.resolve_approval(decision, prefix or None)
    return Response(status_code=204)


@app.post("/api/auto/{session_id}")
def api_auto(session_id: int, on: bool = False):
    cfg = load_config()
    cfg.auto_approve = on
    save_config(cfg)
    for agent in agents.values():
        agent.auto_approve = on
    return Response(status_code=204)


@app.post("/api/upload/{session_id}")
def api_upload(session_id: int, files: list[UploadFile]):
    saved = []
    for f in files:
        name = Path(f.filename or "upload").name  # no traversal
        dest = FINITY_FILES_DIR / f"s{session_id}-{name}"
        dest.write_bytes(f.file.read())
        saved.append(str(dest))
    # surface the paths to the agent as a user turn
    note = "[user uploaded files] " + ", ".join(saved)
    _new_user_message(session_id, note)
    return Response(status_code=204)


@app.post("/api/cancel/{session_id}")
def api_cancel(session_id: int):
    agent = agents.get(session_id)
    if agent:
        agent.cancel()
    return Response(status_code=204)


# ---------- turns ----------

queued: dict[int, list] = {}  # session_id -> [str messages] waiting for the turn

_tool_seq: dict[int, int] = defaultdict(int)  # stable tool-card ids per session


def _turn(session_id: int) -> dict:
    return turns.setdefault(session_id, {
        "events": [], "running": False,
        "cond": threading.Condition(), "tool_n": 0,
        "stream_open": False, "stream_buf": "",
        "think_open": False, "think_n": 0})


def _slash_to_skill(message: str) -> str:
    # /skillname rest → instruct agent to load that skill
    m = re.match(r"^/([\w-]+)\s*([\s\S]*)$", message)
    return f"[skill: {m[1]}] {m[2]}" if m else message


def _new_user_message(session_id: int, message: str) -> Response:
    message = _slash_to_skill(message)
    if session_id in turns and turns[session_id]["running"]:
        # queued messages get their own follow-up turn; persisted when the
        # queued turn actually starts (keeps transcript chronology right)
        queued.setdefault(session_id, []).append(message)
        return Response(status_code=204)
    cfg = load_config()
    agent = agents.get(session_id)
    if agent is None:
        sess = db.get_session(session_id)
        agent = Agent(providers.make_client(cfg, session_id),
                      (sess.model if sess else "") or cfg.model,
                      sess.cwd if sess else ".",
                      reasoning_effort=(sess.effort if sess else "")
                      or cfg.reasoning_effort,
                      session_id=session_id)
    agents[session_id] = agent
    agent.cancel_flag.clear()
    # session pins win; global config is only the fallback
    sess = db.get_session(session_id)
    agent.model = (sess.model if sess else "") or cfg.model
    agent.reasoning_effort = (sess.effort if sess else "") \
        or cfg.reasoning_effort
    agent.auto_approve = cfg.auto_approve

    from . import memory as memory_mod
    mem = memory_mod.read_memory()
    prefix = ([{"role": "user",
                "content": "[persistent memory]\n" + mem,
                }] if mem.strip() else [])
    history = prefix + [
        {"role": m.role, "content": m.content}
        for m in db.get_messages(session_id)
        if m.role in ("user", "assistant")
        and m.kind in ("text", "html_response") and m.content
    ]
    mid = db.add_message(session_id, "user", message)
    if db.get_session(session_id).title == "New chat":
        db.update_session(session_id, title=message[:60])
    history.append({"role": "user", "content": message})

    # pin the model/effort actually used by this conversation
    if sess is not None:
        db.update_session(session_id, model=agent.model,
                          effort=agent.reasoning_effort)

    turn = _turn(session_id)
    turn["events"] = []
    turn["running"] = True
    # the composer's running state and the user bubble both travel over
    # the stream — every client (browser tab or CLI-injected turn) shows it
    turn["events"].append(("turn_start",
                           f'<form id="composer" hx-swap-oob="true">'
                           f'{_composer_inner(session_id, True)}</form>'))
    turn["events"].append(("user_message", _user_bubble(mid, message)))
    threading.Thread(target=_run_turn,
                     args=(session_id, agent, history), daemon=True).start()
    return Response(status_code=204)


@app.post("/api/chat/{session_id}")
def api_chat(session_id: int, message: str):
    return _new_user_message(session_id, message)


@app.post("/api/widget/{session_id}")
async def api_widget(session_id: int, req):
    form = await req.form()
    payload = json.dumps({k: form[k] for k in form})
    return _new_user_message(session_id, "[widget response] " + payload)


turns: dict[int, dict] = {}


def _render_event(session_id: int, etype: str, event: dict) -> str:
    t = turns[session_id]
    if etype == "user_message":
        return _user_bubble(event["id"], event["text"])
    if etype == "text_delta":
        t["stream_buf"] += event["text"]
        shown = ("⏳ writing interactive response…"
                 if "<" in t["stream_buf"] else t["stream_buf"])
        esc = _esc(shown)
        if t["stream_open"]:
            return f'<span hx-swap-oob="beforeend:#stream-bubble">{esc}</span>'
        t["stream_open"] = True
        return f'<div id="stream-bubble" class="msg stream-text">{esc}</div>'
    if etype == "reasoning_delta":
        if t["think_open"]:
            return (f'<span hx-swap-oob="beforeend:'
                    f'#thinking-pre-{t["think_n"]}">{_esc(event["text"])}</span>')
        t["think_n"] += 1
        t["think_open"] = True
        n = t["think_n"]
        return (f'<details class="thinking" open id="thinking-{n}">'
                f'<summary>Thinking</summary>'
                f'<pre id="thinking-pre-{n}">{_esc(event["text"])}</pre>'
                '</details>')
    if etype == "tool_call":
        had_stream = t["stream_open"]
        t["stream_open"] = False
        t["stream_buf"] = ""
        t["think_open"] = False
        _tool_seq[session_id] += 1
        n = t["tool_n"] = _tool_seq[session_id]
        t["tool_cmd"] = event["command"]
        card = (f'<details class="tool-card" id="tool-{n}"><summary>'
                f'<span class="cmd">$ {_esc(event["command"])}</span>'
                f'</summary><pre id="tool-pre-{n}"></pre></details>')
        return (f'<div id="stream-bubble" hx-swap-oob="delete"></div>{card}'
                if had_stream else card)
    if etype == "tool_result":
        n = t["tool_n"]
        if not n:
            return ""
        if event.get("blocked"):
            return (f'<details class="tool-card" open id="tool-{n}"'
                    f' hx-swap-oob="true"><summary><span class="cmd">$ '
                    f'{_esc(t["tool_cmd"])}  [blocked/skipped]</span></summary>'
                    f'<pre>{_esc(event["output"])}</pre></details>')
        return (f'<pre id="tool-pre-{n}" hx-swap-oob="true">'
                f'{_esc(event["output"])}</pre>')
    if etype == "approval_request":
        p = urllib.parse.quote(event.get("prefix", ""), safe="")
        btn = (lambda d, label: f'<button hx-post="/api/approve/{session_id}'
               f'?decision={d}&amp;prefix={p}" hx-target="closest .approval-card"'
               f' hx-swap="delete">{label}</button>')
        return (f'<div class="approval-card"><div class="cmd">'
                f'{_esc(event["command"])}</div><div class="actions">'
                f'{btn("allow", "Run")}{btn("always", "Always this session")}'
                f'{btn("skip", "Skip")}</div></div>')
    if etype == "html_response":
        had_stream = t["stream_open"]
        t["stream_open"] = False
        t["stream_buf"] = ""
        content = event.get("html") or ""
        if not content:
            return ""
        mid = event.get("id")
        frag = _html_answer(mid, content)
        return (f'<div id="stream-bubble" hx-swap-oob="delete"></div>{frag}'
                if had_stream else frag)
    if etype == "error":
        t["stream_open"] = False
        t["stream_buf"] = ""
        return (f'<div class="msg stream-text">Error: '
                f'{_esc(event["message"])}</div>')
    if etype == "turn_complete":
        return (f'<form id="composer" hx-swap-oob="true">'
                f'{_composer_inner(session_id, False)}</form>'
                f'<ul id="session-list" hx-swap-oob="true">'
                f'{_session_lis(session_id)}</ul>'
                f'<ul id="artifact-list" hx-swap-oob="true">'
                f'{_artifact_lis(session_id)}</ul>')
    return ""


def _run_turn(session_id: int, agent: Agent, history: list):
    turn = _turn(session_id)

    def emit(etype: str, fragment: str) -> None:
        if not fragment:
            return
        turn["events"].append((etype, fragment))
        with turn["cond"]:
            turn["cond"].notify_all()

    def run_generator(history):
        try:
            for event in agent.run_turn(history):
                etype = event.pop("type")
                # "error" is also EventSource's native event name — native
                # error events (reconnects) carry no data, so agent errors
                # stream under a distinct name
                if etype == "error":
                    etype = "agent_error"
                if etype == "html_response":
                    content = event.get("html", "")
                    if content and re.search(
                            r"<(?:script|style|canvas|form|svg|table|video)\b",
                            content):
                        # interactive/complex responses become artifacts
                        n = len(db.list_artifacts(session_id)) + 1
                        db.save_artifact(session_id, f"artifact-{n}", content)
                    event["id"] = db.add_message(session_id, "assistant",
                                                 content, kind="html_response")
                emit(etype, _render_event(session_id, etype, event))
        except Exception as e:  # noqa: BLE001 - turn must always complete
            emit("agent_error", _render_event(
                session_id, "error", {"message": str(e)}))

    try:
        run_generator(history)
        # queued messages (sent mid-turn) get their own follow-up turn;
        # persisted here so they sit after the previous response in the
        # transcript, then announced per message so every tab shows them
        while True:
            pending = queued.pop(session_id, None)
            if not pending:
                break
            for msg in pending:
                mid = db.add_message(session_id, "user", msg)
                emit("user_message", _render_event(
                    session_id, "user_message", {"id": mid, "text": msg}))
            run_generator([
                {"role": m.role, "content": m.content}
                for m in db.get_messages(session_id)
                if m.role in ("user", "assistant")
                and m.kind in ("text", "html_response") and m.content
            ])
    finally:
        emit("turn_complete", _render_event(session_id, "turn_complete", {}))
        agents.pop(session_id, None)
        turn["running"] = False
        with turn["cond"]:
            turn["cond"].notify_all()


@app.get("/api/stream/{session_id}")
def api_stream(session_id: int):
    # ponytail: one open thread per tab; the connection persists between
    # turns and picks up the next one when it starts (5Hz poll, trivial load)
    def sse():
        yield "retry: 1000\n\n"
        while True:
            turn = turns.get(session_id)
            if turn is None:
                time.sleep(0.5)
                continue
            idx = 0
            while True:
                events = turn["events"]
                while idx < len(events):
                    etype, fragment = events[idx]
                    idx += 1
                    yield sse_event(etype, fragment)
                if not turn["running"] and idx >= len(events):
                    break
                time.sleep(0.2)
            turns.pop(session_id, None)  # done — wait for the next turn
            time.sleep(0.5)

    return StreamingResponse(sse(), media_type="text/event-stream")


@app.get("/api/turn-status/{session_id}")
def api_turn_status(session_id: int):
    turn = turns.get(session_id)
    return {"running": bool(turn and turn["running"])}


def sse_event(name: str, fragment: str) -> str:
    # SSE data must be one logical line — prefix every fragment line
    data = "".join(f"data: {line}\n" for line in fragment.split("\n"))
    return f"event: {name}\n{data}\n"


@app.get("/static/{fname:path}")
def static_files(fname: str):
    import pathlib
    pkg = pathlib.Path(__file__).parent / "static"
    path = pkg / fname
    if not path.is_file():
        return RedirectResponse("/", status_code=404)
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@app.get("/files/{fname:path}")
def files(fname: str):
    # ponytail: serves ~/.finityagent/files/ plus anything the agent
    # symlinks into it (no copies for big files); ".." is rejected so
    # traversal stays blocked
    if ".." in fname.split("/") or fname.startswith("/"):
        return RedirectResponse("/", status_code=404)
    path = FINITY_FILES_DIR / fname
    if not path.is_file():
        return RedirectResponse("/", status_code=404)
    return FileResponse(path)


@app.get("/healthz")
def healthz():
    return {"ok": True}
