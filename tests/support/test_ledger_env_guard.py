"""Proof for the money-rail ledger env leak predicate + fixture engagement.

Two layers:

* Narrow, deterministic unit proofs of the detection *predicate*
  (``resource_receipt_env_leak_reason``) in isolation.
* A real negative integration probe that runs a nested pytest whose test
  persistently escapes the ledger env (without emitting) and asserts the nested
  run fails at teardown with the exact detector reason — proving the autouse
  isolation fixture in ``tests/conftest.py`` actually engages. A pure-predicate
  test cannot stand in for that fixture-engagement/order evidence.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from agents.payment_processors.resource_receipts import (
    DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH,
    MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
)
from tests.support.ledger_env_guard import resource_receipt_env_leak_reason

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Predicate unit proofs ──────────────────────────────────────────────


def test_per_test_ledger_is_not_a_leak(tmp_path) -> None:
    value = str(tmp_path / "resource-receipts.jsonl")
    assert resource_receipt_env_leak_reason(value, allowed_root=tmp_path.resolve()) is None


def test_different_within_root_filename_is_not_a_leak(tmp_path) -> None:
    # Containment, not exact equality: a different ledger filename inside the same
    # per-test root is legitimate (support-copy tests use this exact filename).
    value = str(tmp_path / "money-rail-resource-receipts.jsonl")
    assert resource_receipt_env_leak_reason(value, allowed_root=tmp_path.resolve()) is None


def test_nested_within_root_path_is_not_a_leak(tmp_path) -> None:
    value = str(tmp_path / "sub" / "dir" / "resource-receipts.jsonl")
    assert resource_receipt_env_leak_reason(value, allowed_root=tmp_path.resolve()) is None


def test_unset_env_is_a_leak(tmp_path) -> None:
    reason = resource_receipt_env_leak_reason(None, allowed_root=tmp_path.resolve())
    assert reason is not None
    assert "unset" in reason


def test_empty_env_is_a_leak(tmp_path) -> None:
    reason = resource_receipt_env_leak_reason("", allowed_root=tmp_path.resolve())
    assert reason is not None
    assert "unset" in reason


def test_canonical_live_ledger_is_a_leak(tmp_path) -> None:
    reason = resource_receipt_env_leak_reason(
        str(DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH), allowed_root=tmp_path.resolve()
    )
    assert reason is not None
    assert "canonical live ledger" in reason


def test_dotdot_alias_of_canonical_ledger_is_a_leak(tmp_path) -> None:
    # A ``..``-normalizing alias of the live ledger must be caught: lexical
    # comparison would miss it, resolve(strict=False) does not.
    canonical = DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH
    alias = str(canonical.parent / "nonexistent-sub" / ".." / canonical.name)
    assert alias != str(canonical)  # lexically distinct
    reason = resource_receipt_env_leak_reason(alias, allowed_root=tmp_path.resolve())
    assert reason is not None
    assert "canonical live ledger" in reason


def test_noncanonical_dev_shm_path_outside_root_is_a_leak(tmp_path) -> None:
    # A different /dev/shm ledger is not the canonical fallback but is still a
    # production-adjacent path outside the per-test root; it must be flagged
    # (the old ``!= canonical`` predicate wrongly accepted it).
    reason = resource_receipt_env_leak_reason(
        "/dev/shm/hapax-monetization/some-other-ledger.jsonl", allowed_root=tmp_path.resolve()
    )
    assert reason is not None
    assert "outside" in reason


def test_sibling_path_outside_root_is_a_leak(tmp_path) -> None:
    sibling = tmp_path.parent / "not-my-root" / "resource-receipts.jsonl"
    reason = resource_receipt_env_leak_reason(str(sibling), allowed_root=tmp_path.resolve())
    assert reason is not None
    assert "outside" in reason


def test_dotdot_traversal_escaping_root_is_a_leak(tmp_path) -> None:
    escape = str(tmp_path / "sub" / ".." / ".." / "escape.jsonl")
    reason = resource_receipt_env_leak_reason(escape, allowed_root=tmp_path.resolve())
    assert reason is not None
    assert "outside" in reason


def test_symlink_escaping_root_is_a_leak(tmp_path) -> None:
    # A symlink inside the per-test root that points outside it must be followed:
    # resolve(strict=False) chases the link, so the value resolves outside root.
    outside = tmp_path.parent / "outside-target"
    outside.mkdir()
    link = tmp_path / "escape-link"
    os.symlink(outside, link)
    reason = resource_receipt_env_leak_reason(
        str(link / "resource-receipts.jsonl"), allowed_root=tmp_path.resolve()
    )
    assert reason is not None
    assert "outside" in reason


def test_symlink_within_root_is_not_a_leak(tmp_path) -> None:
    # A symlink inside the per-test root that points to another location inside
    # the same root stays contained and is safe.
    inside = tmp_path / "real-dir"
    inside.mkdir()
    link = tmp_path / "inside-link"
    os.symlink(inside, link)
    value = str(link / "resource-receipts.jsonl")
    assert resource_receipt_env_leak_reason(value, allowed_root=tmp_path.resolve()) is None


def test_root_swapped_for_symlink_after_setup_is_a_leak(tmp_path) -> None:
    # The immutable-baseline requirement: capture the resolved root BEFORE the
    # swap. A test that later replaces the root directory with a symlink to an
    # outside dir would make a *teardown-resolved* root escape together with the
    # value (false pass). Because the baseline is captured at setup, the value now
    # resolves outside it and is correctly flagged.
    real_root = tmp_path / "root"
    real_root.mkdir()
    allowed_root = real_root.resolve()  # immutable baseline captured pre-swap

    outside = tmp_path / "outside"
    outside.mkdir()
    real_root.rmdir()
    real_root.symlink_to(outside)  # swap the root dir for a symlink to outside

    value = str(real_root / "resource-receipts.jsonl")  # resolves through the swap
    reason = resource_receipt_env_leak_reason(value, allowed_root=allowed_root)
    assert reason is not None
    assert "outside" in reason


def test_unresolvable_value_embedded_nul_returns_reason_not_exception(tmp_path) -> None:
    # An embedded NUL makes Path.resolve raise ValueError; the predicate must
    # classify it as unsafe and return a reason rather than propagate.
    reason = resource_receipt_env_leak_reason("bad\x00path.jsonl", allowed_root=tmp_path.resolve())
    assert reason is not None
    assert "could not be" in reason


def test_injected_oserror_resolution_returns_reason(tmp_path, monkeypatch) -> None:
    # A different exception family: an OSError during resolve() (e.g. ELOOP / EIO)
    # must also be classified fail-closed, not propagated. The patch is scoped so it
    # is gone before the autouse teardown detector (which also resolves) runs.
    import pathlib

    def _boom(_self, *_a, **_k):
        raise OSError("injected resolution failure")

    with monkeypatch.context() as mp:
        mp.setattr(pathlib.Path, "resolve", _boom)
        reason = resource_receipt_env_leak_reason(str(tmp_path / "x.jsonl"), allowed_root=tmp_path)
    assert reason is not None
    assert "could not be" in reason


def test_symlink_loop_returns_actionable_reason(tmp_path) -> None:
    # A symlink loop makes resolve() raise (ELOOP) on this Linux environment; the
    # predicate must classify it fail-closed with an actionable reason — not
    # propagate and not silently pass.
    a = tmp_path / "loop-a"
    b = tmp_path / "loop-b"
    a.symlink_to(b)
    b.symlink_to(a)
    reason = resource_receipt_env_leak_reason(
        str(a / "ledger.jsonl"), allowed_root=tmp_path.resolve()
    )
    assert reason is not None
    assert "could not be" in reason


# ── Real integration proof: fixture teardown detector engages ──────────


def test_isolation_fixture_teardown_detector_engages_on_persistent_unset(tmp_path) -> None:
    # Nested pytest: a probe test persistently unsets the ledger env (no emission).
    # The real autouse fixture (re-exported into the nested conftest) must fire its
    # teardown detector, so the nested run exits nonzero with the exact reason.
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "conftest.py").write_text(
        "from tests.conftest import _isolate_resource_receipt_ledger  # noqa: F401\n",
        encoding="utf-8",
    )
    (nested / "test_leak_probe.py").write_text(
        "def test_persistent_unset(monkeypatch):\n"
        f"    monkeypatch.delenv({MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV!r}, raising=False)\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", ".", "-p", "no:cacheprovider", "-q"],
        cwd=str(nested),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "unset/empty" in output, output
    assert MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV in output, output


def test_isolation_fixture_teardown_detector_engages_on_persistent_escape(tmp_path) -> None:
    # Same, but the probe persistently redirects the env OUTSIDE its per-test root
    # (to a noncanonical /dev/shm path) without emitting; the detector must flag it.
    nested = tmp_path / "nested_escape"
    nested.mkdir()
    (nested / "conftest.py").write_text(
        "from tests.conftest import _isolate_resource_receipt_ledger  # noqa: F401\n",
        encoding="utf-8",
    )
    (nested / "test_escape_probe.py").write_text(
        "def test_persistent_escape(monkeypatch):\n"
        f"    monkeypatch.setenv({MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV!r}, "
        "'/dev/shm/hapax-monetization/escape-ledger.jsonl')\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", ".", "-p", "no:cacheprovider", "-q"],
        cwd=str(nested),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "outside" in output, output


def test_isolation_fixture_uses_immutable_setup_root_against_symlink_swap(tmp_path) -> None:
    # Through the REAL autouse fixture: the probe removes its still-empty tmp_path
    # and replaces it with a symlink to an outside dir, leaving the fixture-set env
    # STRING unchanged. Because the fixture captured the resolved root at SETUP, the
    # env value now resolves outside it and teardown MUST fail with the outside-root
    # reason. If a regression re-resolved tmp_path at teardown, both the value and
    # the root would escape together, teardown would wrongly pass, and this probe
    # (which requires a nonzero teardown) would then fail — catching the regression.
    nested = tmp_path / "nested_swap"
    nested.mkdir()
    (nested / "conftest.py").write_text(
        "from tests.conftest import _isolate_resource_receipt_ledger  # noqa: F401\n",
        encoding="utf-8",
    )
    (nested / "test_swap_probe.py").write_text(
        "import os\n"
        "\n"
        "\n"
        "def test_swap_root(tmp_path):\n"
        "    outside = tmp_path.parent / 'outside-swap-target'\n"
        "    outside.mkdir()\n"
        "    # The env string stays tmp_path/resource-receipts.jsonl; only the root\n"
        "    # directory is swapped for a symlink to the outside dir.\n"
        "    os.rmdir(tmp_path)\n"
        "    os.symlink(outside, tmp_path)\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", ".", "-p", "no:cacheprovider", "-q"],
        cwd=str(nested),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "outside" in output, output
