# FinityAgent — AGENTS.md

## What this project is

An AI agent harness that is intentionally minimal: the agent gets **one tool — bash**.
Everything else is expressed through what it writes back.

- **Harness**: Python-only. Runs the agent loop, executes the single bash tool, manages conversation state.
- **Interface**: A web chat UI — you talk to the agent like any chatbot.
- **Agent output**: Visual, interactive **HTML** rendered directly in the chat (charts, simulations, games, forms) — not plain markdown.

Constraint breeds generality: one universal tool, HTML as the response medium, pure Python end to end.

## Tech stack (fixed)

Use exactly these; keep additions near zero.

- **FastHTML** — backend, routing, HTML generation. Pure Python, no Node build step.
- **htmx** — all interactivity: forms, partial swaps, streaming updates.
- **Surreal JS** — sparingly, only where htmx can't reach (tiny inline behaviors).
- **Pico CSS** — the base stylesheet; classless where possible.
- **Custom CSS** — minimal inline styles or a few lines only; never a stylesheet system.

Rule of thumb: before writing JS, ask if htmx does it; before adding CSS, ask if Pico does it.
