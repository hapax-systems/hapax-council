"""Tests for ``scripts/hapax-mint-route-authority-receipt --ensure-fresh`` upkeep.

The mint tool is the executable form of OQ-5 (the operator signs the opus
model-entitlement that un-degrades the frontier route). ``--ensure-fresh`` is
the timer-driven upkeep path introduced for
``reform-improve-opus-receipt-default-20260601`` (CASE-CAPACITY-ROUTING-001): it
converges on a single stable-id receipt in the dir the dispatch read-path scans
and only re-mints as the receipt approaches staleness, so a sibling timer keeps
opus reachable by default — retiring the rollback-on-stale-worktree hack.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from shared.dispatcher_policy import RouteAuthorityReceipt

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-mint-route-authority-receipt"
STABLE_ID = "opus_model_entitlement-claude-headless-opus"


def _mint_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_mint_route_authority_receipt", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


MINT = _mint_module()


def _ensure_args(receipt_dir: Path, *, now: str, extra: list[str] | None = None) -> list[str]:
    return [
        "--receipt-type",
        "opus_model_entitlement",
        "--route-id",
        "claude.headless.opus",
        "--receipt-dir",
        str(receipt_dir),
        "--ensure-fresh",
        "--now",
        now,
        "--json",
        *(extra or []),
    ]


def _run_json(capsys, args: list[str]) -> tuple[int, dict]:
    rc = MINT.main(args)
    out = capsys.readouterr().out
    return rc, json.loads(out)


def _receipt_path(receipt_dir: Path) -> Path:
    return receipt_dir / "route-authority" / f"{STABLE_ID}.json"


def test_stable_receipt_id_is_timestamp_free() -> None:
    assert MINT._stable_receipt_id("opus_model_entitlement", "claude.headless.opus") == STABLE_ID


def test_ensure_fresh_initial_mint_writes_stable_id(capsys, tmp_path: Path) -> None:
    rc, payload = _run_json(capsys, _ensure_args(tmp_path, now="2026-06-01T00:00:00Z"))

    assert rc == 0
    assert payload["kept"] is False
    assert payload["receipt_id"] == STABLE_ID
    target = _receipt_path(tmp_path)
    assert target.is_file()
    receipt = RouteAuthorityReceipt.model_validate(json.loads(target.read_text(encoding="utf-8")))
    assert receipt.receipt_type == "opus_model_entitlement"
    assert receipt.route_id == "claude.headless.opus"


def test_ensure_fresh_keeps_fresh_receipt_untouched(capsys, tmp_path: Path) -> None:
    _run_json(capsys, _ensure_args(tmp_path, now="2026-06-01T00:00:00Z"))
    before = _receipt_path(tmp_path).read_text(encoding="utf-8")

    # +1h: 23h of a 24h window remain, well above the 8h refresh threshold.
    rc, payload = _run_json(capsys, _ensure_args(tmp_path, now="2026-06-01T01:00:00Z"))

    assert rc == 0
    assert payload["kept"] is True
    assert _receipt_path(tmp_path).read_text(encoding="utf-8") == before


def test_ensure_fresh_remints_near_staleness(capsys, tmp_path: Path) -> None:
    _run_json(capsys, _ensure_args(tmp_path, now="2026-06-01T00:00:00Z"))
    before = _receipt_path(tmp_path).read_text(encoding="utf-8")

    # +20h: only 4h remain (< 8h refresh window) -> re-mint with a later issued_at.
    rc, payload = _run_json(capsys, _ensure_args(tmp_path, now="2026-06-01T20:00:00Z"))

    assert rc == 0
    assert payload["kept"] is False
    after = _receipt_path(tmp_path).read_text(encoding="utf-8")
    assert after != before
    reminted = RouteAuthorityReceipt.model_validate(json.loads(after))
    assert reminted.issued_at.isoformat().startswith("2026-06-01T20:00:00")


def test_ensure_fresh_converges_on_single_file(capsys, tmp_path: Path) -> None:
    for now in ("2026-06-01T00:00:00Z", "2026-06-01T20:00:00Z", "2026-06-02T17:00:00Z"):
        _run_json(capsys, _ensure_args(tmp_path, now=now))

    files = sorted((tmp_path / "route-authority").glob("*.json"))
    assert [p.name for p in files] == [f"{STABLE_ID}.json"]


def test_ensure_fresh_remints_when_stale_after_changes(capsys, tmp_path: Path) -> None:
    _run_json(
        capsys, _ensure_args(tmp_path, now="2026-06-01T00:00:00Z", extra=["--stale-after", "24h"])
    )

    # Same instant + plenty of freshness, but a different policy window must
    # still re-sign so the live stale_after tracks the requested one.
    rc, payload = _run_json(
        capsys,
        _ensure_args(tmp_path, now="2026-06-01T01:00:00Z", extra=["--stale-after", "48h"]),
    )

    assert rc == 0
    assert payload["kept"] is False
    assert payload["stale_after"] == "48h"


def test_default_mode_keeps_timestamped_ids(capsys, tmp_path: Path) -> None:
    base = [
        "--receipt-type",
        "opus_model_entitlement",
        "--route-id",
        "claude.headless.opus",
        "--receipt-dir",
        str(tmp_path),
        "--json",
    ]
    MINT.main([*base, "--now", "2026-06-01T00:00:00Z"])
    capsys.readouterr()
    MINT.main([*base, "--now", "2026-06-01T00:00:01Z"])
    capsys.readouterr()

    # Without --ensure-fresh the default id is timestamped: two runs accumulate
    # two files. This is the behaviour --ensure-fresh exists to avoid.
    files = list((tmp_path / "route-authority").glob("*.json"))
    assert len(files) == 2


def test_invalid_refresh_within_is_refused(capsys, tmp_path: Path) -> None:
    rc = MINT.main(
        _ensure_args(tmp_path, now="2026-06-01T00:00:00Z", extra=["--refresh-within", "banana"])
    )

    assert rc == 2
    assert "refresh-within" in capsys.readouterr().err
    assert not (tmp_path / "route-authority").exists()
