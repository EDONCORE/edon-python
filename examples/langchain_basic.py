"""
EDON + LangChain — governed agent in ~10 lines.

Install:
    pip install 'edon[langchain]' langchain-openai langchain-community

Run:
    EDON_API_KEY=your-key OPENAI_API_KEY=your-key python examples/langchain_basic.py
"""

import os
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.tools import DuckDuckGoSearchRun

# Import EDON LangChain integration
from edon.integrations.langchain import EdonGuard, EdonCallbackHandler

# ── 1. Define tools (any LangChain tools) ────────────────────
tools = [DuckDuckGoSearchRun()]

# ── 2. Wrap with EDON governance ─────────────────────────────
governed_tools = EdonGuard.wrap_tools(
    tools=tools,
    api_key=os.environ["EDON_API_KEY"],
    agent_id="research-agent-01",
    # intent_id="intent_founder_mode_xxx",  # optional: pin to a specific policy
)

# ── 3. Build agent with governed tools ───────────────────────
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful research assistant."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm, governed_tools, prompt)

# Optional: add callback handler for pure audit logging (non-blocking)
handler = EdonCallbackHandler(
    api_key=os.environ["EDON_API_KEY"],
    agent_id="research-agent-01",
    verbose=True,
)

executor = AgentExecutor(
    agent=agent,
    tools=governed_tools,
    callbacks=[handler],
    verbose=True,
)

# ── 4. Run — every tool call goes through EDON first ─────────
result = executor.invoke({"input": "What is the latest news about AI governance?"})
print("\nResult:", result["output"])

# All decisions are now visible in your EDON console at edoncore.com
