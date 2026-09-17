// ponytail: session id lives in the URL, no need for server-rendered attrs
const SESSION_ID = Number(location.pathname.split("/").pop()) || null;
const transcript = document.getElementById("transcript");
const form = document.getElementById("composer");
const input = document.getElementById("chat-input");
const sendBtn = document.getElementById("send");
const modelSwitcher = document.getElementById("model-switcher");
const autoMode = document.getElementById("auto-mode");
const showTools = document.getElementById("show-tools");
const sessionList = document.getElementById("session-list");

let running = false;
let toolPre = null;

// ---------- sessions sidebar (HTMX-rendered <li>s) ----------
document.addEventListener("click", (e) => {
  const li = e.target.closest("#session-list li");
  if (li) location.href = "/chat/" + li.dataset.sid;
});
document.getElementById("new-chat").onclick = () => { location.href = "/"; };
function refreshSessions() { htmx.trigger(document.body, "finity:refresh"); }

// ---------- model switcher ----------
async function loadModels() {
  const res = await fetch("/api/models");
  const data = await res.json();
  const models = data.models || [];
  modelSwitcher.innerHTML = "";
  for (const m of models) {
    const opt = document.createElement("option");
    opt.value = m; opt.textContent = m;
    modelSwitcher.appendChild(opt);
  }
  if (data.current && models.includes(data.current)) {
    modelSwitcher.value = data.current;
  }
}
modelSwitcher.onchange = async () => {
  await fetch(`/api/models/${encodeURIComponent(modelSwitcher.value)}`,
              { method: "POST" });
  loadEffortOptions();
};
loadModels();

const effortSwitcher = document.getElementById("effort-switcher");
effortSwitcher.onchange = async () => {
  await fetch(`/api/effort/${effortSwitcher.value}`, { method: "POST" });
};
fetch("/api/effort").then(r => r.json()).then(d => {
  effortSwitcher.value = d.effort || "default";
});

async function loadEffortOptions() {
  const data = await fetch("/api/reasoning-options")
    .then(r => r.json()).catch(() => ({}));
  const options = data.options || [];
  if (!options.length) return;
  const current = effortSwitcher.value;
  effortSwitcher.innerHTML = "";
  for (const o of options) {
    const opt = document.createElement("option");
    opt.value = o;
    opt.textContent = o === "default" ? "Reasoning: default" : "Reasoning: " + o;
    effortSwitcher.appendChild(opt);
  }
  effortSwitcher.value = options.includes(current) ? current : options[0];
}
loadEffortOptions();

// ---------- transcript replay ----------
async function loadHistory() {
  const msgs = await fetch(`/api/messages/${SESSION_ID}`)
    .then(r => r.json()).then(d => d.messages || []).catch(() => []);
  for (const m of msgs) {
    if (m.role === "user") addUserMsg(m.content);
    else if (m.kind === "html_response" && m.content) renderHtml(m.content);
  }
}
loadHistory();

autoMode.onchange = () =>
  fetch(`/api/auto/${SESSION_ID}?on=${autoMode.checked}`, { method: "POST" });
fetch("/api/auto").then(r => r.json()).then(d => {
  autoMode.checked = !!d.auto;
});

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
  const near = transcript.scrollHeight - transcript.scrollTop -
    transcript.clientHeight < 120;
  if (near) transcript.scrollTop = transcript.scrollHeight;
}

// ---------- HTML response rendering (direct DOM) ----------
function renderHtml(html) {
  // strip ```html / ``` fences if the model wraps fragments
  html = html.replace(/^\s*```(?:html)?\s*\n?/, "").replace(/```\s*$/, "");
  const doc = new DOMParser().parseFromString(html, "text/html");
  const wrap = el("div", "agent-html");
  transcript.appendChild(wrap);
  doc.querySelectorAll("style, link[rel=stylesheet]").forEach((n) =>
    wrap.appendChild(document.importNode(n, true)));
  doc.body.childNodes.forEach((n) =>
    wrap.appendChild(document.importNode(n, true)));
  // scripts don't execute via importNode — re-create them, wrapped so
  // multiple responses don't collide in the page's global scope
  doc.body.querySelectorAll("script").forEach((old) => {
    const sc = document.createElement("script");
    for (const a of old.attributes) sc.setAttribute(a.name, a.value);
    sc.textContent = "(function(){\n" + old.textContent + "\n})();";
    wrap.appendChild(sc);
  });
  if (window.htmx) htmx.process(wrap);
  scroll();
}

// ---------- data-send bridge (delegated) ----------
function widgetSubmit(payload) {
  addWidgetMsg(JSON.stringify(payload));
  if (!running) sendMessage(JSON.stringify(payload), true);
}

transcript.addEventListener("submit", (e) => {
  const form = e.target.closest("form[data-send]");
  if (!form) return;
  e.preventDefault();
  const payload = {};
  new FormData(form).forEach((v, k) => { payload[k] = v; });
  widgetSubmit(payload);
});

transcript.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-send]");
  if (!btn || btn.tagName === "FORM") return;
  e.preventDefault();
  let payload;
  const raw = btn.getAttribute("data-send");
  if (raw) {
    try { payload = JSON.parse(raw); } catch { payload = { value: raw }; }
  }
  widgetSubmit(payload);
});

// surface agent script errors
window.addEventListener("error", (ev) => {
  const chip = el("div", "iframe-error");
  chip.textContent = "Script error in response: " + ev.message;
  transcript.appendChild(chip);
  scroll();
});

// ---------- SSE consumption ----------
async function sendMessage(text, isWidget) {
  if (running || !text.trim()) return;
  running = true;
  sendBtn.disabled = true;
  const cancelBtn = addCancelButton();
  const ctx = { streamEl: null };

  toolPre = null;
  thinkingEl = null;
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
        if (ev) handleEvent(ev, ctx);
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

let thinkingEl = null;

function handleEvent(ev, ctx) {
  const { payload } = ev;
  switch (ev.event) {
    case "user_message":
      addUserMsg(payload.text);
      break;
    case "text_delta":
      ctx.streamBuf = (ctx.streamBuf || "") + payload.text;
      if (ctx.streamBuf.trimStart().startsWith("<")) {
        // HTML fragment incoming — show progress, not raw source
        if (!ctx.streamEl) ctx.streamEl = addStreamText();
        ctx.streamEl.textContent = "⏳ writing interactive response…";
      } else {
        if (!ctx.streamEl) ctx.streamEl = addStreamText();
        ctx.streamEl.textContent = ctx.streamBuf;
      }
      scroll();
      break;
    case "reasoning_delta": {
      if (!thinkingEl) {
        thinkingEl = el("details", "thinking");
        const sum = el("summary");
        sum.textContent = "Thinking";
        const pre = el("pre");
        thinkingEl.appendChild(sum);
        thinkingEl.appendChild(pre);
        transcript.appendChild(thinkingEl);
      }
      thinkingEl.querySelector("pre").textContent += payload.text;
      thinkingEl.open = true;
      scroll();
      break;
    }
    case "tool_call":
      toolPre = addToolCard(payload.command, false);
      break;
    case "approval_request":
      addApprovalCard(payload.command);
      break;
    case "tool_result":
      if (toolPre) {
        toolPre.textContent = payload.output;
        toolPre.parentElement.open = payload.blocked;
      }
      toolPre = null;
      ctx.streamEl = null;
      break;
    case "html_response":
      if (ctx.streamEl) { ctx.streamEl.remove(); ctx.streamEl = null; }
      ctx.streamBuf = "";
      if (thinkingEl) thinkingEl.open = false;
      if (payload.html) {
        // plain-text answers render as a normal message, not a fragment box
        if (/<[a-z][\s\S]*>/i.test(payload.html)) renderHtml(payload.html);
        else {
          const wrap = el("div", "msg assistant");
          const bubble = el("div", "bubble");
          // safety net: models slip markdown into plain text — render it
          let t = payload.html.replace(/&/g, "&amp;").replace(/</g, "&lt;");
          t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
          t = t.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
          t = t.replace(/`([^`\n]+)`/g, "<code>$1</code>");
          t = t.replace(/^### (.*)$/gm, "<strong>$1</strong>");
          bubble.innerHTML = t.replace(/\n/g, "<br>");
          wrap.appendChild(bubble);
          transcript.appendChild(wrap);
          scroll();
        }
      }
      break;
    case "error":
      addStreamText().textContent = "Error: " + payload.message;
      break;
    case "turn_complete":
      refreshSessions();
      break;
  }
  return ctx;
}

// Enter sends; Shift+Enter makes a newline
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
});

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value;
  input.value = "";
  sendMessage(text);
});
