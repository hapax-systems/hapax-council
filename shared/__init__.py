from __future__ import annotations

__all__ = ["DriftReport", "HostStorageRegistry", "evaluate_infra_drift"]


def __getattr__(name: str) -> object:
    if name in {"DriftReport", "evaluate_infra_drift"}:
        from shared.infra_drift import DriftReport, evaluate_infra_drift

        return {"DriftReport": DriftReport, "evaluate_infra_drift": evaluate_infra_drift}[name]
    if name == "HostStorageRegistry":
        from shared.host_storage_model import HostStorageRegistry

        return HostStorageRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
