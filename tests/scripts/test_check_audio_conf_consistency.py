"""Tests for scripts/check-audio-conf-consistency.py (audit F gate)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check-audio-conf-consistency.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_audio_conf_consistency", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def gate_module():
    return _load_module()


def _write_topology(path: Path, chains: list[dict]) -> None:
    """Write a minimal audio-topology.yaml with the given chains."""
    yaml_lines = ["schema_version: 3", "description: synthetic", "nodes:"]
    for chain in chains:
        yaml_lines.append(f"  - id: {chain['id']}")
        yaml_lines.append(f"    kind: {chain.get('kind', 'filter_chain')}")
        yaml_lines.append(f"    pipewire_name: {chain['id']}")
        if chain.get("chain_kind") is not None:
            yaml_lines.append(f"    chain_kind: {chain['chain_kind']}")
        yaml_lines.append("    channels: { count: 2, positions: [FL, FR] }")
        if chain.get("kind") in {"alsa_source", "alsa_sink"}:
            yaml_lines.append("    hw: hw:CARD=X")
    yaml_lines.append("edges: []")
    path.write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")


# ── expected_confs_from_yaml ────────────────────────────────────────


class TestExpectedConfsFromYaml:
    def test_only_typed_chain_kind_chains_count(self, gate_module, tmp_path: Path) -> None:
        topology = tmp_path / "topology.yaml"
        _write_topology(
            topology,
            [
                {"id": "music-loudnorm", "chain_kind": "loudnorm"},
                {"id": "music-duck", "chain_kind": "duck"},
                {"id": "private-monitor-capture"},  # chain_kind=None → no conf expected
            ],
        )
        expected = gate_module.expected_confs_from_yaml(topology)
        assert expected == {"hapax-music-loudnorm.conf", "hapax-music-duck.conf"}

    def test_non_filter_chain_nodes_skipped(self, gate_module, tmp_path: Path) -> None:
        topology = tmp_path / "topology.yaml"
        _write_topology(
            topology,
            [
                {"id": "src-a", "kind": "alsa_source"},
                {"id": "music-loudnorm", "chain_kind": "loudnorm"},
            ],
        )
        expected = gate_module.expected_confs_from_yaml(topology)
        assert expected == {"hapax-music-loudnorm.conf"}


# ── confs_on_disk ───────────────────────────────────────────────────


class TestConfsOnDisk:
    def test_lists_only_dot_conf(self, gate_module, tmp_path: Path) -> None:
        (tmp_path / "a.conf").write_text("")
        (tmp_path / "b.conf").write_text("")
        (tmp_path / "ignore.txt").write_text("")
        result = gate_module.confs_on_disk(tmp_path)
        assert result == {"a.conf", "b.conf"}

    def test_missing_dir_returns_empty(self, gate_module, tmp_path: Path) -> None:
        result = gate_module.confs_on_disk(tmp_path / "nope")
        assert result == set()


# ── load_allowlist ──────────────────────────────────────────────────


class TestLoadAllowlist:
    def test_missing_file_returns_empty_pair(self, gate_module, tmp_path: Path) -> None:
        orphans, known_missing = gate_module.load_allowlist(tmp_path / "nope.yaml")
        assert orphans == set()
        assert known_missing == set()

    def test_loads_both_sections(self, gate_module, tmp_path: Path) -> None:
        path = tmp_path / "allow.yaml"
        path.write_text(
            "orphans:\n  - foo.conf\n  - bar.conf\nknown_missing:\n  - hapax-x.conf\n",
            encoding="utf-8",
        )
        orphans, known_missing = gate_module.load_allowlist(path)
        assert orphans == {"foo.conf", "bar.conf"}
        assert known_missing == {"hapax-x.conf"}


# ── check (the full gate) ───────────────────────────────────────────


class TestCheck:
    def test_clean_when_yaml_and_disk_match(self, gate_module, tmp_path: Path) -> None:
        topology = tmp_path / "topology.yaml"
        pipewire = tmp_path / "pipewire"
        pipewire.mkdir()
        allowlist = tmp_path / "allow.yaml"

        _write_topology(topology, [{"id": "music-loudnorm", "chain_kind": "loudnorm"}])
        (pipewire / "hapax-music-loudnorm.conf").write_text("")
        allowlist.write_text("orphans: []\nknown_missing: []\n", encoding="utf-8")

        code, msg = gate_module.check(topology=topology, pipewire_dir=pipewire, allowlist=allowlist)
        assert code == 0
        assert "OK" in msg

    def test_missing_conf_fires(self, gate_module, tmp_path: Path) -> None:
        """AC: insert a fake yaml chain without a conf, assert the
        check fails with a useful error."""
        topology = tmp_path / "topology.yaml"
        pipewire = tmp_path / "pipewire"
        pipewire.mkdir()
        _write_topology(
            topology,
            [
                {"id": "fake-chain", "chain_kind": "loudnorm"},
            ],
        )

        code, msg = gate_module.check(
            topology=topology,
            pipewire_dir=pipewire,
            allowlist=tmp_path / "no-allowlist.yaml",
        )
        assert code == 1
        assert "Missing confs" in msg
        assert "hapax-fake-chain.conf" in msg
        assert "fake-chain" in msg
        assert "Fix:" in msg

    def test_orphan_conf_fires_when_not_allowlisted(self, gate_module, tmp_path: Path) -> None:
        topology = tmp_path / "topology.yaml"
        pipewire = tmp_path / "pipewire"
        pipewire.mkdir()
        _write_topology(topology, [])
        (pipewire / "stray.conf").write_text("")

        code, msg = gate_module.check(
            topology=topology,
            pipewire_dir=pipewire,
            allowlist=tmp_path / "no-allowlist.yaml",
        )
        assert code == 1
        assert "Orphan confs" in msg
        assert "stray.conf" in msg

    def test_orphan_conf_passes_when_allowlisted(self, gate_module, tmp_path: Path) -> None:
        topology = tmp_path / "topology.yaml"
        pipewire = tmp_path / "pipewire"
        pipewire.mkdir()
        allowlist = tmp_path / "allow.yaml"

        _write_topology(topology, [])
        (pipewire / "legacy.conf").write_text("")
        allowlist.write_text("orphans:\n  - legacy.conf\nknown_missing: []\n", encoding="utf-8")

        code, msg = gate_module.check(topology=topology, pipewire_dir=pipewire, allowlist=allowlist)
        assert code == 0
        assert "1 known orphans" in msg

    def test_known_missing_passes(self, gate_module, tmp_path: Path) -> None:
        topology = tmp_path / "topology.yaml"
        pipewire = tmp_path / "pipewire"
        pipewire.mkdir()
        allowlist = tmp_path / "allow.yaml"

        _write_topology(topology, [{"id": "ytube-ducked", "chain_kind": "duck"}])
        # No conf on disk for ytube-ducked, but it's in known_missing.
        allowlist.write_text(
            "orphans: []\nknown_missing:\n  - hapax-ytube-ducked.conf\n",
            encoding="utf-8",
        )

        code, msg = gate_module.check(topology=topology, pipewire_dir=pipewire, allowlist=allowlist)
        assert code == 0
        assert "known_missing: 1" in msg


# ── live state regression pin ───────────────────────────────────────


class TestLiveStatePassesAfterAllowlist:
    """The shipped state of the repo must pass the gate. This pin
    catches a future commit that introduces drift without updating
    the allowlist."""

    def test_real_repo_passes(self, gate_module) -> None:
        code, msg = gate_module.check()
        assert code == 0, f"audio yaml↔conf consistency gate failed against live state: {msg}"


# ── CLI ─────────────────────────────────────────────────────────────


class TestCli:
    def test_main_returns_zero_on_clean(
        self, gate_module, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        topology = tmp_path / "topology.yaml"
        pipewire = tmp_path / "pipewire"
        pipewire.mkdir()
        _write_topology(topology, [])
        rc = gate_module.main(
            [
                "--topology",
                str(topology),
                "--pipewire-dir",
                str(pipewire),
                "--allowlist",
                str(tmp_path / "no-allowlist.yaml"),
            ]
        )
        assert rc == 0

    def test_main_returns_one_on_drift(
        self, gate_module, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        topology = tmp_path / "topology.yaml"
        pipewire = tmp_path / "pipewire"
        pipewire.mkdir()
        _write_topology(topology, [{"id": "missing-chain", "chain_kind": "loudnorm"}])
        rc = gate_module.main(
            [
                "--topology",
                str(topology),
                "--pipewire-dir",
                str(pipewire),
                "--allowlist",
                str(tmp_path / "no-allowlist.yaml"),
            ]
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert "drift detected" in err
