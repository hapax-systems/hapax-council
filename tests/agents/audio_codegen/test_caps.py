"""Tests for agents.audio_codegen.caps (audit F)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.audio_codegen.caps import (
    derive_capabilities,
    main,
    render_json,
    render_markdown,
)
from shared.audio_topology import TopologyDescriptor

SYNTHETIC_YAML = """
schema_version: 3
description: synthetic-cap-fixture
nodes:
  - id: src-a
    kind: alsa_source
    pipewire_name: alsa_input.A
    description: source A
    hw: hw:CARD=A
    channels: { count: 2, positions: [FL, FR] }
  - id: chain-loud
    kind: filter_chain
    pipewire_name: chain_loud
    description: loudnorm chain
    target_object: src-a
    chain_kind: loudnorm
    limit_db: -1.0
    release_s: 0.2
    channels: { count: 2, positions: [FL, FR] }
  - id: chain-duck
    kind: filter_chain
    pipewire_name: chain_duck
    description: ducker
    target_object: chain-loud
    chain_kind: duck
    channels: { count: 2, positions: [FL, FR] }
  - id: sink-master
    kind: alsa_sink
    pipewire_name: alsa_output.M
    description: master output
    hw: hw:CARD=M
    channels: { count: 2, positions: [FL, FR] }
edges:
  - { source: src-a, target: chain-loud }
  - { source: chain-loud, target: chain-duck }
  - { source: chain-duck, target: sink-master }
"""


@pytest.fixture
def synthetic_topology(tmp_path: Path) -> Path:
    p = tmp_path / "topology.yaml"
    p.write_text(SYNTHETIC_YAML, encoding="utf-8")
    return p


# ── derive_capabilities ─────────────────────────────────────────────


class TestDeriveCapabilities:
    def test_emits_one_row_per_node(self, synthetic_topology: Path) -> None:
        descriptor = TopologyDescriptor.from_yaml(synthetic_topology)
        rows = derive_capabilities(descriptor)
        assert len(rows) == 4
        assert {r.id for r in rows} == {"src-a", "chain-loud", "chain-duck", "sink-master"}

    def test_chain_kind_carried_through(self, synthetic_topology: Path) -> None:
        descriptor = TopologyDescriptor.from_yaml(synthetic_topology)
        rows = {r.id: r for r in derive_capabilities(descriptor)}
        assert rows["chain-loud"].chain_kind == "loudnorm"
        assert rows["chain-duck"].chain_kind == "duck"
        # Non-filter-chain nodes have empty chain_kind.
        assert rows["src-a"].chain_kind == ""
        assert rows["sink-master"].chain_kind == ""

    def test_edges_in_out_counted(self, synthetic_topology: Path) -> None:
        descriptor = TopologyDescriptor.from_yaml(synthetic_topology)
        rows = {r.id: r for r in derive_capabilities(descriptor)}
        # src-a has 1 outgoing (→chain-loud), 0 incoming.
        assert rows["src-a"].edges_in == 0
        assert rows["src-a"].edges_out == 1
        # chain-loud sits in the middle: 1 in, 1 out.
        assert rows["chain-loud"].edges_in == 1
        assert rows["chain-loud"].edges_out == 1
        # sink-master has 1 incoming, 0 outgoing.
        assert rows["sink-master"].edges_in == 1
        assert rows["sink-master"].edges_out == 0

    def test_ducks_flag_set_for_duck_nodes(self, synthetic_topology: Path) -> None:
        descriptor = TopologyDescriptor.from_yaml(synthetic_topology)
        rows = {r.id: r for r in derive_capabilities(descriptor)}
        assert rows["chain-duck"].ducks is True
        assert rows["src-a"].ducks is False
        assert rows["chain-loud"].ducks is False
        assert rows["sink-master"].ducks is False


# ── render_markdown ─────────────────────────────────────────────────


class TestRenderMarkdown:
    def test_header_and_separator_present(self, synthetic_topology: Path) -> None:
        descriptor = TopologyDescriptor.from_yaml(synthetic_topology)
        text = render_markdown(derive_capabilities(descriptor))
        assert "| id | kind | chain | in | out | ducks | description |" in text
        assert "|---|---|---|---:|---:|:---:|---|" in text

    def test_each_row_present(self, synthetic_topology: Path) -> None:
        descriptor = TopologyDescriptor.from_yaml(synthetic_topology)
        text = render_markdown(derive_capabilities(descriptor))
        for node_id in ("src-a", "chain-loud", "chain-duck", "sink-master"):
            assert f"| {node_id} |" in text

    def test_pipe_in_description_escaped(self, tmp_path: Path) -> None:
        p = tmp_path / "topology.yaml"
        yaml_with_pipe = """
schema_version: 3
description: test
nodes:
  - id: piped
    kind: alsa_source
    pipewire_name: piped
    description: "has | pipe in description"
    hw: hw:CARD=P
    channels: { count: 2, positions: [FL, FR] }
edges: []
"""
        p.write_text(yaml_with_pipe, encoding="utf-8")
        descriptor = TopologyDescriptor.from_yaml(p)
        text = render_markdown(derive_capabilities(descriptor))
        # The pipe in description must be escaped so it doesn't break
        # the column structure.
        assert "has \\| pipe" in text


# ── render_json ─────────────────────────────────────────────────────


class TestRenderJson:
    def test_round_trip_through_json(self, synthetic_topology: Path) -> None:
        descriptor = TopologyDescriptor.from_yaml(synthetic_topology)
        rows = derive_capabilities(descriptor)
        text = render_json(rows)
        loaded = json.loads(text)
        assert isinstance(loaded, list)
        assert len(loaded) == 4
        ids = {r["id"] for r in loaded}
        assert ids == {"src-a", "chain-loud", "chain-duck", "sink-master"}

    def test_keys_sorted_for_stable_diff(self, synthetic_topology: Path) -> None:
        descriptor = TopologyDescriptor.from_yaml(synthetic_topology)
        rows = derive_capabilities(descriptor)
        text = render_json(rows)
        loaded = json.loads(text)
        # Each row's keys should be in sorted order in the rendered text.
        first = loaded[0]
        sorted_keys = sorted(first.keys())
        assert list(first.keys()) == sorted_keys


# ── CLI entrypoint ──────────────────────────────────────────────────


class TestCli:
    def test_main_returns_zero_on_success(
        self, synthetic_topology: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["--topology", str(synthetic_topology)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "src-a" in out
        assert "| id | kind |" in out  # markdown header

    def test_main_json_flag(
        self, synthetic_topology: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["--topology", str(synthetic_topology), "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        loaded = json.loads(out)
        assert len(loaded) == 4

    def test_missing_topology_returns_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["--topology", str(tmp_path / "does-not-exist.yaml")])
        assert rc == 2
        err = capsys.readouterr().err
        assert "not found" in err
