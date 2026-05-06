"""Pin GPU memory adapter against non-dict infra-snapshot.json.

Forty-seventh site. The Logos API's GPU-memory adapter reads
``infra-snapshot.json`` then calls ``data.get(\"gpu\")`` outside the
``(FileNotFoundError, json.JSONDecodeError, OSError)`` catch. A
writer producing valid JSON whose root is null, a list, a string, or
a number raised AttributeError out of the API endpoint.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_gpu_memory_used_total_non_dict_returns_zero(
    tmp_path: Path, payload: str, kind: str
) -> None:
    """A corrupt infra-snapshot with non-dict JSON root must yield
    (0, 0) instead of crashing the API endpoint."""
    snapshot = tmp_path / "infra-snapshot.json"
    snapshot.write_text(payload)
    with patch("logos._config.PROFILES_DIR", tmp_path):
        from logos.api.app import LogosGpuBridge

        used, total = LogosGpuBridge().gpu_memory_used_total()
    assert (used, total) == (0, 0), f"non-dict root={kind} must yield (0, 0)"


def test_gpu_memory_used_total_dict_root_with_non_dict_gpu_field(tmp_path: Path) -> None:
    """Pin: dict root with non-dict 'gpu' field falls back to (0, 0)."""
    import json

    snapshot = tmp_path / "infra-snapshot.json"
    snapshot.write_text(json.dumps({"gpu": "not-a-dict"}))
    with patch("logos._config.PROFILES_DIR", tmp_path):
        from logos.api.app import LogosGpuBridge

        used, total = LogosGpuBridge().gpu_memory_used_total()
    assert (used, total) == (0, 0)


def test_gpu_memory_used_total_dict_root_with_valid_gpu(tmp_path: Path) -> None:
    """Sanity pin: well-formed payload returns the parsed values."""
    import json

    snapshot = tmp_path / "infra-snapshot.json"
    snapshot.write_text(json.dumps({"gpu": {"used_mb": 1024, "total_mb": 24576}}))
    with patch("logos._config.PROFILES_DIR", tmp_path):
        from logos.api.app import LogosGpuBridge

        used, total = LogosGpuBridge().gpu_memory_used_total()
    assert used == 1024
    assert total == 24576
