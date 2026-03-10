"""LangChain integration for EDON governance.

Two integration patterns:

1. **Tool wrapping** (recommended) — wraps tools so EDON governs each call before execution:

    from edon.integrations.langchain import EdonGuard

    tools = EdonGuard.wrap_tools(
        tools=[search_tool, email_tool, calendar_tool],
        api_key="your-edon-key",
        agent_id="my-langchain-agent",
    )
    agent = create_tool_calling_agent(llm, tools, prompt)

2. **Callback handler** — logs all tool calls to EDON for audit (non-blocking):

    from edon.integrations.langchain import EdonCallbackHandler

    handler = EdonCallbackHandler(api_key="your-edon-key", agent_id="my-agent")
    agent = AgentExecutor(agent=agent, tools=tools, callbacks=[handler])
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union
from uuid import UUID

from ..client import EdonClient, Decision
from ..exceptions import EdonBlockedError, EdonEscalatedError

try:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.tools import BaseTool, StructuredTool
    from langchain_core.outputs import LLMResult
    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False
    # Provide stubs so the file is importable without langchain installed
    class BaseCallbackHandler:  # type: ignore[no-redef]
        pass
    class BaseTool:  # type: ignore[no-redef]
        pass


def _require_langchain() -> None:
    if not _LANGCHAIN_AVAILABLE:
        raise ImportError(
            "langchain-core is required for this integration. "
            "Install with: pip install 'edon[langchain]'"
        )


# ─────────────────────────────────────────────────────────────
# Tool wrapper
# ─────────────────────────────────────────────────────────────

class _EdonWrappedTool(BaseTool):
    """A LangChain tool wrapped with EDON governance enforcement."""

    name: str = ""
    description: str = ""
    _wrapped: Any = None  # original BaseTool
    _edon: Any = None     # EdonClient
    _agent_id: str = "langchain-agent"
    _intent_id: Optional[str] = None
    _raise_on_block: bool = True

    class Config:
        arbitrary_types_allowed = True

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        """Evaluate via EDON then run the wrapped tool."""
        # Build payload from args/kwargs
        tool_input = kwargs if kwargs else (args[0] if args else {})
        if isinstance(tool_input, str):
            tool_input = {"input": tool_input}

        # Derive action_type from tool name (e.g. "send_email" → "tool.send_email")
        action_type = f"tool.{self.name.lower().replace(' ', '_').replace('-', '_')}"

        decision: Decision = self._edon.evaluate(
            action_type,
            tool_input if isinstance(tool_input, dict) else {"input": str(tool_input)},
            agent_id=self._agent_id,
            intent_id=self._intent_id,
            raise_on_block=False,  # We handle raising ourselves for better messages
        )

        if decision.blocked:
            msg = f"[EDON BLOCKED] {decision.decision_reason}"
            if self._raise_on_block:
                raise EdonBlockedError(
                    decision.decision_reason,
                    action_id=decision.action_id,
                    reason_code=decision.reason_code,
                )
            return msg

        if decision.needs_human:
            msg = f"[EDON ESCALATED] Human approval required: {decision.decision_reason}"
            if self._raise_on_block:
                raise EdonEscalatedError(
                    decision.decision_reason,
                    action_id=decision.action_id,
                    question=decision.escalation_question,
                )
            return msg

        # ALLOW or DEGRADE — proceed with execution
        return self._wrapped._run(*args, **kwargs)

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        # Fall back to sync for now
        return self._run(*args, **kwargs)


class EdonGuard:
    """Factory for wrapping LangChain tools with EDON governance.

    Usage::

        from edon.integrations.langchain import EdonGuard
        from langchain_community.tools import DuckDuckGoSearchRun, GmailSendMessage

        governed_tools = EdonGuard.wrap_tools(
            tools=[DuckDuckGoSearchRun(), GmailSendMessage()],
            api_key=os.environ["EDON_API_KEY"],
            agent_id="research-agent-01",
            intent_id="intent_founder_mode_xxx",
        )

        # Use governed_tools exactly like normal LangChain tools
        agent = create_tool_calling_agent(llm, governed_tools, prompt)
        executor = AgentExecutor(agent=agent, tools=governed_tools)
    """

    @staticmethod
    def wrap_tools(
        tools: List[Any],
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        agent_id: str = "langchain-agent",
        intent_id: Optional[str] = None,
        raise_on_block: bool = True,
    ) -> List[Any]:
        """Wrap a list of LangChain tools with EDON governance.

        Each tool call is evaluated by EDON before execution. Blocked actions
        raise ``EdonBlockedError`` (or return an error string if raise_on_block=False).

        Args:
            tools:          List of LangChain BaseTool instances.
            api_key:        EDON API key (default: ``EDON_API_KEY`` env var).
            base_url:       EDON gateway URL (default: ``EDON_BASE_URL`` env var or cloud).
            agent_id:       Identifier for this agent in the audit trail.
            intent_id:      Active intent contract ID.
            raise_on_block: Raise exception on BLOCK (True) or return error string (False).

        Returns:
            List of governed tools with the same interface as the originals.
        """
        _require_langchain()

        client = EdonClient(
            api_key=api_key,
            base_url=base_url,
            agent_id=agent_id,
            intent_id=intent_id,
            raise_on_block=False,  # _EdonWrappedTool handles raise logic
        )

        governed = []
        for tool in tools:
            wrapped = _EdonWrappedTool()
            wrapped.name = tool.name
            wrapped.description = tool.description
            wrapped._wrapped = tool
            wrapped._edon = client
            wrapped._agent_id = agent_id
            wrapped._intent_id = intent_id
            wrapped._raise_on_block = raise_on_block
            governed.append(wrapped)

        return governed

    @staticmethod
    def wrap(
        tool: Any,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        agent_id: str = "langchain-agent",
        intent_id: Optional[str] = None,
        raise_on_block: bool = True,
    ) -> Any:
        """Wrap a single LangChain tool."""
        return EdonGuard.wrap_tools(
            [tool],
            api_key=api_key,
            base_url=base_url,
            agent_id=agent_id,
            intent_id=intent_id,
            raise_on_block=raise_on_block,
        )[0]


# ─────────────────────────────────────────────────────────────
# Callback handler (audit / observability)
# ─────────────────────────────────────────────────────────────

class EdonCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that logs all tool calls to EDON for audit.

    This handler does NOT block execution — it records every tool invocation
    to EDON's audit trail, giving you a tamper-evident log of every action
    your agent takes. Use alongside ``EdonGuard`` for full governance, or
    standalone for pure observability.

    Usage::

        from edon.integrations.langchain import EdonCallbackHandler

        handler = EdonCallbackHandler(
            api_key=os.environ["EDON_API_KEY"],
            agent_id="my-research-agent",
        )
        executor = AgentExecutor(
            agent=agent,
            tools=tools,
            callbacks=[handler],
        )

    All tool calls will appear in your EDON console at edoncore.com.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        agent_id: str = "langchain-agent",
        intent_id: Optional[str] = None,
        verbose: bool = False,
    ):
        _require_langchain()
        super().__init__()
        self._client = EdonClient(
            api_key=api_key,
            base_url=base_url,
            agent_id=agent_id,
            intent_id=intent_id,
            raise_on_block=False,
        )
        self._agent_id = agent_id
        self._intent_id = intent_id
        self._verbose = verbose

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Called by LangChain before a tool executes. Logs to EDON audit trail."""
        tool_name = serialized.get("name", "unknown_tool")
        action_type = f"tool.{tool_name.lower().replace(' ', '_').replace('-', '_')}"

        # Parse input
        try:
            payload: Dict[str, Any] = json.loads(input_str) if input_str.strip().startswith("{") else {"input": input_str}
        except (json.JSONDecodeError, AttributeError):
            payload = {"input": str(input_str)}

        try:
            decision = self._client.evaluate(
                action_type,
                payload,
                agent_id=self._agent_id,
                intent_id=self._intent_id,
                raise_on_block=False,
            )
            if self._verbose:
                print(f"[EDON] {tool_name} → {decision.decision} ({decision.processing_latency_ms}ms)")
        except Exception as exc:
            if self._verbose:
                print(f"[EDON] audit failed for {tool_name}: {exc}")

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        pass  # Execution complete — already logged in on_tool_start

    def on_tool_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        if self._verbose:
            print(f"[EDON] tool error: {error}")

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        pass

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        pass

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any) -> None:
        pass

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> None:
        pass
