"""Pin agents/_browser_services.py against non-dict JSON corruption.

Thirty-third site. Mirror of the fix already merged for
``shared/browser_services.py`` (#2667). The agents/ vendored copy of
``load_registry`` had the same bug — ``registry.values()`` and
``registry.get(service)`` callers would crash on non-dict JSON roots.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents import _browser_services as bs


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_load_registry_non_dict_returns_empty(tmp_path: Path, payload: str, kind: str) -> None:
    """A corrupt registry file with non-dict JSON root must not crash
    the URL allowlist / resolver."""
    registry_path = tmp_path / "browser-services.json"
    registry_path.write_text(payload)
    with patch.object(bs, "REGISTRY_PATH", registry_path):
        assert bs.load_registry() == {}, f"non-dict root={kind} must yield empty"
        # Downstream consumers must not raise.
        assert bs.is_allowed("https://example.com") is False
        assert bs.resolve_url("any", "any") is None
