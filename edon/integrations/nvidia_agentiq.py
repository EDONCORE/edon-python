"""NVIDIA NeMo Agent Toolkit (AgentIQ) integration for EDON governance.

Wraps async callables so every invocation is evaluated by EDON before execution.
Compatible with ``FunctionInfo.from_fn()`` — just wrap your function first.

Usage::

    from aiq.builder.function_info import FunctionInfo
    from edon.integrations.nvidia_agentiq import EdonNvidiaGuard

    async def send_email(to: str, subject: str, body: str) -> str:
        \"\"\"Send an email.\"\"\"
        ...

    async def search_web(query: str) -> str:
        \"\"\"Search the internet.\"\"\"
        ...

    # One-liner: wrap before passing to FunctionInfo
    governed = EdonNvidiaGuard.wrap_fns(
        fns=[send_email, search_web],
        api_key=os.environ["EDON_API_KEY"],
        agent_id="nvidia-agent-01",
    )

    # Drop-in for FunctionInfo.from_fn()
    yield FunctionInfo.from_fn(governed[0], description="Send an email")
    yield FunctionInfo.from_fn(governed[1], description="Search the web")

Single-function variant::

    governed_fn = EdonNvidiaGuard.wrap_fn(
        send_email,
        api_key=os.environ["EDON_API_KEY"],
        agent_id="nvidia-agent-01",
    )
    yield FunctionInfo.from_fn(governed_fn, description="Send an email")
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, List, Optional

from ..client import EdonClient
from ..exceptions import EdonBlockedError, EdonEscalatedError


class EdonNvidiaGuard:
    """Wraps NVIDIA NeMo Agent Toolkit callables with EDON governance.

    Every function call is evaluated by EDON before execution. Blocked actions
    raise ``EdonBlockedError`` and are never executed.

    Works with async callables intended for ``FunctionInfo.from_fn()``.
    All EDON metadata (name, docstring, type annotations) is preserved so the
    NeMo toolkit can still introspect the wrapped function correctly.

    Usage::

        from edon.integrations.nvidia_agentiq import EdonNvidiaGuard

        governed = EdonNvidiaGuard.wrap_fns(
            fns=[send_email, delete_record],
            api_key=os.environ["EDON_API_KEY"],
            agent_id="my-nvidia-agent",
            intent_id="intent_founder_mode_xxx",
        )
    """

    @staticmethod
    def wrap_fns(
        fns: List[Callable],
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        agent_id: str = "nvidia-agent",
        intent_id: Optional[str] = None,
        raise_on_block: bool = True,
    ) -> List[Callable]:
        """Wrap a list of async callables with EDON governance.

        Args:
            fns:            List of async callables to govern.
            api_key:        EDON API key (default: ``EDON_API_KEY`` env var).
            base_url:       EDON gateway URL (default: ``EDON_BASE_URL`` env var or cloud).
            agent_id:       Agent identifier for the audit trail.
            intent_id:      Active intent contract ID.
            raise_on_block: Raise ``EdonBlockedError`` on BLOCK (True) or return
                            error string (False).

        Returns:
            Governed callables with identical signatures and metadata, ready for
            ``FunctionInfo.from_fn()``.
        """
        client = EdonClient(
            api_key=api_key,
            base_url=base_url,
            agent_id=agent_id,
            intent_id=intent_id,
            raise_on_block=False,
        )

        return [
            EdonNvidiaGuard._wrap_single(
                fn,
                client=client,
                agent_id=agent_id,
                intent_id=intent_id,
                raise_on_block=raise_on_block,
            )
            for fn in fns
        ]

    @staticmethod
    def wrap_fn(
        fn: Callable,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        agent_id: str = "nvidia-agent",
        intent_id: Optional[str] = None,
        raise_on_block: bool = True,
    ) -> Callable:
        """Wrap a single async callable with EDON governance.

        Args:
            fn:             Async callable to govern.
            api_key:        EDON API key (default: ``EDON_API_KEY`` env var).
            base_url:       EDON gateway URL (default: ``EDON_BASE_URL`` env var or cloud).
            agent_id:       Agent identifier for the audit trail.
            intent_id:      Active intent contract ID.
            raise_on_block: Raise ``EdonBlockedError`` on BLOCK (True) or return
                            error string (False).

        Returns:
            Governed callable, drop-in for ``FunctionInfo.from_fn()``.
        """
        client = EdonClient(
            api_key=api_key,
            base_url=base_url,
            agent_id=agent_id,
            intent_id=intent_id,
            raise_on_block=False,
        )
        return EdonNvidiaGuard._wrap_single(
            fn,
            client=client,
            agent_id=agent_id,
            intent_id=intent_id,
            raise_on_block=raise_on_block,
        )

    @staticmethod
    def _wrap_single(
        fn: Callable,
        *,
        client: EdonClient,
        agent_id: str,
        intent_id: Optional[str],
        raise_on_block: bool,
    ) -> Callable:
        fn_name = getattr(fn, "__name__", "unknown_fn")
        action_type = f"tool.{fn_name.lower().replace(' ', '_').replace('-', '_')}"

        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_governed(*args: Any, **kwargs: Any) -> Any:
                payload = _build_payload(fn, args, kwargs)
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
                return await fn(*args, **kwargs)

            # Preserve annotations so NeMo toolkit can build the input schema
            async_governed.__annotations__ = getattr(fn, "__annotations__", {})
            return async_governed

        else:
            # Sync fallback — NeMo toolkit is async-first but handle both
            @functools.wraps(fn)
            def sync_governed(*args: Any, **kwargs: Any) -> Any:
                payload = _build_payload(fn, args, kwargs)
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
                return fn(*args, **kwargs)

            sync_governed.__annotations__ = getattr(fn, "__annotations__", {})
            return sync_governed


def _build_payload(fn: Callable, args: tuple, kwargs: dict) -> dict:
    """Build action payload from function arguments."""
    try:
        sig = inspect.signature(fn)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        return {k: v for k, v in bound.arguments.items() if k not in ("self", "cls")}
    except Exception:
        return {"args": list(args), "kwargs": kwargs}
