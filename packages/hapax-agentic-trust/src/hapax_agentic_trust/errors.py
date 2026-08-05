"""Internal typed failure categories for stable public verification errors."""

from __future__ import annotations


class VerificationResourceLimitExceeded(ValueError):
    """Untrusted evidence exceeded an operator-selected availability ceiling."""


class VerificationCustodyFailure(ValueError):
    """A path, descriptor, inode, mode, link, or observed byte binding failed."""


class CallerAnchorVerificationFailure(ValueError):
    """Caller-supplied content anchors were absent, malformed, or did not match."""
