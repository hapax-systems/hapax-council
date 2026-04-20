"""End-to-end tests for the hapax-audio-topology CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

CLI_PATH = Path(__file__).resolve().parents[2] / "scripts" / "hapax-audio-topology"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
    )


def _write_yaml(tmp: Path, body: str) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / "topo.yaml"
    path.write_text(dedent(body).strip() + "\n")
    return path


@pytest.fixture
def basic_yaml(tmp_path: Path) -> Path:
    return _write_yaml(
        tmp_path,
        """
        schema_version: 1
        description: cli smoketest
        nodes:
          - id: l6-capture
            kind: alsa_source
            pipewire_name: alsa_input.usb-ZOOM_L6-00
            hw: hw:L6,0
          - id: livestream-tap
            kind: tap
            pipewire_name: hapax-livestream-tap
        edges:
          - source: l6-capture
            target: livestream-tap
        """,
    )


class TestDescribe:
    def test_prints_node_and_edge_counts(self, basic_yaml: Path) -> None:
        result = _run(["describe", str(basic_yaml)])
        assert result.returncode == 0
        assert "nodes (2)" in result.stdout
        assert "edges (1)" in result.stdout
        assert "l6-capture" in result.stdout
        assert "livestream-tap" in result.stdout

    def test_missing_file_exits_1(self, tmp_path: Path) -> None:
        result = _run(["describe", str(tmp_path / "does-not-exist.yaml")])
        assert result.returncode == 1
        assert "not found" in result.stderr


class TestGenerate:
    def test_generate_stdout(self, basic_yaml: Path) -> None:
        result = _run(["generate", str(basic_yaml)])
        assert result.returncode == 0
        assert "pipewire/l6-capture.conf" in result.stdout
        assert "pipewire/livestream-tap.conf" in result.stdout
        assert "factory.name = api.alsa.pcm.source" in result.stdout
        assert "support.null-audio-sink" in result.stdout

    def test_generate_output_dir(self, basic_yaml: Path, tmp_path: Path) -> None:
        outdir = tmp_path / "out"
        result = _run(["generate", str(basic_yaml), "--output-dir", str(outdir)])
        assert result.returncode == 0
        assert (outdir / "pipewire" / "l6-capture.conf").exists()
        assert (outdir / "pipewire" / "livestream-tap.conf").exists()
        # Content matches template.
        conf = (outdir / "pipewire" / "l6-capture.conf").read_text()
        assert "api.alsa.pcm.source" in conf
        assert 'api.alsa.path = "hw:L6,0"' in conf


class TestDiff:
    def test_match_exits_0(self, basic_yaml: Path, tmp_path: Path) -> None:
        dup = tmp_path / "dup.yaml"
        dup.write_text(basic_yaml.read_text())
        result = _run(["diff", str(basic_yaml), str(dup)])
        assert result.returncode == 0
        assert "match" in result.stdout

    def test_added_node_exits_2(self, basic_yaml: Path, tmp_path: Path) -> None:
        augmented = _write_yaml(
            tmp_path / "aug",
            """
            schema_version: 1
            description: added voice-fx
            nodes:
              - id: l6-capture
                kind: alsa_source
                pipewire_name: alsa_input.usb-ZOOM_L6-00
                hw: hw:L6,0
              - id: livestream-tap
                kind: tap
                pipewire_name: hapax-livestream-tap
              - id: voice-fx
                kind: filter_chain
                pipewire_name: hapax-voice-fx-capture
                target_object: alsa_output.pci-0000_73_00.6.analog-stereo
            edges:
              - source: l6-capture
                target: livestream-tap
            """,
        )
        result = _run(["diff", str(basic_yaml), str(augmented)])
        assert result.returncode == 2
        assert "added nodes" in result.stdout
        assert "voice-fx" in result.stdout

    def test_changed_gain_shift(self, basic_yaml: Path, tmp_path: Path) -> None:
        # Build two descriptors that differ only by edge gain.
        a = _write_yaml(
            tmp_path / "a",
            """
            schema_version: 1
            nodes:
              - id: src
                kind: alsa_source
                pipewire_name: in
                hw: hw:0,0
              - id: sink
                kind: tap
                pipewire_name: tap
            edges:
              - source: src
                target: sink
                makeup_gain_db: 6.0
            """,
        )
        b = _write_yaml(
            tmp_path / "b",
            """
            schema_version: 1
            nodes:
              - id: src
                kind: alsa_source
                pipewire_name: in
                hw: hw:0,0
              - id: sink
                kind: tap
                pipewire_name: tap
            edges:
              - source: src
                target: sink
                makeup_gain_db: 12.0
            """,
        )
        result = _run(["diff", str(a), str(b)])
        assert result.returncode == 2
        assert "changed edges" in result.stdout
        assert "+6.0 dB → +12.0 dB" in result.stdout

    def test_removed_node(self, basic_yaml: Path, tmp_path: Path) -> None:
        stripped = _write_yaml(
            tmp_path / "stripped",
            """
            schema_version: 1
            nodes:
              - id: l6-capture
                kind: alsa_source
                pipewire_name: alsa_input.usb-ZOOM_L6-00
                hw: hw:L6,0
            """,
        )
        result = _run(["diff", str(basic_yaml), str(stripped)])
        assert result.returncode == 2
        assert "removed nodes" in result.stdout
        assert "livestream-tap" in result.stdout


class TestVerify:
    def test_match_live_exits_0(self, tmp_path: Path) -> None:
        """Descriptor matches live pw-dump → exit 0."""
        import json

        descriptor = _write_yaml(
            tmp_path / "d",
            """
            schema_version: 1
            nodes:
              - id: hapax-tap
                kind: tap
                pipewire_name: hapax-tap
            """,
        )
        dump = tmp_path / "dump.json"
        dump.write_text(
            json.dumps(
                [
                    {
                        "id": 100,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "hapax-tap",
                                "media.class": "Audio/Sink",
                                "factory.name": "support.null-audio-sink",
                            }
                        },
                    }
                ]
            )
        )
        result = _run(["verify", str(descriptor), "--dump-file", str(dump)])
        assert result.returncode == 0
        assert "matches" in result.stdout

    def test_extra_live_node_exits_2(self, tmp_path: Path) -> None:
        """Live graph has a node the descriptor doesn't know about."""
        import json

        descriptor = _write_yaml(
            tmp_path / "d",
            """
            schema_version: 1
            nodes:
              - id: hapax-tap
                kind: tap
                pipewire_name: hapax-tap
            """,
        )
        dump = tmp_path / "dump.json"
        dump.write_text(
            json.dumps(
                [
                    {
                        "id": 100,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "hapax-tap",
                                "media.class": "Audio/Sink",
                                "factory.name": "support.null-audio-sink",
                            }
                        },
                    },
                    {
                        "id": 101,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "hapax-extra",
                                "media.class": "Audio/Sink",
                                "factory.name": "support.null-audio-sink",
                            }
                        },
                    },
                ]
            )
        )
        result = _run(["verify", str(descriptor), "--dump-file", str(dump)])
        assert result.returncode == 2
        assert "live extras" in result.stdout
        assert "hapax-extra" in result.stdout


class TestAudit:
    def test_audit_prints_counts(self, tmp_path: Path) -> None:
        """Audit always exits 0 and prints declared vs live totals."""
        import json

        descriptor = _write_yaml(
            tmp_path / "d",
            """
            schema_version: 1
            nodes:
              - id: hapax-tap
                kind: tap
                pipewire_name: hapax-tap
            """,
        )
        dump = tmp_path / "dump.json"
        dump.write_text(json.dumps([]))
        result = _run(["audit", str(descriptor), "--dump-file", str(dump)])
        # Audit exit is always 0.
        assert result.returncode == 0
        assert "declared nodes: 1" in result.stdout
        assert "live nodes:     0" in result.stdout


class TestWatchdog:
    def test_dry_run_prints_commands(self) -> None:
        """Dry-run must emit both pactl commands and not exec."""
        result = _run(["watchdog", "--dry-run"])
        assert result.returncode == 0
        assert "pactl set-card-profile alsa_card.pci-0000_73_00.6 off" in result.stdout
        assert (
            "pactl set-card-profile alsa_card.pci-0000_73_00.6 output:analog-stereo"
            in result.stdout
        )

    def test_dry_run_custom_card(self) -> None:
        result = _run(
            [
                "watchdog",
                "--card",
                "alsa_card.custom",
                "--profile",
                "output:hdmi-stereo",
                "--dry-run",
            ]
        )
        assert result.returncode == 0
        assert "alsa_card.custom" in result.stdout
        assert "output:hdmi-stereo" in result.stdout


class TestInvalidDescriptor:
    def test_dangling_edge_exits_1(self, tmp_path: Path) -> None:
        bad = _write_yaml(
            tmp_path,
            """
            schema_version: 1
            nodes:
              - id: a
                kind: tap
                pipewire_name: a
            edges:
              - source: nonexistent
                target: a
            """,
        )
        result = _run(["describe", str(bad)])
        assert result.returncode == 1
        assert "source not in" in result.stderr
