"""
EDON + NVIDIA NeMo Agent Toolkit (AgentIQ) — governed agent.

Install:
    pip install 'edon[nvidia]' nvidia-nat

Run:
    EDON_API_KEY=your-key python examples/nvidia_agentiq_basic.py
"""

import asyncio
import os

from edon.integrations.nvidia_agentiq import EdonNvidiaGuard


# ── 1. Define async tools ─────────────────────────────────────
async def search_web(query: str) -> str:
    """Search the internet for current information."""
    # Real implementation would call a search API
    return f"Search results for: {query}"


async def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to a recipient."""
    # Real implementation would send via SMTP/Gmail
    return f"Email sent to {to}"


async def delete_database_records(table: str, condition: str) -> str:
    """Delete records from a database table matching a condition."""
    return f"Deleted from {table} where {condition}"


# ── 2. Wrap with EDON governance ──────────────────────────────
# EDON evaluates each tool call before execution.
# send_email and delete_database_records will likely be BLOCKED
# by the default policy. search_web will ALLOW.
governed = EdonNvidiaGuard.wrap_fns(
    fns=[search_web, send_email, delete_database_records],
    api_key=os.environ["EDON_API_KEY"],
    agent_id="nvidia-research-agent",
    raise_on_block=True,  # Raises EdonBlockedError on blocked actions
)
governed_search, governed_email, governed_delete = governed


# ── 3. Register with NeMo Agent Toolkit ───────────────────────
# Pass governed callables to FunctionInfo.from_fn() exactly as you
# would unguarded functions. EDON checks run transparently before
# each invocation.
#
#   from aiq.builder.function_info import FunctionInfo
#
#   @register_function(config_type=MyAgentConfig)
#   async def build_agent(config, builder):
#       yield FunctionInfo.from_fn(governed_search, description="Search the web")
#       yield FunctionInfo.from_fn(governed_email,  description="Send an email")
#       yield FunctionInfo.from_fn(governed_delete, description="Delete DB records")


# ── 4. Standalone smoke test (no NeMo toolkit required) ───────
async def main() -> None:
    from edon.exceptions import EdonBlockedError

    print("Testing EDON governance on NVIDIA AgentIQ callables...\n")

    # search_web — expect ALLOW
    try:
        result = await governed_search(query="latest AI safety research")
        print(f"search_web → ALLOWED: {result}")
    except EdonBlockedError as e:
        print(f"search_web → BLOCKED: {e}")

    # send_email — expect BLOCK under default policy
    try:
        result = await governed_email(
            to="ceo@company.com",
            subject="AI Safety Summary",
            body="Here is the latest...",
        )
        print(f"send_email → ALLOWED: {result}")
    except EdonBlockedError as e:
        print(f"send_email → BLOCKED: {e}")

    # delete_database_records — expect BLOCK
    try:
        result = await governed_delete(table="users", condition="created_at < '2020-01-01'")
        print(f"delete_database_records → ALLOWED: {result}")
    except EdonBlockedError as e:
        print(f"delete_database_records → BLOCKED: {e}")


if __name__ == "__main__":
    asyncio.run(main())
