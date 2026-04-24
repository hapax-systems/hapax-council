"""Integrity verification — detect drift between on-disk bytes and manifest SHA-256."""

from __future__ import annotations


class IntegrityError(Exception):
    """Raised when explicit integrity enforcement finds drift."""

    def __init__(self, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.details = details or []
