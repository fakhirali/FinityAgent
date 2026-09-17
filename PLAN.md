# FinityAgent — Implementation Plan (V1)

Local agent harness, Python-only. Chat in the browser; agent has exactly one
tool (bash) and responds with visual, interactive HTML.

## Decisions

| Area | Decision |
|---|---|
| Provider | OpenAI-compatible via official `openai` SDK with `base_url` override; tested against OpenCode Go (`https://opencode.ai/zen/go/v1`) |
| Onboarding | First-run wizard in the web UI; presets (OpenCode Go / OpenAI / Custom); config at `~/.finityagent/config.toml`; env vars override |
| Install | PyPI; `uv tool install finityagent` primary, `uvx finityagent` trial |
| Permissions | Mode toggle (Approve all / Auto) + hardcoded deny list (`sudo`, `rm -rf /`, fork bombs, `curl \| sh`) + approval cards: Run once / Always this session / Skip |
| Rendering | Sandboxed iframe (`allow-scripts`, opaque origin) + injected runtime script + `data-send` protocol; widget replies arrive as `[widget response] {...}` user turns |
| Streaming | Model SSE → browser SSE (server→client) + POST (client→server); live text deltas, tool cards, approval cards |
| Bash | `/bin/bash -c`, cwd = launch dir, 120s default / 600s max timeout, 30k char tail cap, process-group kill on timeout/cancel, UI cancel button |
| Persistence | SQLite at `~/.finityagent/sessions.db` (stdlib `sqlite3`); sidebar + resume; config global, sessions global with per-session `cwd` |
| System prompt | Identity/contract + `data-send` docs + "Design for interaction" guidance; no environment briefing; external/CDN resources allowed |
| Visibility | Tool calls hidden by default (collapsible chips + toggle); model switcher in header populated from `/v1/models` |
| CLI | `finityagent` zero-arg: start-or-reattach on port 8377 + auto-open browser; flags `--port`, `--cwd`, `--no-browser` |
| Stack | FastHTML + vanilla JS/HTMX + `openai` SDK, Python 3.11+, minimal deps |
| Structure | `src/finityagent/` package; entry point `finityagent` |

## System prompt outline

1. Identity & contract: one tool (bash); every final response is a complete,
   self-contained HTML document.
2. `data-send` protocol: `<form data-send>`, `<button data-send='{json}'>`,
   `data-send-target="chat"`; replies return as user turns wrapped in
   `[widget response] {...}`.
3. Design for interaction: responses must be visual and interactive by default
   — charts, sliders, buttons, tabs, live-updating views; compute real data
   with bash, then present it richly.
4. Behavioral guidance: verify by running commands rather than guessing.

External/CDN resources are allowed (iframe sandbox does not block network).

## Bash tool semantics

- Shell: `/bin/bash -c "<command>"`
- cwd: directory `finityagent` was launched from (per session)
- Timeout: 120s default; agent may request up to 600s hard cap
- On timeout: kill process group, return partial output
- Output: stdout+stderr combined, tail-capped at 30k chars with truncation notice
- User cancel button aborts current command and interrupts the loop
- Interactive commands discouraged in the system prompt (no background facility in V1)

## Approval system

- Modes: Approve all (default) / Auto (YOLO)
- Hardcoded deny list always enforced, even in Auto: `sudo`, `rm -rf /`,
  fork bombs, `curl | sh` style pipes into shells
- Approval card in chat keyed on command prefix: Run once / Always this
  session / Skip
- Full pattern rule engine deferred to V2

## Project layout

```
finityagent/
├── pyproject.toml          # uv/hatch build, entry point: finityagent
├── src/finityagent/
│   ├── __main__.py         # CLI: start-or-reattach, flags
│   ├── server.py           # FastHTML app, routes, SSE
│   ├── agent.py            # the loop: stream → tool call → bash → repeat
│   ├── tools.py            # bash tool: subprocess, timeouts, kill
│   ├── permissions.py      # deny list + approval state
│   ├── providers.py        # openai SDK client factory from config
│   ├── config.py           # toml load/save, wizard handling
│   ├── db.py               # sqlite sessions/messages
│   └── static/
│       ├── app.js
│       ├── iframe-runtime.js
│       └── style.css
└── tests/
```

## Milestones

1. **M1 — Skeleton**: CLI starts server, wizard page, config saved, chat page renders.
2. **M2 — First conversation**: non-streaming loop end-to-end against OpenCode Go; bash tool executes; response HTML renders in sandboxed iframe (static).
3. **M3 — Streaming & approval**: SSE everywhere, approval cards, visibility toggle, cancel button.
4. **M4 — Persistence & polish**: SQLite sessions + sidebar + resume, model switcher, `/v1/models`, V1 done.

## Testing strategy

- Unit tests for config, bash tool, permissions, db (pytest)
- Playwright for UI verification: wizard, chat flow, iframe rendering, approval cards
- Model tests hit the real OpenCode Go endpoint when `OPENCODE_API_KEY` present

## V2 backlog

- Background process facility (start/stop/monitor long-running commands, e.g. dev servers)
- Configurable permission patterns in `~/.finityagent/config.toml` (full allow/deny rule engine)
- OS-level sandboxing (sandbox-exec/Seatbelt, bubblewrap)
- Doom-loop detection
- Static sanitized inline preview for script-less HTML
- Per-session working directory picker in UI
- AST (tree-sitter style) parsing of chained commands for the permission gate
