# FinityAgent

A local AI agent harness with exactly **one tool: bash**. You chat in the
browser; the agent answers with **visual, interactive HTML** — charts,
sliders, quizzes, dashboards, live data — rendered right in the conversation.

## How it works

- **One tool.** Bash is universal: files, code execution, data processing,
  web requests — all through a single shell. Constraint breeds generality.
- **HTML as the response medium.** Agent fragments are injected directly
  into the chat page (CDN libraries like Chart.js/D3 work). Interactive
  widgets can send data back to the agent via the `data-send` attribute —
  quizzes, parameter pickers, drill-downs become conversations.
- **Pure Python.** FastHTML + HTMX + vanilla JS. No Node, no build step.
  Works with any OpenAI-compatible endpoint (OpenCode Go, OpenAI, …).

## Features

- First-run setup wizard with provider presets; config in
  `~/.finityagent/config.toml`
- Streaming responses with live tool-call cards and a collapsible Thinking
  view for reasoning models
- Approval system: Approve all / Auto modes, per-command cards
  (Run / Always this session / Skip), hardcoded deny list
- Model + reasoning-level switchers (per-model options fetched from
  models.dev), persisted across conversations
- Multiple conversations with background turns (switching chats never kills
  a running agent), SQLite persistence, transcript replay
- Skills: reads markdown skill files from `~/.claude/skills`,
  `~/.agents/skills`, `~/.finityagent/skills` and project `.finityagent/skills`
- Agent-served assets: anything copied/symlinked into
  `~/.finityagent/files/` is available to agent HTML at `/files/<name>`
- Web search via DuckDuckGo through bash (skill), with citations
- Playwright-friendly test surface; 56 pytest tests

## Getting started

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/fakhirali/FinityAgent.git
cd FinityAgent
uv sync
uv run finityagent            # opens http://localhost:8377
```

First run shows a setup wizard: pick a provider preset (OpenCode Go,
OpenAI, or custom), paste your API key, pick a model — done.

Flags: `--port`, `--cwd <dir>` (agent's working directory), `--no-browser`.

## Architecture

```
src/finityagent/
├── __main__.py   # CLI
├── server.py     # FastHTML app, routes, background turns, SSE
├── agent.py      # the loop: stream → tool call → bash → repeat
├── tools.py      # bash tool: subprocess, timeouts, process-group kill
├── permissions.py# deny list + approval state
├── providers.py  # openai SDK client factory, model lists
├── prompts.py    # system prompt builder
├── config.py     # toml config + presets
└── db.py         # fastlite (SQLite) sessions/messages
```

See [PLAN.md](PLAN.md) for the full implementation status and roadmap.

## Roadmap highlights

- Long-term agent memory
- Background processes; cronjobs and triggered workflows
- Auto-error-repair loop (render errors sent back to the agent)
- Mobile interface; user-initiated skills and slash commands
- Agent-served backend for dynamic apps
