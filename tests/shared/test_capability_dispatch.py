"""Tests for shared.capability_dispatch — the alias resolver + utilization view."""

from __future__ import annotations

import json
from pathlib import Path

from shared.capability_dispatch import (
    CAPABILITY_ALIASES,
    DISPATCHER_PLATFORMS,
    UNROUTED_POINTERS,
    launchable_aliases,
    load_valid_route_ids,
    read_dispatch_ledger,
    record_route_id,
    resolve_capability,
    split_route_id,
    utilization,
)

# A fixed registry set so resolution tests don't depend on the live registry file.
VALID = frozenset(
    {
        "antigrav.interactive.full",
        "codex.headless.full",
        "codex.headless.spark",
        "claude.headless.full",
        "claude.headless.opus",
        "claude.headless.sonnet",
        "claude.headless.haiku",
        "claude.interactive.full",
        "api.headless.provider_gateway",
        "api.headless.api_frontier",
        "vibe.headless.full",
        "glmcp.review.direct",
        "local_tool.local.worker",
    }
)


# --- resolve_capability ----------------------------------------------------------


def test_resolve_known_alias_ok() -> None:
    res = resolve_capability("agy", valid_route_ids=VALID)
    assert res.ok
    assert res.route_id == "antigrav.interactive.full"
    assert (res.platform, res.mode, res.profile) == ("antigrav", "interactive", "full")


def test_resolve_is_case_insensitive_and_trims() -> None:
    res = resolve_capability("  AGY ", valid_route_ids=VALID)
    assert res.ok and res.route_id == "antigrav.interactive.full"


def test_resolve_raw_route_id_ok() -> None:
    res = resolve_capability("claude.headless.opus", valid_route_ids=VALID)
    assert res.ok and res.profile == "opus"


def test_resolve_unrouted_fails_closed_with_pointer() -> None:
    res = resolve_capability("fugu", valid_route_ids=VALID)
    assert not res.ok
    assert "P2" in res.reason and res.route_id is None


def test_resolve_sakana_points_at_fugu() -> None:
    res = resolve_capability("sakana", valid_route_ids=VALID)
    assert not res.ok and "fugu" in res.reason.lower()


def test_resolve_unknown_capability() -> None:
    res = resolve_capability("nope", valid_route_ids=VALID)
    assert not res.ok and "unknown capability" in res.reason


def test_resolve_non_spawnable_platform_fails_closed() -> None:
    res = resolve_capability("glmcp-review", valid_route_ids=VALID)
    assert not res.ok
    assert "not a spawnable lane" in res.reason
    assert res.platform == "glmcp"  # resolved, but not launchable here


def test_resolve_alias_to_route_absent_from_registry() -> None:
    # agy -> antigrav.interactive.full, but pretend the registry lacks that route.
    res = resolve_capability("agy", valid_route_ids=VALID - {"antigrav.interactive.full"})
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


def test_load_valid_route_ids_missing_file(tmp_path: Path) -> None:
    assert load_valid_route_ids(tmp_path / "nope.json") == frozenset()


def test_load_valid_route_ids_malformed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_valid_route_ids(bad) == frozenset()


def test_load_valid_route_ids_reflects_real_registry() -> None:
    # The shipped registry must expose required_route_ids; the aliases must be valid.
    valid = load_valid_route_ids()
    assert valid, "registry should expose required_route_ids"
    for route_id in launchable_aliases(valid).values():
        assert route_id in valid


# --- launchable_aliases ----------------------------------------------------------


def test_launchable_aliases_excludes_non_spawnable() -> None:
    out = launchable_aliases(VALID)
    assert "agy" in out and "codex" in out
    assert "glmcp-review" not in out  # platform glmcp not spawnable
    assert "local-worker" not in out
    for route_id in out.values():
        assert split_route_id(route_id)[0] in DISPATCHER_PLATFORMS  # type: ignore[index]


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
    u = utilization(records, valid_route_ids=VALID)
    assert "codex.headless.full" in u.active
    assert "antigrav.interactive.full" in u.active
    assert "vibe.headless.full" in u.latent  # launchable but unused
    assert u.counts["codex.headless.full"] == 2
    assert set(u.active).isdisjoint(set(u.latent))
    assert sorted(u.active + u.latent) == u.known


def test_utilization_launched_only_filter() -> None:
    records = [
        {"platform": "vibe", "mode": "headless", "profile": "full", "launched": False},
    ]
    u_strict = utilization(records, valid_route_ids=VALID, launched_only=True)
    assert "vibe.headless.full" in u_strict.latent
    u_all = utilization(records, valid_route_ids=VALID, launched_only=False)
    assert "vibe.headless.full" in u_all.active


def test_utilization_counts_unknown_routes_but_excludes_from_known() -> None:
    # A dispatch to a non-launchable route is tallied but not in the known scorecard.
    records = [
        {"platform": "glmcp", "mode": "review", "profile": "direct", "launched": True},
    ]
    u = utilization(records, valid_route_ids=VALID)
    assert u.counts.get("glmcp.review.direct") == 1
    assert "glmcp.review.direct" not in u.known


def test_utilization_alias_for_uses_primary_alias() -> None:
    records = [{"platform": "antigrav", "mode": "interactive", "profile": "full", "launched": True}]
    u = utilization(records, valid_route_ids=VALID)
    # agy is declared before gemini, so it is the primary display alias.
    assert u.alias_for["antigrav.interactive.full"] == "agy"
