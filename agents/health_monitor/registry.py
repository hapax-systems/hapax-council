"""Check group registry: decorator and global registry dict."""

from __future__ import annotations

from collections.abc import Callable, Coroutine

from .models import CheckResult

# Check group -> list of async check functions
CHECK_REGISTRY: dict[str, list[Callable[[], Coroutine[None, None, list[CheckResult]]]]] = {}


def check_group(group: str):
    """Decorator to register check functions under a group name."""

    def decorator(fn: Callable[[], Coroutine[None, None, list[CheckResult]]]):
        CHECK_REGISTRY.setdefault(group, []).append(fn)
        return fn

    return decorator
