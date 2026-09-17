# FinityAgent

An AI agent harness that is intentionally minimal: the agent gets **one tool — bash**. Everything else is expressed through what it writes back.

## Concept

- **Harness**: Python-only. Runs the agent loop, executes the single bash tool, and manages conversation state.
- **Interface**: A web chat UI. You talk to the agent like any chatbot.
- **Agent output**: Instead of plain markdown, the agent responds with **visual, interactive HTML**. Charts, simulations, games, forms — rendered directly in the chat.

## Design principles

1. **One tool.** The bash tool is universal: file manipulation, code execution, data processing, and API calls all go through it. Constraint breeds generality.
2. **HTML as the response medium.** The chat renders the agent's HTML responses in a sandboxed frame, making answers interactive rather than static text.
3. **Pure Python.** No Node build step for the harness. A Python backend (FastAPI/WebSocket) serves the chat UI and streams agent turns.

## Roadmap

- [ ] Agent loop with a single bash tool (subprocess sandboxing)
- [ ] FastAPI backend + WebSocket streaming
- [ ] Chat UI with sandboxed HTML response rendering
- [ ] Configurable model providers (Anthropic, OpenAI, local)
- [ ] Session persistence

## Getting started

Not built yet — see the roadmap above.
