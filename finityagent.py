#!/usr/bin/env python
# coding: utf-8

# In[3]:


from fasthtml.common import *

app, router = fast_app(live=False)


# In[4]:


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


# In[5]:


models = llm_client.models.list()
model_ids = [m.id for m in models.data]
# print(model_ids)
model_ids


# In[6]:


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


# # Agent loop — one tool: bash
# Chat history → model → tool call → `subprocess` → result → model. The agent answers in plain text or an HTML artifact.
# disk: 15 cells
# 

# In[9]:


# Tool definition
BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a bash command and return stdout+stderr. Use for file ops, code execution, data processing, websearch, cronjobs — everything.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to run"},
            },
            "required": ["command"],
        },
    },
}

import subprocess

def run_bash(command: str, timeout: int = 60) -> str:
    """Execute one bash command, return combined stdout/stderr."""
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + ("\n[stderr]\n" + r.stderr if r.stderr else "")).strip()
        return out or f"(exit {r.returncode}, no output)"
    except subprocess.TimeoutExpired:
        return f"(timed out after {timeout}s)"

# smoke test
print(run_bash("echo hi && pwd"))


# In[79]:


# Agent loop
import json as _json

SYSTEM_PROMPT = """You are Finity Agent, an agent with exactly one tool: bash. You will use it
for everything such as file ops, code execution, websearch, external integrations, scheduling tasks etc. Respond in html formatting instead of markdown please."""

def chat(messages: list, max_turns: int = 8, model: str | None = None) -> list:
    """Run the agent loop; returns the full message history (mutated in place)."""
    for _ in range(max_turns):
        reply = llm_client.chat.completions.create(
            model=model or current_model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            tools=[BASH_TOOL],
            extra_headers={"x-opencode-session": chat_session},
        )
        msg = reply.choices[0].message
        if not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content})
            return messages
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": tc.id, "type": "function",
                                         "function": {"name": tc.function.name,
                                                      "arguments": tc.function.arguments}}
                                        for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            if tc.function.name != "bash":
                result = f"(unknown tool {tc.function.name})"
            else:
                args = _json.loads(tc.function.arguments)
                # print(f"$ {args['command']}")
                result = run_bash(args["command"])
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return messages





page = Div(
    Div(
        Div("Hi! I'm FinityAgent — one tool: bash.",
            style="align-self:flex-start;"),
        Div("What files are in this directory?",
            style="align-self:flex-end;"),
        Div("$ ls → FinityAgent.ipynb, finityagent.py, pyproject.toml, README.md",
            style="align-self:flex-start;"),
        id="chat-log",
        style="display:flex; flex-direction:column; gap:6px; flex:1;"
              " overflow-y:auto; padding:14px; line-height:1.3;",
    ),
    Form(
        Input(name="msg", placeholder="Type a message…", required=True,
              autocomplete="off",
              style="flex:1; height:50px; box-sizing:border-box;"),
        Button("Send", style="height:50px; box-sizing:border-box;"),
        style="display:flex; gap:8px; margin-top:10px;",
        hx_post="/chat", hx_target="#chat-log", hx_swap="beforeend",
        hx_on__after_request="this.reset()",
    ),
    style="display:flex; flex-direction:column; height:100vh;"
          " padding:16px; box-sizing:border-box;",
)


# In[96]:


import json
history = [] 
@router("/")
def get():
    return page

# Step 1: echo the user's message back immediately...
@router("/chat")
def post(msg: str):

    return Div(
        msg, style="align-self:flex-end; white-space:pre-wrap;",
        hx_post="/agent", hx_trigger="load",
        hx_target="#chat-log", hx_swap="beforeend",
        hx_vals=json.dumps({"msg": msg}),
    )

# Step 2: ...the echoed div fires this on load and swaps in the agent's response
@router("/agent")
def agent(msg: str):
    global history
    if "history" not in globals():
        history = []
    history.append({"role": "user", "content": msg})
    chat(history)
    return Div(NotStr(history[-1]["content"]), style="align-self:flex-start;")


# In[14]:


if __name__ == "__main__":
    serve(app, port=5437)


# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:




