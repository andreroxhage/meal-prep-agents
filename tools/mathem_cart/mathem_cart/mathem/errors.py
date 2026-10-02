"""Exceptions raised by the Mathem client. Messages never contain credentials."""

from __future__ import annotations


class MathemError(Exception):
    """Base class."""


class ForbiddenEndpoint(MathemError):
    """A request outside the allowlist was attempted. Raised before sending."""


class MathemAuthError(MathemError):
    """Login failed or the session is no longer valid (401/403)."""


class MathemRequestError(MathemError):
    def __init__(self, status: int, method: str, path: str, body: str | None = None, *,
                 hint: str | None = None):
        self.status = status
        self.method = method
        self.path = path
        self.body = body
        super().__init__(f"{method} {path} -> HTTP {status}" + (f": {hint}" if hint else ""))


class MathemProtocolError(MathemError):
    """Response had an unexpected shape; the message names endpoint and field."""
