"""EDON core API client — sync and async."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import httpx
from pydantic import BaseModel

from .exceptions import (
    EdonAuthError,
    EdonBlockedError,
    EdonConnectionError,
    EdonDegradedError,
    EdonEscalatedError,
    EdonRateLimitError,
)

_DEFAULT_BASE_URL = "https://edon-gateway.fly.dev"
_DEFAULT_TIMEOUT = 10.0


# ─────────────────────────────────────────────
# Response models
# ─────────────────────────────────────────────

class Decision(BaseModel):
    """Governance decision returned by EDON."""
    action_id: str
    decision: str  # ALLOW | BLOCK | DEGRADE | HUMAN_REQUIRED | PAUSE
    decision_reason: str
    policy_version: Optional[str] = None
    processing_latency_ms: int = 0
    reason_code: Optional[str] = None
    safe_alternative: Optional[Dict[str, Any]] = None
    escalation_question: Optional[str] = None
    escalation_options: Optional[List[Any]] = None

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"

    @property
    def blocked(self) -> bool:
        return self.decision == "BLOCK"

    @property
    def needs_human(self) -> bool:
        return self.decision in ("HUMAN_REQUIRED", "ESCALATE")


# ─────────────────────────────────────────────
# Sync client
# ─────────────────────────────────────────────

class EdonClient:
    """Synchronous EDON governance client.

    Usage::

        from edon import EdonClient

        client = EdonClient(api_key="your-key")
        decision = client.evaluate(
            agent_id="my-agent",
            action_type="email.send",
            action_payload={"to": "user@example.com", "subject": "Hello"},
        )
        if decision.blocked:
            raise RuntimeError(decision.decision_reason)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        agent_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        raise_on_block: bool = False,
    ):
        self.api_key = api_key or os.environ.get("EDON_API_KEY") or os.environ.get("EDON_API_TOKEN")
        if not self.api_key:
            raise EdonAuthError(
                "No EDON API key provided. Pass api_key= or set EDON_API_KEY env var."
            )
        self.base_url = (
            base_url
            or os.environ.get("EDON_BASE_URL")
            or os.environ.get("EDON_GATEWAY_URL")
            or _DEFAULT_BASE_URL
        ).rstrip("/")
        self.agent_id = agent_id or os.environ.get("EDON_AGENT_ID", "edon-sdk-agent")
        self.intent_id = intent_id or os.environ.get("EDON_INTENT_ID")
        self.raise_on_block = raise_on_block
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"X-EDON-TOKEN": self.api_key},
            timeout=timeout,
        )

    def evaluate(
        self,
        action_type: str,
        action_payload: Dict[str, Any],
        *,
        agent_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        raise_on_block: Optional[bool] = None,
    ) -> Decision:
        """Evaluate an agent action through the EDON governance engine.

        Args:
            action_type:    Action in ``tool.operation`` format (e.g. ``email.send``).
            action_payload: Free-form dict of action parameters.
            agent_id:       Override the default agent_id for this call.
            intent_id:      Override the default intent_id for this call.
            context:        Additional context merged into the request.
            raise_on_block: Override the client-level raise_on_block setting.

        Returns:
            :class:`Decision` with the governance verdict and metadata.

        Raises:
            EdonBlockedError:    If the action is blocked and ``raise_on_block`` is True.
            EdonEscalatedError:  If human approval is required and ``raise_on_block`` is True.
            EdonConnectionError: If the gateway is unreachable.
        """
        effective_intent = intent_id or self.intent_id
        ctx: Dict[str, Any] = dict(context or {})
        if effective_intent:
            ctx["intent_id"] = effective_intent

        payload = {
            "agent_id": agent_id or self.agent_id,
            "action_type": action_type,
            "action_payload": action_payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "context": ctx,
        }

        try:
            response = self._http.post("/v1/action", json=payload)
        except httpx.ConnectError as exc:
            raise EdonConnectionError(f"EDON gateway unreachable at {self.base_url}") from exc
        except httpx.TimeoutException as exc:
            raise EdonConnectionError(f"EDON gateway timed out after {self._http.timeout}s") from exc

        if response.status_code == 401:
            raise EdonAuthError("Invalid EDON API key. Check EDON_API_KEY.")
        if response.status_code == 429:
            raise EdonRateLimitError("EDON quota exceeded. Upgrade your plan at edoncore.com.")
        if response.status_code >= 500:
            raise EdonConnectionError(f"EDON gateway error: {response.status_code} {response.text[:200]}")

        data = response.json()
        decision = Decision(**data)

        should_raise = raise_on_block if raise_on_block is not None else self.raise_on_block
        if should_raise:
            if decision.blocked:
                raise EdonBlockedError(
                    decision.decision_reason,
                    action_id=decision.action_id,
                    reason_code=decision.reason_code,
                    policy_version=decision.policy_version,
                )
            if decision.needs_human:
                raise EdonEscalatedError(
                    decision.decision_reason,
                    action_id=decision.action_id,
                    question=decision.escalation_question,
                    escalation_options=decision.escalation_options,
                )
            if decision.decision == "DEGRADE" and decision.safe_alternative:
                raise EdonDegradedError(
                    decision.decision_reason,
                    action_id=decision.action_id,
                    safe_alternative=decision.safe_alternative,
                )

        return decision

    def ping(self) -> bool:
        """Return True if the gateway is healthy."""
        try:
            r = self._http.get("/health", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "EdonClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


# ─────────────────────────────────────────────
# Async client
# ─────────────────────────────────────────────

class AsyncEdonClient:
    """Asynchronous EDON governance client.

    Usage::

        async with AsyncEdonClient(api_key="your-key") as client:
            decision = await client.evaluate(
                agent_id="my-agent",
                action_type="email.send",
                action_payload={"to": "user@example.com"},
            )
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        agent_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        raise_on_block: bool = False,
    ):
        self.api_key = api_key or os.environ.get("EDON_API_KEY") or os.environ.get("EDON_API_TOKEN")
        if not self.api_key:
            raise EdonAuthError(
                "No EDON API key provided. Pass api_key= or set EDON_API_KEY env var."
            )
        self.base_url = (
            base_url
            or os.environ.get("EDON_BASE_URL")
            or os.environ.get("EDON_GATEWAY_URL")
            or _DEFAULT_BASE_URL
        ).rstrip("/")
        self.agent_id = agent_id or os.environ.get("EDON_AGENT_ID", "edon-sdk-agent")
        self.intent_id = intent_id or os.environ.get("EDON_INTENT_ID")
        self.raise_on_block = raise_on_block
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-EDON-TOKEN": self.api_key},
            timeout=timeout,
        )

    async def evaluate(
        self,
        action_type: str,
        action_payload: Dict[str, Any],
        *,
        agent_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        raise_on_block: Optional[bool] = None,
    ) -> Decision:
        """Evaluate an agent action asynchronously."""
        effective_intent = intent_id or self.intent_id
        ctx: Dict[str, Any] = dict(context or {})
        if effective_intent:
            ctx["intent_id"] = effective_intent

        payload = {
            "agent_id": agent_id or self.agent_id,
            "action_type": action_type,
            "action_payload": action_payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "context": ctx,
        }

        try:
            response = await self._http.post("/v1/action", json=payload)
        except httpx.ConnectError as exc:
            raise EdonConnectionError(f"EDON gateway unreachable at {self.base_url}") from exc
        except httpx.TimeoutException as exc:
            raise EdonConnectionError(f"EDON gateway timed out") from exc

        if response.status_code == 401:
            raise EdonAuthError("Invalid EDON API key.")
        if response.status_code == 429:
            raise EdonRateLimitError("EDON quota exceeded.")
        if response.status_code >= 500:
            raise EdonConnectionError(f"EDON gateway error: {response.status_code}")

        data = response.json()
        decision = Decision(**data)

        should_raise = raise_on_block if raise_on_block is not None else self.raise_on_block
        if should_raise:
            if decision.blocked:
                raise EdonBlockedError(
                    decision.decision_reason,
                    action_id=decision.action_id,
                    reason_code=decision.reason_code,
                )
            if decision.needs_human:
                raise EdonEscalatedError(
                    decision.decision_reason,
                    action_id=decision.action_id,
                    question=decision.escalation_question,
                )

        return decision

    async def ping(self) -> bool:
        try:
            r = await self._http.get("/health", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncEdonClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()
