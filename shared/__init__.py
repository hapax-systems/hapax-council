from __future__ import annotations

__all__ = ["HostStorageRegistry"]


def __getattr__(name: str) -> object:
    if name == "HostStorageRegistry":
        from shared.host_storage_model import HostStorageRegistry

        return HostStorageRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
