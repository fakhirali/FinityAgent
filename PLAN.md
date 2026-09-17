# FinityAgent — Implementation Plan

Local agent harness, Python-only. Chat in the browser; agent has exactly one
tool (bash) and responds with visual, interactive HTML.

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
- [x] **`data-send` widget bridge** — `<form data-send>` and
      `<button data-send='{json}'>` submit back as
      `[widget response] {...}` user turns
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
- Web search moved out of the prompt into a real skill
  (`~/.finityagent/skills/websearch.md`, DuckDuckGo via curl, citations)

### Testing
- [x] 57 pytest tests: config, permissions, tools, db, agent decisions
- [x] Playwright verification of wizard, chat flow, approval cards,
      widget round-trip, persistence, background turns, file serving
- [x] Demo video recorded (`/tmp/finity-demo.webm`)

## Not yet implemented

### Near-term
- [ ] Long-term agent memory (persistent facts/preferences across
      conversations, e.g. MEMORY.md the agent reads and updates)
- [ ] Hide (soft-delete) conversations from the sidebar
- [ ] Stable header dropdowns: model/reasoning selects keep their value
      without flashing blank while options load
- [ ] Loading indicators in the conversation sidebar showing which
      conversations have a running agent
- [ ] Overall UI polish pass
- [ ] Improved skills access; user-initiated skills and slash commands
      (e.g. `/skill: <name>`, custom commands)
- [ ] Auto-send HTML render errors back to the agent so it can fix them
- [ ] Background process facility (start/stop/monitor long-running
      commands, e.g. dev servers)
- [ ] Richer widget protocol: multi-step forms — submit fires only after
      the user has selected all options / clicked submit, not per button
- [ ] Web search as a first-class installable skill with per-provider
      backends (SearXNG, Brave, Exa keys)
- [ ] Publish to PyPI (`uv tool install finityagent` path; currently
      repo-only install via `uv sync`)
- [ ] Start-or-reattach: zero-arg invocation when a server already runs
      on the port (currently errors on port conflict)

### Bugs
- [ ] After a page refresh, replayed reasoning deltas update the first
      Thinking block instead of the last one (thinkingEl is not reset per
      replayed turn)

### Explore
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
| Rendering | **Direct DOM** (was sandboxed iframe — dropped for seamlessness); agent fragments injected into `.agent-html` container, scripts IIFE-wrapped |
| UI framework | FastHTML + Pico CSS (dark) + vanilla JS + HTMX for sidebar partials |
| DB | fastlite over raw sqlite3 |
| Files | Dedicated `~/.finityagent/files/` dir + symlinks, not the cwd |
| Reasoning | Per-model options from models.dev; `reasoning_effort` param; traces displayed |
| Streaming | Per-token SSE; POST/EventSource split; turns run server-side in threads |

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
│       ├── app.js          # chat UI, EventSource, data-send bridge
│       ├── wizard.js       # preset prefill + model dropdown
│       └── style.css       # structural CSS on top of Pico
└── tests/
```
