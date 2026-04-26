"""Read-only contract test — payment_processors must never INITIATE value.

Constitutional invariant:
    The receive-only rails (Lightning, Nostr Zap, Liberapay) are
    structurally incapable of *initiating* payment. This test scans
    the package source for forbidden verbs and fails if any appears
    as a method, function, or class member name.

A separate runtime check (smoke test) verifies that the public API
surfaces only ``poll_once`` / ``run_forever`` / ``stop`` / ``ingest``
verbs — never ``send`` / ``initiate`` / ``payout`` / ``transfer``.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import agents.payment_processors as pp_pkg

FORBIDDEN_VERBS: tuple[str, ...] = (
    "send",
    "initiate",
    "payout",
    "transfer",
    "withdraw",
    "pay",
    "remit",
)

# Specific tokens that ARE allowed (false positives in the simple
# substring scan): things like ``send_count`` would be ambiguous, but
# we don't expect those. We allow shared.chronicle's ``send`` if it's
# referenced — but this test only scans the payment_processors source
# tree, never shared/.


def _package_root() -> Path:
    file = inspect.getfile(pp_pkg)
    return Path(file).parent


def _iter_source_files() -> list[Path]:
    root = _package_root()
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _names_in(file: Path) -> set[str]:
    """Collect every defined name (function, async function, class, method)."""
    src = file.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
    return names


@pytest.mark.parametrize("source_file", _iter_source_files(), ids=lambda p: p.name)
def test_no_forbidden_verb_definitions(source_file: Path) -> None:
    """No def/class in the package may be named with a forbidden verb."""
    names = _names_in(source_file)
    offenders: list[str] = []
    for name in names:
        lower = name.lower()
        for verb in FORBIDDEN_VERBS:
            # Exact match or starts-with-verb pattern: ``send_invoice``
            # / ``initiate_payment`` / ``payout_handler``.
            if lower == verb or lower.startswith(f"{verb}_"):
                offenders.append(name)
                break
    assert not offenders, (
        f"{source_file.name}: forbidden verb in defs {offenders}; "
        "receive-only rails must never define send/initiate/payout/transfer "
        "names. Constitutional contract — see "
        "tests/payment_processors/test_read_only_contract.py."
    )


def test_public_api_exposes_no_forbidden_verbs() -> None:
    """Re-exported names from agents.payment_processors must be receive-only."""
    public_names = set(getattr(pp_pkg, "__all__", []))
    offenders: list[str] = []
    for name in public_names:
        lower = name.lower()
        for verb in FORBIDDEN_VERBS:
            if lower == verb or lower.startswith(f"{verb}_"):
                offenders.append(name)
                break
    assert not offenders, (
        f"agents.payment_processors.__all__ exports forbidden verb names: {offenders}"
    )


def test_each_receiver_class_has_no_initiate_methods() -> None:
    """Verify the three receiver classes have no initiate-style methods."""
    from agents.payment_processors.liberapay_receiver import LiberapayReceiver
    from agents.payment_processors.lightning_receiver import LightningReceiver
    from agents.payment_processors.nostr_zap_listener import NostrZapListener

    for klass in (LightningReceiver, NostrZapListener, LiberapayReceiver):
        method_names = {
            name
            for name, _ in inspect.getmembers(klass, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        offenders = [
            name
            for name in method_names
            if any(name.lower() == v or name.lower().startswith(f"{v}_") for v in FORBIDDEN_VERBS)
        ]
        assert not offenders, f"{klass.__name__} exposes forbidden methods: {offenders}"
