const sessionEl = document.body;
const SESSION_ID = Number(sessionEl.dataset.session);
const transcript = document.getElementById("transcript");
const form = document.getElementById("composer");
const input = document.getElementById("chat-input");
const sendBtn = document.getElementById("send");
const modelSwitcher = document.getElementById("model-switcher");
const autoMode = document.getElementById("auto-mode");
const showTools = document.getElementById("show-tools");
const sessionList = document.getElementById("session-list");

let running = false;
let pendingApprovalId = null;
const cancellers = new Set();
const IFRAME_RUNTIME_SRC = "/static/iframe-runtime.js";

// ---------- sessions sidebar ----------
async function loadSessions() {
  const res = await fetch("/api/sessions");
  const sessions = await res.json();
  sessionList.innerHTML = "";
  for (const s of sessions) {
    const li = document.createElement("li");
    li.textContent = s.title;
    if (s.id === SESSION_ID) li.classList.add("active");
    li.onclick = () => { location.href = "/chat/" + s.id; };
    sessionList.appendChild(li);
  }
}
document.getElementById("new-chat").onclick = () => { location.href = "/"; };
loadSessions();

// ---------- model switcher ----------
async function loadModels() {
  const res = await fetch("/api/models");
  const models = await res.json();
  modelSwitcher.innerHTML = "";
  for (const m of models) {
    const opt = document.createElement("option");
    opt.value = m; opt.textContent = m;
    modelSwitcher.appendChild(opt);
  }
}
modelSwitcher.onchange = async () => {
  await fetch(`/api/models/${encodeURIComponent(modelSwitcher.value)}`,
              { method: "POST" });
};
loadModels();

// ---------- transcript rendering ----------
function el(tag, cls) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  return e;
}

function addUserMsg(text) {
  const wrap = el("div", "msg user");
  const bubble = el("div", "bubble");
  bubble.textContent = text;
  wrap.appendChild(bubble);
  transcript.appendChild(wrap);
  scroll();
}

function addWidgetMsg(jsonText) {
  const wrap = el("div", "msg widget");
  const bubble = el("div", "bubble");
  bubble.textContent = "[widget response] " + jsonText;
  wrap.appendChild(bubble);
  transcript.appendChild(wrap);
  scroll();
}

function addStreamText() {
  const e = el("div", "msg stream-text");
  transcript.appendChild(e);
  return e;
}

function addToolCard(command, blocked) {
  if (!showTools.checked) return null;
  const card = el("details", "tool-card" + (blocked ? " blocked" : ""));
  const summary = el("summary");
  const prefix = el("span", "cmd");
  prefix.textContent = "$ " + (blocked ? command + "  [blocked/skipped]" : command);
  summary.appendChild(prefix);
  const pre = el("pre");
  card.appendChild(summary);
  card.appendChild(pre);
  transcript.appendChild(card);
  card.open = false;
  scroll();
  return pre;
}

function addApprovalCard(command) {
  const card = el("div", "approval-card");
  const cmd = el("div", "cmd");
  cmd.textContent = command;
  const actions = el("div", "actions");
  const mk = (label, decision, cls) => {
    const b = el("button", cls || "");
    b.textContent = label;
    b.onclick = () => {
      fetch(`/api/approve/${SESSION_ID}?decision=${decision}` +
            `&prefix=${encodeURIComponent(cmdPrefix(command))}`,
            { method: "POST" });
      card.remove();
    };
    return b;
  };
  actions.appendChild(mk("Run", "allow", "primary"));
  actions.appendChild(mk("Always this session", "always"));
  actions.appendChild(mk("Skip", "skip"));
  card.appendChild(cmd);
  card.appendChild(actions);
  transcript.appendChild(card);
  scroll();
}

function cmdPrefix(command) {
  const parts = command.trim().split(/\s+/);
  return parts.slice(0, 2).join(" ");
}

function scroll() {
  transcript.scrollTop = transcript.scrollHeight;
}

// ---------- iframe rendering ----------
function renderHtml(html) {
  const wrap = el("div", "html-frame-wrap");
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-scripts allow-forms");
  frame.style.height = "480px";
  wrap.appendChild(frame);
  transcript.appendChild(wrap);
  const doc = frame.contentDocument;
  doc.open();
  doc.write(injectRuntime(html));
  doc.close();
  scroll();
}

function injectRuntime(html) {
  const tag = `<script src="${IFRAME_RUNTIME_SRC}"></script>`;
  if (/<\/body>/i.test(html)) return html.replace(/<\/body>/i, tag + "</body>");
  return html + tag;
}

window.addEventListener("message", (ev) => {
  if (ev.data && ev.data.type === "finity:resize") {
    const frame = document.querySelector(`iframe[data-fid="${ev.data.fid}"]`);
    if (frame && ev.data.height) frame.style.height = ev.data.height + "px";
  }
  if (ev.data && ev.data.type === "finity:send") {
    addWidgetMsg(JSON.stringify(ev.data.payload));
    if (!running) sendMessage(JSON.stringify(ev.data.payload), true);
  }
});

// assign frame ids so runtime resize messages can find frames
const origRender = renderHtml;
renderHtml = function (html) {
  const before = transcript.querySelectorAll("iframe").length;
  origRender(html);
  const frames = transcript.querySelectorAll("iframe");
  frames[before].dataset.fid = String(before);
};

// ---------- SSE consumption ----------
async function sendMessage(text, isWidget) {
  if (running || !text.trim()) return;
  running = true;
  sendBtn.disabled = true;
  const cancelBtn = addCancelButton();
  let streamEl = null;

  try {
    const res = await fetch(`/api/chat/${SESSION_ID}`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ message: text }),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const ev = parseSse(raw);
        if (!ev) continue;
        ({ streamEl } = handleEvent(ev, { streamEl, cancelBtn }));
      }
    }
  } catch (e) {
    console.error(e);
  } finally {
    cancelBtn.remove();
    running = false;
    sendBtn.disabled = false;
    input.focus();
  }
}

function addCancelButton() {
  const b = el("button", "");
  b.id = "cancel";
  b.textContent = "Stop";
  b.style.cssText = "background:var(--danger);border:0;color:#fff;" +
    "padding:10px 18px;border-radius:8px;cursor:pointer;font-weight:600";
  b.onclick = () => fetch(`/api/cancel/${SESSION_ID}`, { method: "POST" });
  form.appendChild(b);
  return b;
}

function parseSse(raw) {
  let event = "message", data = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!data) return null;
  let payload;
  try { payload = JSON.parse(data); } catch { return null; }
  return { event, payload };
}

function handleEvent(ev, ctx) {
  const { payload } = ev;
  switch (ev.event) {
    case "user_message":
      addUserMsg(payload.text);
      break;
    case "text_delta":
      if (!ctx.streamEl) ctx.streamEl = addStreamText();
      ctx.streamEl.textContent += payload.text;
      scroll();
      break;
    case "tool_call": {
      ctx.toolPre = addToolCard(payload.command, false);
      break;
    }
    case "approval_request":
      addApprovalCard(payload.command);
      break;
    case "tool_result":
      if (ctx.toolPre) {
        ctx.toolPre.textContent = payload.output;
        ctx.toolPre.parentElement.open = payload.blocked;
      } else {
        addToolCard("(earlier command)", payload.blocked);
      }
      ctx.toolPre = null;
      if (ctx.streamEl) { ctx.streamEl = null; }
      break;
    case "html_response":
      if (payload.html) renderHtml(payload.html);
      break;
    case "error":
      addStreamText().textContent = "Error: " + payload.message;
      break;
    case "turn_complete":
      loadSessions();
      break;
  }
  return ctx;
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value;
  input.value = "";
  sendMessage(text);
});
