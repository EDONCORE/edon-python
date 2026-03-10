"""CrewAI integration for EDON governance.

Wraps CrewAI tools so every tool invocation is evaluated by EDON before execution.

Usage::

    from crewai import Agent, Task, Crew
    from crewai.tools import tool
    from edon.integrations.crewai import EdonCrewGuard

    @tool("Search the web")
    def web_search(query: str) -> str:
        \"\"\"Search the internet for information.\"\"\"
        ...

    @tool("Send email")
    def send_email(to: str, subject: str, body: str) -> str:
        \"\"\"Send an email to a recipient.\"\"\"
        ...

    # Wrap all tools with EDON governance
    governed_tools = EdonCrewGuard.wrap_tools(
        tools=[web_search, send_email],
        api_key=os.environ["EDON_API_KEY"],
        agent_id="research-crew-agent",
    )

    researcher = Agent(
        role="Research Analyst",
        goal="Find and summarize information",
        tools=governed_tools,
    )
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Dict, List, Optional

from ..client import EdonClient
from ..exceptions import EdonBlockedError, EdonEscalatedError


class EdonCrewGuard:
    """Wraps CrewAI tools with EDON governance enforcement.

    Every tool call is checked against EDON policy before execution.
    Blocked actions raise ``EdonBlockedError`` and are never executed.

    Usage::

        from edon.integrations.crewai import EdonCrewGuard

        governed = EdonCrewGuard.wrap_tools(
            tools=[search_tool, email_tool],
            api_key=os.environ["EDON_API_KEY"],
            agent_id="crew-agent-01",
            intent_id="intent_founder_mode_xxx",
        )
        agent = Agent(role="Analyst", tools=governed)
    """

    @staticmethod
    def wrap_tools(
        tools: List[Any],
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        agent_id: str = "crewai-agent",
        intent_id: Optional[str] = None,
        raise_on_block: bool = True,
    ) -> List[Any]:
        """Wrap CrewAI tools with EDON governance.

        Args:
            tools:          List of CrewAI tool objects or @tool-decorated functions.
            api_key:        EDON API key.
            base_url:       EDON gateway URL.
            agent_id:       Agent identifier for the audit trail.
            intent_id:      Active intent contract ID.
            raise_on_block: Raise on blocked (True) or return error string (False).

        Returns:
            Governed tool list, drop-in compatible with CrewAI agents.
        """
        client = EdonClient(
            api_key=api_key,
            base_url=base_url,
            agent_id=agent_id,
            intent_id=intent_id,
            raise_on_block=False,
        )

        return [
            EdonCrewGuard._wrap_single(
                tool,
                client=client,
                agent_id=agent_id,
                intent_id=intent_id,
                raise_on_block=raise_on_block,
            )
            for tool in tools
        ]

    @staticmethod
    def _wrap_single(
        tool: Any,
        *,
        client: EdonClient,
        agent_id: str,
        intent_id: Optional[str],
        raise_on_block: bool,
    ) -> Any:
        # CrewAI tools are either BaseTool subclasses or @tool-decorated callables
        tool_name = _get_tool_name(tool)
        action_type = f"tool.{tool_name.lower().replace(' ', '_').replace('-', '_')}"

        # If it's a callable (function decorated with @tool)
        if callable(tool) and not _is_crewai_base_tool(tool):
            func = tool

            @functools.wraps(func)
            def governed_func(*args: Any, **kwargs: Any) -> Any:
                payload = _build_payload_from_call(func, args, kwargs)
                decision = client.evaluate(
                    action_type, payload,
                    agent_id=agent_id, intent_id=intent_id, raise_on_block=False,
                )
                if decision.blocked:
                    if raise_on_block:
                        raise EdonBlockedError(
                            decision.decision_reason,
                            action_id=decision.action_id,
                            reason_code=decision.reason_code,
                        )
                    return f"[EDON BLOCKED] {decision.decision_reason}"
                if decision.needs_human:
                    if raise_on_block:
                        raise EdonEscalatedError(
                            decision.decision_reason,
                            action_id=decision.action_id,
                            question=decision.escalation_question,
                        )
                    return f"[EDON ESCALATED] {decision.decision_reason}"
                return func(*args, **kwargs)

            # Preserve CrewAI tool metadata
            for attr in ("name", "description", "__doc__", "args_schema", "crewai_tool"):
                if hasattr(func, attr):
                    try:
                        setattr(governed_func, attr, getattr(func, attr))
                    except (AttributeError, TypeError):
                        pass

            return governed_func

        # If it's a BaseTool class instance, patch its _run method
        original_run = getattr(tool, "_run", None)
        if original_run is None:
            return tool  # Unknown type — return as-is

        @functools.wraps(original_run)
        def governed_run(*args: Any, **kwargs: Any) -> Any:
            payload = _build_payload_from_call(original_run, args, kwargs)
            # Remove 'self' from payload if present
            payload.pop("self", None)

            decision = client.evaluate(
                action_type, payload,
                agent_id=agent_id, intent_id=intent_id, raise_on_block=False,
            )
            if decision.blocked:
                if raise_on_block:
                    raise EdonBlockedError(
                        decision.decision_reason,
                        action_id=decision.action_id,
                        reason_code=decision.reason_code,
                    )
                return f"[EDON BLOCKED] {decision.decision_reason}"
            if decision.needs_human:
                if raise_on_block:
                    raise EdonEscalatedError(
                        decision.decision_reason,
                        action_id=decision.action_id,
                        question=decision.escalation_question,
                    )
                return f"[EDON ESCALATED] {decision.decision_reason}"
            return original_run(*args, **kwargs)

        tool._run = governed_run
        return tool


def _get_tool_name(tool: Any) -> str:
    for attr in ("name", "__name__", "__class__.__name__"):
        val = None
        if "." in attr:
            parts = attr.split(".")
            obj = tool
            for part in parts:
                obj = getattr(obj, part, None)
            val = obj
        else:
            val = getattr(tool, attr, None)
        if val and isinstance(val, str):
            return val
    return "unknown_tool"


def _is_crewai_base_tool(obj: Any) -> bool:
    try:
        from crewai.tools import BaseTool
        return isinstance(obj, BaseTool)
    except ImportError:
        return False


def _build_payload_from_call(func: Callable, args: tuple, kwargs: dict) -> Dict[str, Any]:
    try:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        return {k: v for k, v in bound.arguments.items() if k not in ("self", "cls")}
    except Exception:
        return {"args": list(args), "kwargs": kwargs}
