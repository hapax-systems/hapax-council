"""Regression test for the hapax-* PipeWire node naming convention.

Audit finding E#12 (2026-05-02): the workspace had drifted into having a
single PipeWire conf file named ``pc-loudnorm.conf`` while every other
operator-authored conf carries the ``hapax-*`` prefix. The conf was
renamed to ``hapax-pc-loudnorm.conf`` in the same PR.

This test pins the convention so future audio work cannot silently
re-introduce non-prefixed nodes or deployable conf filenames. The rules:

    Every operator-authored PipeWire node in the canonical topology
    descriptor must declare a ``pipewire_name`` starting with ``hapax-``.

    Every top-level, hand-authored PipeWire conf under
    ``config/pipewire/*.conf`` must be named ``hapax-*.conf``. Generated
    compiler outputs under ``config/pipewire/generated/`` are governed
    by the audio-routing compiler's node-id filename convention and are
    intentionally not checked here.

Two well-defined exception classes:

1.  **Operator hardware** — ALSA endpoints (``alsa_input.*`` /
    ``alsa_output.*``) and the wireplumber role-bucket loopbacks
    (``input.loopback.sink.role.*`` / ``output.loopback.sink.role.*``)
    are named by PipeWire/wireplumber and not under our authorship.

2.  **Synth/instrument model nodes** — the S-4 analog port descriptor
    node ``s4-analog-out-1-2`` is a model-only abstraction over the
    operator's hardware (Torso S-4) and does not correspond to a
    Hapax-authored PipeWire module.

Any other node MUST start with ``hapax-`` or this test fails. Adding a
new exception requires editing this file plus a justification in the PR.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.audio_industrial_naming import industrial_audio_name_violations
from shared.audio_topology import TopologyDescriptor

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_YAML = REPO_ROOT / "config" / "audio-topology.yaml"
PIPEWIRE_DIR = REPO_ROOT / "config" / "pipewire"

# Pipewire-authored prefixes (operator hardware / wireplumber primitives).
OPERATOR_HARDWARE_PREFIXES: tuple[str, ...] = (
    "alsa_input",
    "alsa_output",
    "input.loopback.sink.role.",
    "output.loopback.sink.role.",
)

# Model-only node ids that do not correspond to a Hapax-authored
# PipeWire module (S-4 analog port descriptor lives here).
MODEL_ONLY_NODE_IDS: frozenset[str] = frozenset({"s4-analog-out-1-2"})


def test_canonical_topology_yaml_exists() -> None:
    assert CANONICAL_YAML.exists(), f"missing canonical descriptor: {CANONICAL_YAML}"


def test_all_hapax_authored_pw_nodes_match_prefix() -> None:
    """Every node that is not operator-hardware nor model-only must be hapax-*."""
    descriptor = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    violations: list[str] = []
    for node in descriptor.nodes:
        if node.id in MODEL_ONLY_NODE_IDS:
            continue
        if any(node.pipewire_name.startswith(p) for p in OPERATOR_HARDWARE_PREFIXES):
            continue
        if not node.pipewire_name.startswith("hapax-"):
            violations.append(
                f"{node.id}: pipewire_name {node.pipewire_name!r} violates hapax-* convention"
            )
    assert not violations, "\n".join(violations)


def test_canonical_topology_nodes_have_unique_industrial_names() -> None:
    """Every canonical node has a stable, non-ad-hoc industrial graph name."""

    descriptor = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    violations: list[str] = []
    seen: dict[str, str] = {}
    for node in descriptor.nodes:
        name = node.industrial_name
        reasons = industrial_audio_name_violations(name)
        if reasons:
            violations.append(f"{node.id}: {name or '<missing>'} ({', '.join(reasons)})")
            continue
        assert name is not None
        if name in seen:
            violations.append(f"{node.id}: {name} duplicates {seen[name]}")
            continue
        seen[name] = node.id

    assert not violations, "\n".join(violations)


def test_legacy_ad_hoc_pipewire_nodes_have_industrial_names() -> None:
    """Pin ad-hoc live names to operator-readable SSOT graph names."""

    descriptor = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    assert descriptor.node_by_id("music-duck").industrial_name == "chain.music.ducker"
    assert (
        descriptor.node_by_id("l12-evilpet-capture").industrial_name
        == "chain.broadcast.processor-return-capture"
    )


def test_pc_loudnorm_uses_hapax_prefix() -> None:
    """Pin: pc-loudnorm node carries the hapax- prefix (audit E#12 closure)."""
    descriptor = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    node = descriptor.node_by_id("pc-loudnorm")
    assert node.pipewire_name == "hapax-pc-loudnorm"


def test_pc_loudnorm_conf_uses_hapax_prefix_filename() -> None:
    """Pin: the conf file name matches the hapax-* convention (E#12 closure)."""
    correct = REPO_ROOT / "config" / "pipewire" / "hapax-pc-loudnorm.conf"
    legacy = REPO_ROOT / "config" / "pipewire" / "pc-loudnorm.conf"
    assert correct.exists(), f"expected renamed conf at {correct}"
    assert not legacy.exists(), f"legacy conf {legacy} must be removed"


def test_top_level_pipewire_conf_filenames_use_hapax_prefix() -> None:
    """Top-level deployable PipeWire confs must all be hapax-*."""

    violations = [
        path.name
        for path in sorted(PIPEWIRE_DIR.glob("*.conf"))
        if path.is_file() and not path.name.startswith("hapax-")
    ]
    assert not violations, "non-hapax deployable PipeWire conf names: " + ", ".join(violations)


@pytest.mark.parametrize(
    "exception_id",
    sorted(MODEL_ONLY_NODE_IDS),
)
def test_model_only_exceptions_remain_in_descriptor(exception_id: str) -> None:
    """Model-only ids MUST stay in the descriptor — exceptions are codified."""
    descriptor = TopologyDescriptor.from_yaml(CANONICAL_YAML)
    descriptor.node_by_id(exception_id)  # raises KeyError if removed
