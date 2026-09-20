import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return


@app.cell
def _():
    from fasthtml.common import (
        fast_app, Titled, P,
    )

    return P, Titled, fast_app


@app.cell
def _(fast_app):
    app, router = fast_app(live=True)
    return app, router


@app.cell
def _():
    import os, uuid
    from openai import OpenAI

    # OpenCode Go requires (opencode.ai/docs/go):
    #   - a coding-agent User-Agent, not the generic SDK one
    #   - a stable x-opencode-session per conversation
    llm_client = OpenAI(
        base_url="https://opencode.ai/zen/go/v1",
        api_key=os.environ.get("OPENCODE_GO_KEY") or "unset",
        default_headers={"User-Agent": "finityagent/1.0"},
    )
    chat_session = str(uuid.uuid4())
    return chat_session, llm_client, os


@app.cell
def _(llm_client):
    models = llm_client.models.list()
    model_ids = [m.id for m in models.data]
    # print(model_ids)
    return (model_ids,)


@app.cell
def _(chat_session, llm_client, model_ids, os):
    current_model = "glm-5.3-flash"
    assert current_model in model_ids
    if not os.environ.get("OPENCODE_GO_KEY"):
        print("Set OPENCODE_GO_KEY in .env (opencode.ai/auth) and re-run to test chat")
    else:
        reply = llm_client.chat.completions.create(
            model=current_model,
            messages=[{"role": "user", "content": "Say hello in one sentence."}],
            extra_headers={"x-opencode-session": chat_session},
        )
        print(reply.choices[0].message.content)
    return


@app.cell
def _(P, Titled, router):
    @router("/")
    def get():
        return Titled("FinityAgent",
            P("Hello from FinityAgent, live inside marimo!"),
            P("Edit me — hot reload will pick it up."),
        )

    return


@app.cell
def _(app):
    from fasthtml.jupyter import nb_serve
    from fasthtml.core import serve
    server = nb_serve(app, port=5437, log_level="warning", reload=True, daemon=True)
    # serve(reload=True, port=5437)
    f"FastHTML dev server on http://localhost:5437 (stop with: server.should_exit = True)"
    return (server,)


@app.cell
def _(server):
    server.shutdown()
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
