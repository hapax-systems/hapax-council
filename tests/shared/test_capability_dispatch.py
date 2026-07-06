"""Tests for shared.capability_dispatch — the alias resolver + utilization view."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from shared.capability_dispatch import (
    CAPABILITY_ALIASES,
    LAUNCHABLE_PATHS,
    UNROUTED_POINTERS,
    launchable_aliases,
    ledger_health,
    load_active_route_ids,
    load_valid_route_ids,
    read_dispatch_ledger,
    record_route_id,
    registry_error,
    resolve_capability,
    split_route_id,
    utilization,
)

# A fixed registry set so resolution tests don't depend on the live registry file.
VALID = frozenset(
    {
        "codex.headless.full",
        "codex.headless.spark",
        "claude.headless.full",
        "claude.headless.opus",
        "claude.headless.sonnet",
        "claude.headless.haiku",
        "claude.interactive.full",
        "api.headless.provider_gateway",
        "api.headless.api_frontier",
        "api.headless.openrouter",
        "codex.headless.ornith",
        "vibe.headless.full",
        "glmcp.review.direct",
        "local_tool.local.worker",
    }
)
ACTIVE = VALID - {"codex.headless.ornith"}


# --- resolve_capability ----------------------------------------------------------


def test_resolve_known_alias_ok() -> None:
    res = resolve_capability("codex", valid_route_ids=VALID)
    assert res.ok
    assert res.route_id == "codex.headless.full"
    assert (res.platform, res.mode, res.profile) == ("codex", "headless", "full")


def test_resolve_is_case_insensitive_and_trims() -> None:
    res = resolve_capability("  CODEX ", valid_route_ids=VALID)
    assert res.ok and res.route_id == "codex.headless.full"


def test_resolve_raw_route_id_ok() -> None:
    res = resolve_capability("claude.headless.opus", valid_route_ids=VALID)
    assert res.ok and res.profile == "opus"


def test_resolve_ornith_route_uses_codex_harness_profile() -> None:
    for alias in ("ornith", "ornith-35b", "ornith-35b-local", "ornith-local"):
        res = resolve_capability(alias, valid_route_ids=VALID)
        assert res.ok, alias
        assert res.route_id == "codex.headless.ornith"
        assert (res.platform, res.mode, res.profile) == ("codex", "headless", "ornith")


def test_resolve_unrouted_fails_closed_with_pointer() -> None:
    res = resolve_capability("fugu", valid_route_ids=VALID)
    assert not res.ok
    assert "P2" in res.reason and res.route_id is None


def test_resolve_sakana_points_at_fugu() -> None:
    res = resolve_capability("sakana", valid_route_ids=VALID)
    assert not res.ok and "fugu" in res.reason.lower()


def test_resolve_deprecated_antigrav_alias_fails_closed() -> None:
    res = resolve_capability("agy", valid_route_ids=VALID)
    assert not res.ok
    assert "deprecated" in res.reason.lower()
    assert res.route_id is None

    full_word = resolve_capability("antigravity", valid_route_ids=VALID)
    assert not full_word.ok
    assert "deprecated" in full_word.reason.lower()
    assert "measured agy supply leaves" in full_word.reason
    assert full_word.route_id is None

    gemini_cli = resolve_capability("gemini-cli", valid_route_ids=VALID)
    assert not gemini_cli.ok
    assert "retired" in gemini_cli.reason.lower()
    assert "measured agy supply leaves" in gemini_cli.reason
    assert gemini_cli.route_id is None


def test_resolve_unknown_capability() -> None:
    res = resolve_capability("nope", valid_route_ids=VALID)
    assert not res.ok and "unknown capability" in res.reason


def test_resolve_non_spawnable_platform_fails_closed() -> None:
    res = resolve_capability("glmcp-review", valid_route_ids=VALID)
    assert not res.ok
    assert "not a spawnable lane" in res.reason
    assert res.platform == "glmcp"  # resolved, but not launchable here


def test_resolve_alias_to_route_absent_from_registry() -> None:
    # codex-spark maps to a real route, but pretend the registry lacks that route.
    res = resolve_capability("codex-spark", valid_route_ids=VALID - {"codex.headless.spark"})
    assert not res.ok and "not in the registry" in res.reason


# --- split_route_id --------------------------------------------------------------


def test_split_route_id_valid() -> None:
    assert split_route_id("api.headless.provider_gateway") == (
        "api",
        "headless",
        "provider_gateway",
    )


def test_split_route_id_malformed() -> None:
    assert split_route_id("two.parts") is None
    assert split_route_id("a..c") is None  # empty middle


# --- load_valid_route_ids --------------------------------------------------------


def test_load_valid_route_ids(tmp_path: Path) -> None:
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"required_route_ids": ["a.b.c", "d.e.f"]}), encoding="utf-8")
    assert load_valid_route_ids(reg) == frozenset({"a.b.c", "d.e.f"})


def test_load_active_route_ids_excludes_blocked_routes(tmp_path: Path) -> None:
    reg = tmp_path / "reg.json"
    reg.write_text(
        json.dumps(
            {
                "required_route_ids": ["a.b.c", "d.e.f", "x.y.z"],
                "routes": [
                    {"route_id": "a.b.c", "route_state": "active", "blocked_reasons": []},
                    {
                        "route_id": "d.e.f",
                        "route_state": "blocked",
                        "blocked_reasons": ["receipt_absent"],
                    },
                    {"route_id": "not.required", "route_state": "active", "blocked_reasons": []},
                    {"route_id": "x.y.z", "route_state": "active", "blocked_reasons": ["stale"]},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_active_route_ids(reg) == frozenset({"a.b.c"})


@pytest.mark.parametrize(
    "route_payload",
    [
        {"route_id": "a.b.c", "route_state": "active"},
        {"route_id": "a.b.c", "route_state": "active", "blocked_reasons": None},
        {"route_id": "a.b.c", "route_state": "active", "blocked_reasons": ""},
        {"route_id": "a.b.c", "route_state": "active", "blocked_reasons": {}},
        {"route_id": "a.b.c", "route_state": "available", "blocked_reasons": []},
    ],
)
def test_load_active_route_ids_excludes_malformed_route_state(
    tmp_path: Path, route_payload: dict[str, object]
) -> None:
    reg = tmp_path / "reg.json"
    reg.write_text(
        json.dumps(
            {
                "required_route_ids": ["a.b.c"],
                "routes": [route_payload],
            }
        ),
        encoding="utf-8",
    )

    assert load_active_route_ids(reg) == frozenset()


def test_load_valid_route_ids_missing_file(tmp_path: Path) -> None:
    assert load_valid_route_ids(tmp_path / "nope.json") == frozenset()


def test_load_valid_route_ids_malformed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_valid_route_ids(bad) == frozenset()


def test_registry_error_readable_returns_none() -> None:
    assert registry_error() is None  # the shipped registry reads + has routes


def test_registry_error_missing_file(tmp_path: Path) -> None:
    assert "unreadable" in (registry_error(tmp_path / "nope.json") or "")


def test_registry_error_malformed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert "malformed" in (registry_error(bad) or "")


def test_registry_error_missing_key(tmp_path: Path) -> None:
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"other": []}), encoding="utf-8")
    assert "required_route_ids" in (registry_error(reg) or "")


def test_registry_error_empty_list(tmp_path: Path) -> None:
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"required_route_ids": []}), encoding="utf-8")
    assert "empty" in (registry_error(reg) or "")


def test_ledger_health_missing(tmp_path: Path) -> None:
    assert ledger_health(tmp_path / "nope.jsonl") == (False, 0)


def test_ledger_health_counts_corrupt(tmp_path: Path) -> None:
    led = tmp_path / "methodology-dispatch.jsonl"
    led.write_text(
        json.dumps({"platform": "codex", "mode": "headless", "profile": "full"})
        + "\n"
        + "{ corrupt\n"
        + "\n"
        + "also not json\n",
        encoding="utf-8",
    )
    exists, corrupt = ledger_health(led)
    assert exists is True and corrupt == 2


def test_load_valid_route_ids_reflects_real_registry() -> None:
    # The shipped registry must expose required_route_ids; aliases must be valid; and
    # launchability must match the dispatcher's spawnable (platform, mode) lanes — the
    # receipt-only api/local routes must never appear as launch capacity (makes the
    # "latent capability" claim recheckable, not a hand-picked number).
    valid = load_valid_route_ids()
    active = load_active_route_ids()
    assert valid, "registry should expose required_route_ids"
    assert "codex.headless.ornith" not in active
    launchable = launchable_aliases(active)
    for route_id in launchable.values():
        assert route_id in valid
        platform, mode, _ = split_route_id(route_id)  # type: ignore[misc]
        assert (platform, mode) in LAUNCHABLE_PATHS
    assert "ornith" not in launchable
    assert "api" not in launchable and "api-frontier" not in launchable
    assert "openrouter" not in launchable and "openrouter-frontier" not in launchable
    assert "local-worker" not in launchable and "glmcp-review" not in launchable
    assert not any(rid.startswith("api.") for rid in launchable.values())


# --- launchable_aliases ----------------------------------------------------------


def test_launchable_aliases_excludes_non_spawnable() -> None:
    out = launchable_aliases(ACTIVE)
    assert "codex" in out and "vibe" in out
    assert "ornith" not in out
    assert "codex.headless.ornith" not in out.values()
    assert "agy" not in out
    assert "glmcp-review" not in out  # platform glmcp not spawnable
    assert "local-worker" not in out  # receipt-only local-inference, no lane
    assert "api" not in out and "api-frontier" not in out  # receipt-only api routes
    assert "openrouter" not in out and "openrouter-frontier" not in out
    for route_id in out.values():
        platform, mode, _ = split_route_id(route_id)  # type: ignore[misc]
        assert (platform, mode) in LAUNCHABLE_PATHS


def test_resolve_api_route_is_receipt_only_not_launchable() -> None:
    # api routes are valid + admittable but receipt-only (no spawnable lane) — they
    # must fail closed, not appear as launch capacity (codex major finding).
    res = resolve_capability("api", valid_route_ids=VALID)
    assert not res.ok
    assert "not a spawnable lane" in res.reason
    assert res.route_id == "api.headless.provider_gateway"


def test_resolve_openrouter_route_is_receipt_only_not_launchable() -> None:
    res = resolve_capability("openrouter", valid_route_ids=VALID)
    assert not res.ok
    assert "not a spawnable lane" in res.reason
    assert res.route_id == "api.headless.openrouter"

    frontier = resolve_capability("openrouter-frontier", valid_route_ids=VALID)
    assert not frontier.ok
    assert "not a spawnable lane" in frontier.reason
    assert frontier.route_id == "api.headless.openrouter"

    raw = resolve_capability("api.headless.openrouter", valid_route_ids=VALID)
    assert not raw.ok
    assert "not a spawnable lane" in raw.reason
    assert raw.route_id == "api.headless.openrouter"

    typo = resolve_capability("open-router", valid_route_ids=VALID)
    assert not typo.ok
    assert "unknown capability" in typo.reason
    assert typo.route_id is None


# --- the launchable set vs the LIVE dispatcher (contract, not a mock) ------------

_DISPATCHER = Path(__file__).resolve().parents[2] / "scripts" / "hapax-methodology-dispatch"


def test_launchable_paths_match_live_dispatcher() -> None:
    # Guards the "tests mock away the dispatcher contract" finding: run the REAL
    # dispatcher's --list-platform-paths and assert LAUNCHABLE_PATHS are exactly the
    # spawnable lanes while api/local are receipt-only — so the set cannot drift.
    try:
        proc = subprocess.run(
            [sys.executable, str(_DISPATCHER), "--list-platform-paths"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - env guard
        pytest.skip(f"dispatcher not runnable: {exc}")
    if proc.returncode != 0:  # pragma: no cover - env guard
        pytest.skip(f"dispatcher --list-platform-paths failed: {proc.stderr[-300:]}")
    lines = proc.stdout.splitlines()
    for platform, mode in LAUNCHABLE_PATHS:
        prefix = f"{platform}/{mode}/"
        matched = [ln for ln in lines if ln.startswith(prefix)]
        assert matched, f"{prefix} missing from --list-platform-paths"
        assert any("receipt-only" not in ln and "no spawnable lane" not in ln for ln in matched), (
            f"{prefix} is receipt-only in the dispatcher but LAUNCHABLE_PATHS claims it spawns"
        )
    api_lines = [ln for ln in lines if ln.startswith("api/")]
    assert api_lines and all("receipt-only" in ln for ln in api_lines)
    # Set EQUALITY — catches drift BOTH ways (incl. a NEW spawnable lane LAUNCHABLE_PATHS forgot).
    spawnable: set[tuple[str, str]] = set()
    for ln in lines:
        m = re.match(r"^([a-z_]+)/([a-z_]+)/\S+:", ln)
        if m and "receipt-only" not in ln and "no spawnable lane" not in ln:
            spawnable.add((m.group(1), m.group(2)))
    assert spawnable == set(LAUNCHABLE_PATHS), (
        f"LAUNCHABLE_PATHS drift: dispatcher spawnable={sorted(spawnable)} "
        f"vs LAUNCHABLE_PATHS={sorted(LAUNCHABLE_PATHS)}"
    )


def test_every_alias_targets_a_well_formed_route_id() -> None:
    for route_id in CAPABILITY_ALIASES.values():
        assert split_route_id(route_id) is not None


def test_unrouted_pointers_are_not_aliases() -> None:
    assert set(UNROUTED_POINTERS).isdisjoint(set(CAPABILITY_ALIASES))


# --- the dispatch ledger reader --------------------------------------------------


def test_read_dispatch_ledger_skips_corrupt(tmp_path: Path) -> None:
    led = tmp_path / "methodology-dispatch.jsonl"
    led.write_text(
        json.dumps({"platform": "codex", "mode": "headless", "profile": "full", "launched": True})
        + "\n"
        + "{ corrupt\n"
        + "\n"
        + json.dumps({"platform": "claude", "mode": "headless", "profile": "full"})
        + "\n",
        encoding="utf-8",
    )
    rows = list(read_dispatch_ledger(led))
    assert len(rows) == 2 and rows[0]["platform"] == "codex"


def test_read_dispatch_ledger_missing(tmp_path: Path) -> None:
    assert list(read_dispatch_ledger(tmp_path / "nope.jsonl")) == []


def test_record_route_id() -> None:
    assert (
        record_route_id({"platform": "codex", "mode": "headless", "profile": "full"})
        == "codex.headless.full"
    )
    assert record_route_id({"platform": "codex", "mode": "headless"}) is None


# --- utilization -----------------------------------------------------------------


def test_utilization_active_vs_latent() -> None:
    records = [
        {"platform": "codex", "mode": "headless", "profile": "full", "launched": True},
        {"platform": "codex", "mode": "headless", "profile": "full", "launched": True},
        {"platform": "antigrav", "mode": "interactive", "profile": "full", "launched": True},
    ]
    u = utilization(records, valid_route_ids=ACTIVE)
    assert "codex.headless.full" in u.active
    assert "antigrav.interactive.full" not in u.known
    assert "antigrav.interactive.full" not in u.active
    assert "vibe.headless.full" in u.latent  # launchable but unused
    assert u.counts["codex.headless.full"] == 2
    assert u.counts["antigrav.interactive.full"] == 1
    assert set(u.active).isdisjoint(set(u.latent))
    assert sorted(u.active + u.latent) == u.known


def test_utilization_launched_only_filter() -> None:
    records = [
        {"platform": "vibe", "mode": "headless", "profile": "full", "launched": False},
    ]
    u_strict = utilization(records, valid_route_ids=ACTIVE, launched_only=True)
    assert "vibe.headless.full" in u_strict.latent
    u_all = utilization(records, valid_route_ids=ACTIVE, launched_only=False)
    assert "vibe.headless.full" in u_all.active


def test_utilization_counts_unknown_routes_but_excludes_from_known() -> None:
    # A dispatch to a non-launchable route is tallied but not in the known scorecard.
    records = [
        {"platform": "glmcp", "mode": "review", "profile": "direct", "launched": True},
    ]
    u = utilization(records, valid_route_ids=ACTIVE)
    assert u.counts.get("glmcp.review.direct") == 1
    assert "glmcp.review.direct" not in u.known


def test_utilization_alias_for_uses_primary_alias() -> None:
    records = [{"platform": "codex", "mode": "headless", "profile": "full", "launched": True}]
    u = utilization(records, valid_route_ids=ACTIVE)
    assert u.alias_for["codex.headless.full"] == "codex"
