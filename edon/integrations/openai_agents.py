"""OpenAI Agents SDK integration for EDON governance.

Wraps OpenAI Agent tools so every tool call is evaluated by EDON before execution.

Usage::

    import openai
    from edon.integrations.openai_agents import EdonToolGuard

    # Wrap your tools
    tools = EdonToolGuard.wrap(
        tools=[send_email, search_web, read_file],
        api_key=os.environ["EDON_API_KEY"],
        agent_id="openai-agent-01",
    )

    # Use exactly like normal OpenAI tools
    agent = openai.Agent(
        name="Research Assistant",
        instructions="You are a helpful research assistant.",
        tools=tools,
    )
"""

from __future__ import annotations

import functools
import inspect
import json
import os
from typing import Any, Callable, Dict, List, Optional

from ..client import EdonClient
from ..exceptions import EdonBlockedError, EdonEscalatedError


def _is_openai_agents_available() -> bool:
    try:
        import openai  # noqa: F401
        return True
    except ImportError:
        return False


class EdonToolGuard:
    """Wraps OpenAI Agent SDK tools with EDON governance.

    Works with both the ``@function_tool`` decorator style and plain callables
    passed directly to ``openai.Agent(tools=[...])``.

    Usage::

        from edon.integrations.openai_agents import EdonToolGuard

        @function_tool
        def send_email(to: str, subject: str, body: str) -> str:
            \"\"\"Send an email.\"\"\"
            ...

        @function_tool
        def delete_file(path: str) -> str:
            \"\"\"Delete a file permanently.\"\"\"
            ...

        governed = EdonToolGuard.wrap(
            tools=[send_email, delete_file],
            api_key=os.environ["EDON_API_KEY"],
            agent_id="my-openai-agent",
        )
        agent = openai.Agent(tools=governed, ...)
    """

    @staticmethod
    def wrap(
        tools: List[Any],
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        agent_id: str = "openai-agent",
        intent_id: Optional[str] = None,
        raise_on_block: bool = True,
    ) -> List[Any]:
        """Wrap a list of OpenAI Agent tools with EDON governance.

        Args:
            tools:          List of tool functions (decorated with @function_tool or plain callables).
            api_key:        EDON API key.
            base_url:       EDON gateway URL.
            agent_id:       Agent identifier for the audit trail.
            intent_id:      Active intent contract ID.
            raise_on_block: Raise EdonBlockedError when blocked (True) or return error string (False).

        Returns:
            Governed versions of the same tools with identical signatures.
        """
        client = EdonClient(
            api_key=api_key,
            base_url=base_url,
            agent_id=agent_id,
            intent_id=intent_id,
            raise_on_block=False,
        )

        governed = []
        for tool in tools:
            governed.append(
                EdonToolGuard._wrap_single(
                    tool,
                    client=client,
                    agent_id=agent_id,
                    intent_id=intent_id,
                    raise_on_block=raise_on_block,
                )
            )
        return governed

    @staticmethod
    def _wrap_single(
        tool: Any,
        *,
        client: EdonClient,
        agent_id: str,
        intent_id: Optional[str],
        raise_on_block: bool,
    ) -> Any:
        # Resolve the actual callable — openai function_tool wraps it
        func = getattr(tool, "__wrapped__", tool) or tool
        func_name = getattr(func, "__name__", None) or getattr(tool, "name", "unknown_tool")
        action_type = f"tool.{func_name.lower().replace(' ', '_').replace('-', '_')}"

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_governed(*args: Any, **kwargs: Any) -> Any:
                payload = _build_payload(func, args, kwargs)
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
                return await func(*args, **kwargs)

            # Preserve openai SDK metadata
            _copy_tool_metadata(tool, async_governed)
            return async_governed

        else:
            @functools.wraps(func)
            def sync_governed(*args: Any, **kwargs: Any) -> Any:
                payload = _build_payload(func, args, kwargs)
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

            _copy_tool_metadata(tool, sync_governed)
            return sync_governed


def _build_payload(func: Callable, args: tuple, kwargs: dict) -> Dict[str, Any]:
    """Build action payload from function arguments."""
    try:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        return {k: v for k, v in bound.arguments.items() if k not in ("self", "cls")}
    except Exception:
        return {"args": list(args), "kwargs": kwargs}


def _copy_tool_metadata(source: Any, target: Callable) -> None:
    """Copy openai SDK tool metadata (schema, name, etc.) from source to target."""
    for attr in ("__name__", "name", "__doc__", "openai_schema", "model_json_schema",
                 "__openai_tool__", "metadata", "strict"):
        if hasattr(source, attr):
            try:
                setattr(target, attr, getattr(source, attr))
            except (AttributeError, TypeError):
                pass
