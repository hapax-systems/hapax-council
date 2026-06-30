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


def test_runtime_stable_receipt_id_includes_scope() -> None:
    first = MINT._stable_receipt_id(
        "runtime_actuation",
        "codex.headless.full",
        task_ids=["task-a"],
        mutation_surfaces=["runtime"],
    )
    second = MINT._stable_receipt_id(
        "runtime_actuation",
        "codex.headless.full",
        task_ids=["task-b"],
        mutation_surfaces=["runtime"],
    )

    assert first.startswith("runtime_actuation-codex-headless-full-")
    assert first != second


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


def test_default_mode_mints_runtime_actuation_receipt(capsys, tmp_path: Path) -> None:
    rc, payload = _run_json(
        capsys,
        [
            "--receipt-type",
            "runtime_actuation",
            "--route-id",
            "codex.headless.full",
            "--task-id",
            "appendix-podium-minio-old-root-cleanup-20260605",
            "--receipt-dir",
            str(tmp_path),
            "--now",
            "2026-06-05T11:30:00Z",
            "--json",
        ],
    )

    assert rc == 0
    target = Path(payload["receipt_path"])
    assert target.is_file()
    receipt = RouteAuthorityReceipt.model_validate(json.loads(target.read_text(encoding="utf-8")))
    assert receipt.receipt_type == "runtime_actuation"
    assert receipt.route_id == "codex.headless.full"
    assert receipt.task_ids == ("appendix-podium-minio-old-root-cleanup-20260605",)
    assert receipt.mutation_surfaces == ("runtime",)


def test_default_mode_mints_connector_mutation_receipt(capsys, tmp_path: Path) -> None:
    rc, payload = _run_json(
        capsys,
        [
            "--receipt-type",
            "connector_mutation",
            "--route-id",
            "codex.headless.full",
            "--task-id",
            "cc-task-mcp-mutator-route-resource-receipts-20260630",
            "--receipt-dir",
            str(tmp_path),
            "--now",
            "2026-06-30T04:30:00Z",
            "--json",
        ],
    )

    assert rc == 0
    target = Path(payload["receipt_path"])
    assert target.is_file()
    receipt = RouteAuthorityReceipt.model_validate(json.loads(target.read_text(encoding="utf-8")))
    assert receipt.receipt_type == "connector_mutation"
    assert receipt.route_id == "codex.headless.full"
    assert receipt.task_ids == ("cc-task-mcp-mutator-route-resource-receipts-20260630",)
    assert receipt.mutation_surfaces == ("connector",)


def test_ensure_fresh_runtime_actuation_keeps_scope_specific_files(capsys, tmp_path: Path) -> None:
    base = [
        "--receipt-type",
        "runtime_actuation",
        "--route-id",
        "codex.headless.full",
        "--receipt-dir",
        str(tmp_path),
        "--ensure-fresh",
        "--now",
        "2026-06-05T11:30:00Z",
        "--json",
    ]
    rc_first, first = _run_json(
        capsys,
        [*base, "--task-id", "appendix-podium-minio-old-root-cleanup-20260605"],
    )
    rc_second, second = _run_json(capsys, [*base, "--task-id", "some-other-runtime-task"])

    assert rc_first == 0
    assert rc_second == 0
    assert first["kept"] is False
    assert second["kept"] is False
    assert first["receipt_path"] != second["receipt_path"]
    files = sorted((tmp_path / "route-authority").glob("*.json"))
    assert len(files) == 2


def test_invalid_refresh_within_is_refused(capsys, tmp_path: Path) -> None:
    rc = MINT.main(
        _ensure_args(tmp_path, now="2026-06-01T00:00:00Z", extra=["--refresh-within", "banana"])
    )

    assert rc == 2
    assert "refresh-within" in capsys.readouterr().err
    assert not (tmp_path / "route-authority").exists()


# ── Re-mint failure escalation (reform-opus-receipt-remint-repoint-20260601) ──
# The timer-backed re-mint failure is SILENTLY suppressed by the global
# notify-failure coalescer ("Timer-backed ... failed (suppressed — timer
# retries)"), so a receipt that stops refreshing lapses with no operator-visible
# alert and opus dispatch loses route authority. The minter therefore
# self-escalates an ntfy when, in --ensure-fresh upkeep, a re-mint FAILS and
# either (a) N consecutive failures have accrued or (b) the live receipt is
# within --alert-within of expiry.


def _boom(*_args, **_kwargs):
    raise OSError("simulated write failure")


def _record_ntfy(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def _fake(title: str, message: str, **kwargs) -> bool:
        calls.append({"title": title, "message": message, **kwargs})
        return True

    monkeypatch.setattr(MINT, "_post_ntfy", _fake, raising=False)
    return calls


def test_remint_failure_within_expiry_window_fires_ntfy(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    # Seed a receipt issued at 00:00 (24h window -> expires 24:00).
    _run_json(capsys, _ensure_args(tmp_path, now="2026-06-01T00:00:00Z"))
    calls = _record_ntfy(monkeypatch)
    monkeypatch.setattr(MINT, "write_route_authority_receipt", _boom)

    # 23:30: remaining 0.5h (< 8h refresh window -> re-mint attempted; < 2h
    # alert window -> a failed re-mint must alert even on the first failure).
    rc = MINT.main(_ensure_args(tmp_path, now="2026-06-01T23:30:00Z"))

    assert rc == 2
    assert calls, "a re-mint failure within T-2h of expiry must fire an ntfy"
    assert calls[0].get("priority") in {"high", "urgent"}


def test_remint_failure_alerts_only_after_n_consecutive(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    _run_json(capsys, _ensure_args(tmp_path, now="2026-06-01T00:00:00Z"))
    calls = _record_ntfy(monkeypatch)
    monkeypatch.setattr(MINT, "write_route_authority_receipt", _boom)

    # 20:00: remaining 4h -> re-mint attempted, but outside the 2h alert window,
    # so only the consecutive-failure threshold (default N=3) can trip the alert.
    args = _ensure_args(tmp_path, now="2026-06-01T20:00:00Z")
    assert MINT.main(args) == 2
    assert MINT.main(args) == 2
    assert not calls, "must not alert before N consecutive re-mint failures"
    assert MINT.main(args) == 2
    assert calls, "must alert on the Nth consecutive re-mint failure"


def test_successful_remint_resets_failure_counter(capsys, monkeypatch, tmp_path: Path) -> None:
    _run_json(capsys, _ensure_args(tmp_path, now="2026-06-01T00:00:00Z"))
    real_write = MINT.write_route_authority_receipt
    monkeypatch.setattr(MINT, "write_route_authority_receipt", _boom)
    args = _ensure_args(tmp_path, now="2026-06-01T20:00:00Z")
    assert MINT.main(args) == 2
    assert MINT.main(args) == 2

    # A successful re-mint clears the streak and does not alert.
    monkeypatch.setattr(MINT, "write_route_authority_receipt", real_write)
    calls = _record_ntfy(monkeypatch)
    rc = MINT.main(args)

    assert rc == 0
    assert not calls
    state = json.loads(MINT._upkeep_state_path(tmp_path, STABLE_ID).read_text(encoding="utf-8"))
    assert state["consecutive_failures"] == 0


def test_upkeep_sidecar_never_pollutes_scanned_receipt_dir(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    # The dispatch read-path globs <dir>/route-authority/*.json and RAISES on any
    # file that is not a valid receipt, so the upkeep state must live elsewhere.
    _run_json(capsys, _ensure_args(tmp_path, now="2026-06-01T00:00:00Z"))
    _record_ntfy(monkeypatch)
    monkeypatch.setattr(MINT, "write_route_authority_receipt", _boom)

    MINT.main(_ensure_args(tmp_path, now="2026-06-01T23:30:00Z"))

    scanned = sorted((tmp_path / "route-authority").glob("*.json"))
    assert [p.name for p in scanned] == [f"{STABLE_ID}.json"]
    sidecar = MINT._upkeep_state_path(tmp_path, STABLE_ID)
    assert sidecar.is_file()
    assert sidecar.parent.name != "route-authority"


def test_post_ntfy_is_best_effort_on_network_error(monkeypatch) -> None:
    def _explode(*_args, **_kwargs):
        raise OSError("ntfy unreachable")

    monkeypatch.setattr(MINT, "urlopen", _explode, raising=False)
    # Never raises into the caller — upkeep alerting must not crash the minter.
    assert MINT._post_ntfy("title", "body", priority="high") is False


SERVICE_UNIT = REPO_ROOT / "systemd" / "units" / "hapax-opus-route-authority-receipt.service"


def test_service_unit_runs_from_active_deploy_worktree_not_primary() -> None:
    unit = SERVICE_UNIT.read_text(encoding="utf-8")
    exec_lines = [line for line in unit.splitlines() if line.startswith("ExecStart=")]
    assert exec_lines, "service unit must define an ExecStart"
    exec_line = exec_lines[0]
    # Antipattern: running the minter from the primary worktree, which parks on
    # feature branches where this minter does not exist (status=2 -> lapse).
    assert "/projects/hapax-council/" not in exec_line, (
        "ExecStart must not run the minter from the primary worktree"
    )
    assert "/.cache/hapax/source-activation/worktree/" in exec_line, (
        "ExecStart must resolve the minter from the stable active deploy symlink"
    )
    assert "--ensure-fresh" in exec_line
    # The minter self-escalates an ntfy on failure, so a topic must be configured.
    assert "NTFY_TOPIC=" in unit
