from __future__ import annotations

from pathlib import Path

from shared.sdlc_task_store import (
    ClaimDispatchBinding,
    claim_dispatch_binding_bytes,
    claim_dispatch_binding_path,
)


def write_claim_dispatch_binding_fixture(
    cache_dir: Path,
    claim_key: str,
    binding: ClaimDispatchBinding,
) -> Path:
    """Materialize a binding sidecar for tests that begin after claim publication."""
    path = claim_dispatch_binding_path(cache_dir, claim_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(claim_dispatch_binding_bytes(binding))
    return path
