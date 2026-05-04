"""Decomposes every real conf in ``~/.config/pipewire/pipewire.conf.d/``.

This test PROVES the schema fits reality. **MUST be 100% pass.** If a
conf doesn't decompose, the schema is incomplete; iterate until it does.

The acceptance criterion (from the URGENT P1 brief): every active
conf must produce at least one typed model OR be explicitly classified
as "untyped wireplumber rule" (the gap G-12 catch-all surface).

For the gap G-12 catch-all path we ALSO require the validator to record
the conf in ``gaps.inferred_models`` (every conf that gets a typed
model is logged) — that means the conf was recognised, just routed to
the catch-all type rather than to a typed subclass.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.audio_graph import AudioGraphValidator

PIPEWIRE_CONF_DIR = Path("~/.config/pipewire/pipewire.conf.d").expanduser()
WIREPLUMBER_CONF_DIR = Path("~/.config/wireplumber/wireplumber.conf.d").expanduser()


@pytest.fixture(scope="module")
def validator() -> AudioGraphValidator:
    return AudioGraphValidator(PIPEWIRE_CONF_DIR, WIREPLUMBER_CONF_DIR)


def _maybe_skip_if_no_live_dir() -> None:
    if not PIPEWIRE_CONF_DIR.is_dir():
        pytest.skip(
            f"PipeWire conf dir {PIPEWIRE_CONF_DIR} not present "
            "(running outside the live workstation environment)"
        )


def test_active_conf_count_documented(validator: AudioGraphValidator) -> None:
    """Document the live count for the PR body."""
    _maybe_skip_if_no_live_dir()
    pw = validator.list_active_pipewire_confs()
    wp = validator.list_active_wireplumber_confs()
    print(f"PipeWire active: {len(pw)}")
    print(f"WirePlumber active: {len(wp)}")
    print(f"Total active: {len(pw) + len(wp)}")
    assert len(pw) >= 20
    assert len(wp) >= 14


def test_every_active_pipewire_conf_decomposes(
    validator: AudioGraphValidator,
) -> None:
    """ACCEPTANCE GATE — every active PipeWire conf must decompose."""
    _maybe_skip_if_no_live_dir()
    failures: list[str] = []
    for conf in validator.list_active_pipewire_confs():
        if not validator.conf_decomposed_cleanly(conf):
            failures.append(conf.name)
    assert failures == [], (
        f"{len(failures)} active PipeWire confs did not decompose:\n"
        + "\n".join(f"  - {n}" for n in failures)
    )


def test_every_active_wireplumber_conf_decomposes(
    validator: AudioGraphValidator,
) -> None:
    """ACCEPTANCE GATE — every active WirePlumber conf must decompose."""
    _maybe_skip_if_no_live_dir()
    failures: list[str] = []
    for conf in validator.list_active_wireplumber_confs():
        if not validator.conf_decomposed_cleanly(conf):
            failures.append(conf.name)
    assert failures == [], (
        f"{len(failures)} active WirePlumber confs did not decompose:\n"
        + "\n".join(f"  - {n}" for n in failures)
    )


def test_full_decompose_yields_a_well_formed_graph(
    validator: AudioGraphValidator,
) -> None:
    _maybe_skip_if_no_live_dir()
    result = validator.decompose_confs()
    # Schema validation already enforced at AudioGraph construction
    # — if we got here, the assembled graph parsed.
    assert result.graph.schema_version == 4
    # Sanity: at least one node, at least one loopback, at least one
    # tunable, at least one media-role-sink.
    assert len(result.graph.nodes) >= 10, (
        f"expected ≥10 nodes from real confs, got {len(result.graph.nodes)}"
    )
    assert len(result.graph.loopbacks) >= 1
    assert len(result.graph.tunables) >= 1
    assert len(result.graph.media_role_sinks) >= 1


def test_specific_critical_nodes_present(validator: AudioGraphValidator) -> None:
    """The broadcast-master / livestream-tap / private chain must appear.

    These are the load-bearing nodes — if the validator misses any of
    them, the gap is critical and the schema needs another iteration.
    """
    _maybe_skip_if_no_live_dir()
    result = validator.decompose_confs()
    node_ids = {n.id for n in result.graph.nodes}
    # Validator uses pipewire_name as the node.id (kebab-cased),
    # which gives the ``hapax-`` prefix.
    expected_ids = {
        "hapax-livestream-tap",
        "hapax-broadcast-master",
        "hapax-broadcast-normalized",
        "hapax-obs-broadcast-remap",
        "hapax-private",
        "hapax-notification-private",
    }
    missing = expected_ids - node_ids
    assert not missing, (
        f"critical nodes missing from decomposition: {sorted(missing)}\nGot {sorted(node_ids)}"
    )


def test_role_loopback_infrastructure_decomposes() -> None:
    """50-hapax-voice-duck.conf — the load-bearing wireplumber conf.

    Verifies gap G-13 fold actually surfaces the role-based loopback
    infrastructure when the live conf is read.
    """
    _maybe_skip_if_no_live_dir()
    target = WIREPLUMBER_CONF_DIR / "50-hapax-voice-duck.conf"
    if not target.is_file():
        pytest.skip(f"{target} not present")
    v = AudioGraphValidator(
        Path("/tmp/empty-pw-dir-does-not-exist"),
        WIREPLUMBER_CONF_DIR,
    )
    result = v.decompose_confs()
    # Should produce exactly one MediaRoleSink (everything is in one conf).
    assert len(result.graph.media_role_sinks) == 1
    sink = result.graph.media_role_sinks[0]
    assert sink.duck_policy.duck_level == 0.3
    role_names = {lb.role for lb in sink.loopbacks}
    # Live conf has 4 roles: Multimedia, Notification, Assistant, Broadcast.
    # The validator picks the first intended role per loopback; in the
    # live conf those map to Music (multimedia), Notification, Assistant,
    # Broadcast.
    assert len(sink.loopbacks) >= 4
    assert any("notif" in r.lower() for r in role_names)
