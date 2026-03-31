"""Resource lifecycle management for long-lived daemon resources.

Provides a registry that tracks ThreadPoolExecutors, subprocesses, and
other resources, and shuts them down in reverse registration order.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

log = logging.getLogger(__name__)

__all__ = ["ManagedResource", "ResourceRegistry", "ExecutorResource"]


class ManagedResource(Protocol):
    """Protocol for resources managed by the registry."""

    def stop(self) -> None: ...
    def is_alive(self) -> bool: ...


class ExecutorResource:
    """Adapter wrapping a ThreadPoolExecutor as a ManagedResource."""

    def __init__(self, executor: ThreadPoolExecutor) -> None:
        self._executor = executor
        self._stopped = False

    def stop(self) -> None:
        self._executor.shutdown(wait=False)
        self._stopped = True

    def is_alive(self) -> bool:
        return not self._stopped


class ResourceRegistry:
    """Tracks and shuts down daemon resources in reverse order."""

    def __init__(self) -> None:
        self._resources: list[tuple[str, ManagedResource]] = []

    def register(self, name: str, resource: ManagedResource) -> None:
        self._resources.append((name, resource))

    def stop_all(self, timeout: float = 5.0) -> list[str]:
        """Stop all resources in reverse registration order.

        Returns list of resource names that failed to stop.
        """
        failed: list[str] = []
        for name, resource in reversed(self._resources):
            if not resource.is_alive():
                continue
            try:
                resource.stop()
            except Exception:
                log.warning("Failed to stop resource %s", name, exc_info=True)
                failed.append(name)
        self._resources.clear()
        return failed
