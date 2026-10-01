# FinityAgent

An AI agent harness that is intentionally minimal: the agent gets **one tool — bash**. Everything else is expressed through what it writes back.

## Concept

- **Harness**: Python-only. Runs the agent loop, executes the single bash tool, and manages conversation state.
- **Interface**: A web chat UI. You talk to the agent like any chatbot.
- **Agent output**: Instead of plain markdown, the agent responds with **visual, interactive HTML**. Charts, simulations, games, forms — rendered directly in the chat.

## Design principles

1. **One tool.** The bash tool is universal: file manipulation, code execution, data processing, and API calls all go through it. Constraint breeds generality.
2. **HTML as the response medium.** The chat renders the agent's HTML responses in a sandboxed frame, making answers interactive rather than static text.


## Roadmap

- [ ] Agent loop with a single bash tool + simple UI
- [ ] Streaming Interface
- [ ] Safe bash 
- [ ] Session persistence (sqlite)
- [ ] Prompt to teach it background processes, scheduled tasks, skills, memory etc.
