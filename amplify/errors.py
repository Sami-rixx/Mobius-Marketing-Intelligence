"""Explicit failure types.

Every failure is one of these; none of them is silently swallowed. The cycle marks the
week DEGRADED and preserves the reason (docs/01-architecture.md, docs/06-limits.md).
"""

from __future__ import annotations


class AmplifyError(Exception):
    """Base class for all engine errors."""


class ConfigError(AmplifyError):
    """config.yaml is missing, malformed, or incomplete."""


class SchemaError(AmplifyError):
    """An instance failed JSON-schema validation."""

    def __init__(self, schema_name: str, problems: list[str]):
        self.schema_name = schema_name
        self.problems = problems
        super().__init__(f"{schema_name}: " + "; ".join(problems))


class StopCondition(AmplifyError):
    """A documented agent stop-condition. The branch halts; nothing is guessed."""

    def __init__(self, agent: str, reason: str):
        self.agent = agent
        self.reason = reason
        super().__init__(f"STOP [{agent}] {reason}")


class BudgetExceeded(AmplifyError):
    """The monthly token budget is exhausted; the runner refuses to start."""


class ClaimError(AmplifyError):
    """A claim is missing, expired, or quarantined."""

    def __init__(self, problems: list[str], claim_ids: list[str] | None = None):
        self.problems = problems
        self.claim_ids = claim_ids or []
        super().__init__("; ".join(problems))


class GateFailure(AmplifyError):
    """A validation gate failed (content CI, review, publication recording)."""


class TransitionError(AmplifyError):
    """An illegal status transition, or an actor doing something it may not do."""


class TransientError(AmplifyError):
    """A retriable failure from the model API (timeout, 5xx, rate limit)."""


class PermanentError(AmplifyError):
    """A non-retriable failure from the model API (bad request, auth)."""
