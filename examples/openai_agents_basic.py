"""
EDON + OpenAI Agents SDK — governed agent.

Install:
    pip install 'edon[openai]' openai

Run:
    EDON_API_KEY=your-key OPENAI_API_KEY=your-key python examples/openai_agents_basic.py
"""

import os
import openai
from agents import Agent, Runner, function_tool

from edon.integrations.openai_agents import EdonToolGuard


# ── 1. Define tools ───────────────────────────────────────────
@function_tool
def search_web(query: str) -> str:
    """Search the internet for current information."""
    # Real implementation would call a search API
    return f"Search results for: {query}"


@function_tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to a recipient."""
    # Real implementation would send via SMTP/Gmail
    return f"Email sent to {to}"


@function_tool
def delete_database_records(table: str, condition: str) -> str:
    """Delete records from a database table matching a condition."""
    return f"Deleted from {table} where {condition}"


# ── 2. Wrap with EDON governance ─────────────────────────────
# EDON evaluates each tool call before execution.
# send_email and delete_database_records will likely be BLOCKED
# by the default founder_mode policy. search_web will ALLOW.
governed_tools = EdonToolGuard.wrap(
    tools=[search_web, send_email, delete_database_records],
    api_key=os.environ["EDON_API_KEY"],
    agent_id="openai-research-agent",
    raise_on_block=True,  # Raises EdonBlockedError on blocked actions
)

# ── 3. Create agent with governed tools ───────────────────────
agent = Agent(
    name="Research Assistant",
    instructions="You are a helpful research assistant with access to web search and email.",
    tools=governed_tools,
)

# ── 4. Run ────────────────────────────────────────────────────
result = Runner.run_sync(
    agent,
    "Search for the latest AI safety news and send a summary to ceo@company.com"
)
print(result.final_output)
