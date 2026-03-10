"""EDON SDK exceptions."""

from __future__ import annotations
from typing import Optional


class EdonError(Exception):
    """Base exception for all EDON errors."""
    pass


class EdonBlockedError(EdonError):
    """Raised when EDON blocks an agent action.

    Attributes:
        action_id:      Unique audit trail ID for this decision.
        reason:         Human-readable explanation.
        reason_code:    Machine-readable code (e.g. OUT_OF_SCOPE).
        policy_version: Policy version that produced the decision.
    """

    def __init__(
        self,
        reason: str,
        *,
        action_id: Optional[str] = None,
        reason_code: Optional[str] = None,
        policy_version: Optional[str] = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.action_id = action_id
        self.reason_code = reason_code
        self.policy_version = policy_version

    def __repr__(self) -> str:
        return (
            f"EdonBlockedError(reason={self.reason!r}, "
            f"reason_code={self.reason_code!r}, action_id={self.action_id!r})"
        )


class EdonEscalatedError(EdonError):
    """Raised when EDON requires human approval before the action can proceed.

    Attributes:
        action_id:           Audit trail ID — pass to /v1/approval to resolve.
        question:            Question to show the human approver.
        escalation_options:  Options the human can choose from.
    """

    def __init__(
        self,
        reason: str,
        *,
        action_id: Optional[str] = None,
        question: Optional[str] = None,
        escalation_options: Optional[list] = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.action_id = action_id
        self.question = question
        self.escalation_options = escalation_options or []


class EdonDegradedError(EdonError):
    """Raised when EDON degrades an action to a safer alternative.

    Attributes:
        safe_alternative: The alternative action EDON recommends.
    """

    def __init__(
        self,
        reason: str,
        *,
        action_id: Optional[str] = None,
        safe_alternative: Optional[dict] = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.action_id = action_id
        self.safe_alternative = safe_alternative


class EdonConnectionError(EdonError):
    """Raised when the EDON gateway is unreachable."""
    pass


class EdonAuthError(EdonError):
    """Raised when the API key is invalid or missing."""
    pass


class EdonRateLimitError(EdonError):
    """Raised when the tenant quota is exceeded."""
    pass
