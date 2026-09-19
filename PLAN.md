# FinityAgent — Implementation Plan

Local agent harness, Python-only. Chat in the browser; agent has exactly one
tool (bash) and responds with visual, interactive HTML.

## General preferences

### Web interface
- Built with FastHTML + HTMX, used to the fullest (htmx events, partials, hx-swap, etc.)
- Avoid standalone JS and CSS files as much as possible
- If JS is unavoidable, use inline JS (e.g. Surreal.js)
- Interface stays simple and effective

### Agent design
- The agent has a single tool: bash. No other tools.
- The system prompt is where the versatility lives: it teaches unique ways to
  use bash for different effects —
  - scheduled workflows (cron via bash)
  - serving files to the user (`/files/`)
  - accessing skills and memory
  - web search, data processing, background processes, etc.
- The prompt also states what is not safe (deny-list behavior)

## Implemented (V1)

### Core
- [x] **Agent loop** — stream model → tool call → bash → repeat (`agent.py`)
- [x] **Bash tool** — `/bin/bash -c`, 120s default / 600s max timeout,
      30k output tail cap, process-group kill, cancel support (`tools.py`)
- [x] **OpenAI-compatible providers** — official `openai` SDK, `base_url`
      override; tested against OpenCode Go; `User-Agent` + stable
      `x-opencode-session` headers; reasoning levels via `reasoning_effort`
- [x] **Streaming** — per-token SSE (model → server → browser); live text,
      reasoning ("Thinking" block), tool cards, approval cards
- [x] **Background turns** — turns run in a server-side thread decoupled
      from the browser: switching chats or closing the tab doesn't kill a
      turn; reconnect replays events; concurrent conversations supported
- [x] **Cancel** — Stop button kills running process group and unblocks
      approval waits
- [x] **Persistence** — SQLite via fastlite at `~/.finityagent/sessions.db`;
      sidebar (HTMX partials) + transcript replay (user messages, HTML
      responses) on load; sessions auto-titled from first message
- [x] **CLI** — `finityagent` zero-arg: start server on port 8377 +
      auto-open browser; `--port`, `--cwd`, `--no-browser`

### UI / UX
- [x] **First-run wizard** — centered card, provider presets
      (OpenCode Go / OpenAI / Custom) prefill base URL; model dropdown
      populated from the endpoint's `/v1/models`; API key entered in UI
      (stored in `~/.finityagent/config.toml`)
- [x] **Chat UI** — Pico CSS dark theme; sidebar, composer with textarea
      (Enter sends, Shift+Enter newline, auto-grow), free scroll during
      generation
- [x] **Tool-call visibility toggle** — collapsible `$ …` cards; never
      hides approval cards
- [x] **Approval system** — Approve all (default) / Auto (YOLO) toggle,
      persisted in config; approval cards: Run / Always this session / Skip;
      hardcoded deny list always enforced (`sudo`, `rm -rf /`, fork bombs,
      `curl | sh`, etc.)
- [x] **Model switcher** — dropdown from `/v1/models`, persisted globally,
      applied live across sessions
- [x] **Reasoning levels** — per-model options fetched from models.dev
      (default/none/low/medium/high/xhigh/max), persisted globally
- [x] **Reasoning traces** — captures `reasoning_content` (DeepSeek) and
      `reasoning` (Kimi/GLM) into a collapsible Thinking block
- [x] **Plain-text answers** — simple questions answered as plain text
      (no HTML, no bash); inline-markdown safety net renders bold/italic/
      code if a model slips
- [x] **HTML-in-DOM responses** — no iframes; agent fragments inserted
      directly into the transcript, scripts re-executed in IIFEs (no global
      collisions), CDN scripts/stylesheets work, htmx processed
- [x] **Error surfacing** — agent script errors show as inline chips
- [x] **HTML hidden while generating** — "⏳ writing interactive
      response…" placeholder; Thinking view stays visible
- [x] **`/files/` serving** — `~/.finityagent/files/` served at
      `/files/<name>`; symlinks supported (no copies for external files);
      `..` traversal blocked
- [x] **htmx widget bridge** — `<button hx-post="/api/widget/<sid>"
      hx-vals='{json}'>` and `<form hx-post="/api/widget/<sid">` submit
      back as `[widget response] {...}` user turns; multi-step widgets
      capture choices in an inline surreal.js script
- [x] **Wider layout** — content spans ~1350px

### System prompt (restructured)
- Response format: plain text for simple answers, otherwise HTML fragment
  (no markdown, no ``` fences); minimal CSS, scoped; CDN libraries
  preferred, search for one if unsure; IIFE script rules
- Interactivity: visual-first for data; JS-on-the-fly or bash/python
  compute-and-store; hyperlinks; cite web sources
- Files: assets must be copied/symlinked into `~/.finityagent/files/` and
  referenced as `/files/<name>`; never inline large datasets
- Bash usage; Skills (~/.finityagent, ./.finityagent, ~/.claude/skills,
  ~/.agents/skills — SKILL.md + frontmatter)
- Web search moved out of the prompt into a real skill: the server now
  seeds `~/.finityagent/skills/websearch.md` on startup if missing
  (Bing scrape via curl — DuckDuckGo serves bots a CAPTCHA — plus the
  DDG instant-answer API for quick facts, citations)

### Testing
- [x] 57 pytest tests: config, permissions, tools, db, agent decisions
- [x] Playwright verification of wizard, chat flow, approval cards,
      widget round-trip, persistence, background turns, file serving
- [x] Demo video recorded (`/tmp/finity-demo.webm`)

## Not yet implemented

### Near-term
- [x] Queue messages while a turn is running (send into the running
      conversation; agent processes them after the current turn finishes)
- [x] Compaction for context compression (summarize old turns into a
      compact summary to keep long sessions within the context window)
- [x] Links in agent HTML always open in a new tab (target=_blank, or
      enforced platform-side)
- [x] Artifacts: persist agent HTML responses as named, editable objects
      the user and agent can iterate on (like Claude artifacts), instead of
      one-shot fragments
- [x] File uploads in the chat (drop files into the UI; agent gets the
      path, uploads land in ~/.finityagent/files/)
- [x] Platform env-var store (Hermes-style): agent can save credentials/
      tokens for external platforms (e.g. TELEGRAM_TOKEN, GITHUB_TOKEN)
      into ~/.finityagent/.env, wired into the system prompt so agent-built
      integrations can connect to those platforms
- [ ] Point-and-add: click any element in an agent's HTML response to
      attach it (as a selector/element reference) to the prompt (removed
      for now — revisit later)
- [x] Persist reasoning effort per conversation alongside the model
      (currently global config only)
- [x] Long tool responses saved as files the agent can read (instead of
      only tail-capping output in context)
- [x] Long-term agent memory (persistent facts/preferences across
      conversations, e.g. MEMORY.md the agent reads and updates)
- [x] Mobile-friendly interface (responsive layout / touch composer)
- [x] Scheduled agent runs via real cron: `finityagent --prompt "..." --session <id>`
      injected into the running server; the agent creates cron entries itself
      via bash (session ids listed by `finityagent sessions`, also in the
      system prompt)
      event-triggered actions)
- [x] Hide (soft-delete) conversations from the sidebar
- [x] Stable header dropdowns: model/reasoning selects keep their value
      without flashing blank while options load
- [x] Loading indicators in the conversation sidebar showing which
      conversations have a running agent
- [ ] Overall UI polish pass
- [x] Improved skills access; user-initiated skills and slash commands
      (e.g. `/skill: <name>`, custom commands)
- [x] Auto-send HTML render errors back to the agent so it can fix them
- [x] Long-running commands handled by plain bash (`nohup CMD >file.log 2>&1
      &` — detached, output in a file; results streamed back via
      `finityagent --prompt --session`) — no special bg facility
- [x] Richer widget protocol: multi-step forms — submit fires only after
      the user has selected all options / clicked submit, not per button
- [x] Web search as a first-class installable skill with per-provider
      backends (Bing no-key scrape + DDG instant answers bundled; SearXNG/Brave/Exa keys when needed) — bundled Bing-no-key + DDG-instant skill seeded at startup
- [ ] Publish to PyPI (`uv tool install finityagent` path; currently
      repo-only install via `uv sync`)
- [x] Start-or-reattach: zero-arg invocation when a server already runs
      on the port (currently errors on port conflict)

### Bugs
- [x] After a page refresh, replayed reasoning deltas update the first
      Thinking block instead of the last one (thinkingEl is not reset per
      replayed turn)

### Explore
- Learning loop / self-nudges (agent-initiated, no harness subsystem):
  - **Self-nudge via own CLI** — after a multi-turn task, the agent runs
    `finityagent --prompt "Reflection: persist anything valuable..." --session <id>`
    to spin a reflection turn on its own transcript. Policy ("nudge yourself
    after complex tasks") is saved to MEMORY.md once and becomes standing
    behavior. Delayed reflection via cron (sleep-on-it reviews, weekly audits).
    Policy lives in memory/skills (data), mechanism lives in the harness —
    behavior is programmable in natural language.
  - **Tier 1 (zero harness change)** — agent-built listener: cron polling
    `sessions.db` for new message ids; react via `--prompt --session` injection.
    Deterministic but laggy; listener is just a background bash process.
  - **Tier 2 (one tiny harness concession)** — `server.py` appends JSONL
    lifecycle events (turn_started, turn_finished, tool_error, approval_denied,
    compaction…) to `~/.finityagent/events.jsonl`; agent runs
    `tail -f events.jsonl | python hooks/on_event.py` — a real event bus.
    Hooks are files the agent owns and edits; nudges fire 100% of the time
    (the event is the nudge, nothing relies on remembering).
  - **Delivery** — seed a `hooks.md` skill (like websearch.md) teaching the
    event format + listener conventions rather than writing harness code.
  - **Caveats** — recursion (injected turn finishes → turn_finished event →
    loop; skip rule: never react to handler-injected turns, e.g. `[reflection]`
    marker), listener durability (PID lockfile, @reboot revive, log rotation),
    listener bypasses per-command approval (deny list still applies to
    injected turns), event log doubles as observational memory.
- Give the agent access to (or the ability to create) backend endpoints,
  so generated apps can serve dynamic content beyond static HTML — e.g.
  agent-authored FastAPI routes mounted by the harness, server-side
  compute, webhooks, live data streams

### V2 backlog
- Configurable permission patterns in `~/.finityagent/config.toml`
  (full allow/deny rule engine)
- OS-level sandboxing (sandbox-exec/Seatbelt, bubblewrap)
- Doom-loop detection
- Per-session working directory picker in UI
- AST (tree-sitter style) parsing of chained commands for the permission gate
- Static sanitized inline preview for script-less HTML
- Turn history compaction / context management for long sessions
- Turn recovery across server restarts (turns die with the process)

## Key decisions log

| Area | Decision |
|---|---|
| Rendering | **Direct DOM** (was sandboxed iframe — dropped for seamlessness); agent fragments injected into `.agent-html` container, scripts IIFE-wrapped server-side |
| UI framework | FastHTML + Pico CSS (dark) + **HTMX everywhere + inline surreal.js** — no app.js; the whole UI is server-rendered, streaming is SSE events carrying HTML fragments with hx-swap-oob updates |
| DB | fastlite over raw sqlite3 |
| Files | Dedicated `~/.finityagent/files/` dir + symlinks, not the cwd |
| Reasoning | Per-model options from models.dev; `reasoning_effort` param; traces displayed |
| Streaming | SSE extension; every event is a server-rendered HTML fragment (append or oob-swap) — htmx does all rendering |

## Project layout

```
finityagent/
├── pyproject.toml          # uv/hatch build, entry point: finityagent
├── src/finityagent/
│   ├── __main__.py         # CLI: flags, browser open
│   ├── server.py           # FastHTML app, routes, background turns, SSE
│   ├── agent.py            # the loop: stream → tool call → bash → repeat
│   ├── tools.py            # bash tool: subprocess, timeouts, kill
│   ├── permissions.py      # deny list + approval state
│   ├── providers.py        # openai SDK client factory, model lists
│   ├── prompts.py          # system prompt builder
│   ├── config.py           # toml load/save, presets
│   ├── db.py               # fastlite sessions/messages
│   └── static/
│       ├── app.js          # (removed — htmx + SSE + inline surreal)
│       ├── wizard.js       # preset prefill + model dropdown
│       └── style.css       # structural CSS on top of Pico
└── tests/
```
