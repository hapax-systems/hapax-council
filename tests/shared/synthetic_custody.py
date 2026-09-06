"""Synthetic private custody for every test that touches the consent registry.

The estate registry is bound `required` (shared/governance/consent.py) and refuses
identity operations without a validated custody document; a test process must
therefore supply one. This module holds the single fixture that does so, with a
wholly synthetic correspondence document in a temporary FileStore built from the
installed reins API. It is registered as an autouse fixture by tests/conftest.py
and packages/agentgov/tests/conftest.py, so a partial run (one module, one
directory) sees the same custody a full run does; nothing depends on which test
module happened to be collected first.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest
from agentgov import consent as portable

ENTRY = "consent-identifier-compatibility"
PRINCIPAL = "synthetic-successor-subject"
CONTRACT = "synthetic-successor-contract"
OLD_PRINCIPAL = "synthetic-predecessor-subject"
OLD_CONTRACT = "synthetic-predecessor-contract"
UNKNOWN_PRINCIPAL = "synthetic-unknown-subject"
UNKNOWN_CONTRACT = "synthetic-unknown-contract"


def document():
    return {
        "version": 1,
        "principals": {OLD_PRINCIPAL: PRINCIPAL},
        "contracts": {OLD_CONTRACT: CONTRACT},
        "inventory": [OLD_PRINCIPAL, OLD_CONTRACT],
    }


def installed_api() -> Path:
    """The installed reins API: a declared HAPAX_REINS_API wins over the home default."""
    return Path(
        os.environ.get("HAPAX_REINS_API", "").strip()
        or (Path.home() / ".local" / "share" / "reins" / "current" / "api")
    )


@pytest.fixture(autouse=True)
def synthetic_custody(monkeypatch, tmp_path_factory):
    # Only installed API source is imported; every store is explicitly temporary.
    # A declared HAPAX_REINS_API wins over the home-relative default, exactly as the
    # resolver resolves it, so a verification run under a throwaway HOME can still
    # reach the installed API without touching the real home's state.
    api = installed_api()
    monkeypatch.setenv("HAPAX_REINS_API", str(api))
    # Plugin users may assert that their own tmp_path contains only their output.
    # Give custody a separate per-test directory so it cannot pollute that surface.
    custody_root = tmp_path_factory.mktemp("synthetic-custody") / "custody"
    monkeypatch.setenv("REINS_SECRET_STORE", str(custody_root))
    monkeypatch.syspath_prepend(str(api))
    key_capture = importlib.import_module("k0.key_capture")
    store = key_capture.FileStore(root=custody_root)
    store.put(ENTRY, json.dumps(document()).encode())
    monkeypatch.setattr(portable, "_configured_binding", None)
    monkeypatch.setenv("AGENTGOV_IDENTITY_MIGRATION", "required")
    monkeypatch.setenv("AGENTGOV_IDENTITY_PROVIDER", "shared.governance.consent")
    return store
