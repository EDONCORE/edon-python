"""EDON Governance SDK.

Govern AI agent actions at runtime — evaluate, enforce, and audit
every action your agent takes before it executes.

Quick start::

    import edon

    # Configure once
    edon.configure(api_key="your-key")

    # Govern any function
    @edon.govern(action_type="email.send")
    def send_email(to: str, subject: str, body: str) -> None:
        ...  # Only runs if EDON allows it

    # Or use the client directly
    client = edon.EdonClient(api_key="your-key")
    decision = client.evaluate("email.send", {"to": "user@example.com", "subject": "Hello"})
    print(decision.decision)  # ALLOW or BLOCK

LangChain integration::

    from edon.integrations.langchain import EdonGuard
    tools = EdonGuard.wrap_tools(tools=[...], api_key="your-key")

OpenAI Agents integration::

    from edon.integrations.openai_agents import EdonToolGuard
    tools = EdonToolGuard.wrap(tools=[...], api_key="your-key")

CrewAI integration::

    from edon.integrations.crewai import EdonCrewGuard
    tools = EdonCrewGuard.wrap_tools(tools=[...], api_key="your-key")
"""

from .client import AsyncEdonClient, Decision, EdonClient
from .exceptions import (
    EdonAuthError,
    EdonBlockedError,
    EdonConnectionError,
    EdonDegradedError,
    EdonEscalatedError,
    EdonError,
    EdonRateLimitError,
)
from .govern import configure, govern

__version__ = "0.1.0"
__author__ = "EDON Core"
__email__ = "sdk@edoncore.com"

__all__ = [
    # Clients
    "EdonClient",
    "AsyncEdonClient",
    "Decision",
    # Decorator API
    "govern",
    "configure",
    # Exceptions
    "EdonError",
    "EdonBlockedError",
    "EdonEscalatedError",
    "EdonDegradedError",
    "EdonAuthError",
    "EdonConnectionError",
    "EdonRateLimitError",
    # Meta
    "__version__",
]
