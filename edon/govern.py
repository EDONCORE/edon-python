"""@govern decorator — add EDON governance to any Python function in one line."""

from __future__ import annotations

import functools
import inspect
import os
from typing import Any, Callable, Dict, Optional, TypeVar, Union

from .client import EdonClient
from .exceptions import EdonBlockedError

F = TypeVar("F", bound=Callable[..., Any])

# Module-level default client (configured once, used everywhere)
_default_client: Optional[EdonClient] = None


def configure(
    api_key: Optional[str] = None,
    *,
    base_url: Optional[str] = None,
    agent_id: Optional[str] = None,
    intent_id: Optional[str] = None,
    raise_on_block: bool = True,
) -> EdonClient:
    """Configure the module-level EDON client used by @govern.

    Call once at application startup::

        import edon
        edon.configure(api_key="your-key", intent_id="intent_founder_mode_xxx")

    Returns the configured client for direct use if needed.
    """
    global _default_client
    _default_client = EdonClient(
        api_key=api_key,
        base_url=base_url,
        agent_id=agent_id,
        intent_id=intent_id,
        raise_on_block=raise_on_block,
    )
    return _default_client


def _get_default_client() -> EdonClient:
    global _default_client
    if _default_client is None:
        _default_client = EdonClient(raise_on_block=True)
    return _default_client


def govern(
    action_type: Optional[str] = None,
    *,
    agent_id: Optional[str] = None,
    intent_id: Optional[str] = None,
    payload_from: Optional[Callable[..., Dict[str, Any]]] = None,
    client: Optional[EdonClient] = None,
    raise_on_block: bool = True,
) -> Callable[[F], F]:
    """Decorator that governs a function call through EDON before executing it.

    EDON intercepts the function call, evaluates the action, and either:
    - **Allows** it → function runs normally
    - **Blocks** it → raises ``EdonBlockedError`` (function never runs)
    - **Requires human approval** → raises ``EdonEscalatedError``

    Args:
        action_type:  The ``tool.operation`` string (default: ``module.function_name``).
        agent_id:     Agent identifier (overrides client default).
        intent_id:    Intent contract ID (overrides client default).
        payload_from: Callable that maps ``(args, kwargs)`` → payload dict.
                      Defaults to passing all kwargs as payload.
        client:       EDON client to use (defaults to module-level client).
        raise_on_block: Raise on BLOCK/ESCALATE (default True).

    Examples::

        # Basic usage — action_type inferred from function name
        @govern()
        def send_email(to: str, subject: str, body: str) -> None:
            ...

        # Explicit action_type
        @govern(action_type="email.send")
        def send_email(to: str, subject: str, body: str) -> None:
            ...

        # Custom payload extractor
        @govern(
            action_type="database.delete",
            payload_from=lambda args, kw: {"table": kw["table"], "where": kw["condition"]},
        )
        def delete_records(table: str, condition: str) -> int:
            ...
    """

    def decorator(func: F) -> F:
        inferred_action = action_type or f"{func.__module__.split('.')[-1]}.{func.__name__}"

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            edon = client or _get_default_client()

            if payload_from is not None:
                payload = payload_from(args, kwargs)
            else:
                # Build payload from function signature
                sig = inspect.signature(func)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                payload = {k: v for k, v in bound.arguments.items() if k != "self"}

            decision = edon.evaluate(
                inferred_action,
                payload,
                agent_id=agent_id,
                intent_id=intent_id,
                raise_on_block=raise_on_block,
            )

            if not decision.allowed and not raise_on_block:
                # Silent mode — return None without executing
                return None

            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            from .client import AsyncEdonClient
            # For async functions, use a fresh async client per call
            # (or reuse if one is passed in)
            api_key = os.environ.get("EDON_API_KEY") or os.environ.get("EDON_API_TOKEN")
            base_url = os.environ.get("EDON_BASE_URL") or os.environ.get("EDON_GATEWAY_URL")

            if payload_from is not None:
                payload = payload_from(args, kwargs)
            else:
                sig = inspect.signature(func)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                payload = {k: v for k, v in bound.arguments.items() if k != "self"}

            async with AsyncEdonClient(
                api_key=api_key,
                base_url=base_url,
                agent_id=agent_id,
                raise_on_block=raise_on_block,
            ) as async_client:
                decision = await async_client.evaluate(
                    inferred_action,
                    payload,
                    agent_id=agent_id,
                    intent_id=intent_id,
                    raise_on_block=raise_on_block,
                )

            if not decision.allowed and not raise_on_block:
                return None

            return await func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator
