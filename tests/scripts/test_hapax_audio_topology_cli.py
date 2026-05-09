"""End-to-end tests for the hapax-audio-topology CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import numpy as np
import pytest

from shared.audio_topology import Node, TopologyDescriptor

CLI_PATH = Path(__file__).resolve().parents[2] / "scripts" / "hapax-audio-topology"
CANONICAL_YAML = Path(__file__).resolve().parents[2] / "config" / "audio-topology.yaml"


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


def _replace_node(
    descriptor: TopologyDescriptor,
    node_id: str,
    **updates: object,
) -> TopologyDescriptor:
    nodes: list[Node] = []
    for node in descriptor.nodes:
        nodes.append(node.model_copy(update=updates) if node.id == node_id else node)
    return descriptor.model_copy(update={"nodes": nodes})


def _write_l12_scene_pcm(
    path: Path,
    *,
    content_l_amp: int = 20000,
    content_r_amp: int = 20000,
    voice_l_amp: int = 20000,
    voice_r_amp: int = 20000,
) -> Path:
    buffer = np.zeros((4800, 14), dtype=np.int16)
    buffer[:, 8] = content_l_amp
    buffer[:, 9] = content_r_amp
    buffer[:, 10] = voice_l_amp
    buffer[:, 11] = voice_r_amp
    path.write_bytes(buffer.tobytes())
    return path


@pytest.fixture
def basic_yaml(tmp_path: Path) -> Path:
    return _write_yaml(
        tmp_path,
        """
        schema_version: 2
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
            schema_version: 2
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
            schema_version: 2
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
            schema_version: 2
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
            schema_version: 2
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
            schema_version: 2
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
            schema_version: 2
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

    def test_edge_compare_uses_pipewire_names_not_descriptor_ids(self, tmp_path: Path) -> None:
        """Hand-authored descriptor IDs differ from live-derived IDs.

        Verify must compare edges by PipeWire node.name or every stable
        descriptor ID becomes false drift against pw-dump-derived IDs.
        """
        import json

        descriptor = _write_yaml(
            tmp_path / "d",
            """
            schema_version: 2
            nodes:
              - id: l12-capture
                kind: alsa_source
                pipewire_name: alsa_input.usb-ZOOM_Corporation_L-12-00.multichannel-input
                hw: hw:L12,0
              - id: l12-evilpet-capture
                kind: filter_chain
                pipewire_name: hapax-l12-evilpet-capture
            edges:
              - source: l12-capture
                target: l12-evilpet-capture
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
                                "node.name": (
                                    "alsa_input.usb-ZOOM_Corporation_L-12-00.multichannel-input"
                                ),
                                "media.class": "Audio/Source",
                                "factory.name": "api.alsa.pcm.source",
                                "api.alsa.path": "hw:L12,0",
                            }
                        },
                    },
                    {
                        "id": 101,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "hapax-l12-evilpet-capture",
                                "media.class": "Audio/Sink",
                                "factory.name": "filter-chain",
                            }
                        },
                    },
                    {
                        "id": 200,
                        "type": "PipeWire:Interface:Link",
                        "info": {"output-node-id": 100, "input-node-id": 101},
                    },
                ]
            )
        )

        result = _run(["verify", str(descriptor), "--dump-file", str(dump)])

        assert result.returncode == 0
        assert "no unclassified drift" in result.stdout

    def test_external_hardware_extra_is_classified_not_drift(self, tmp_path: Path) -> None:
        import json

        descriptor = _write_yaml(
            tmp_path / "d",
            """
            schema_version: 2
            nodes: []
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
                                "node.name": "alsa_output.pci-0000_01_00.1.hdmi-stereo",
                                "media.class": "Audio/Sink",
                                "factory.name": "api.alsa.pcm.sink",
                                "api.alsa.path": "hdmi:2",
                            }
                        },
                    }
                ]
            )
        )

        result = _run(["verify", str(descriptor), "--dump-file", str(dump)])

        assert result.returncode == 0
        assert "classified external/runtime" in result.stdout
        assert "external-hardware-endpoint" in result.stdout

    def test_m8_missing_source_runtime_fallback_is_classified(self, tmp_path: Path) -> None:
        import json

        descriptor = _write_yaml(
            tmp_path / "d",
            """
            schema_version: 2
            nodes:
              - id: l12-capture
                kind: alsa_source
                pipewire_name: alsa_input.usb-ZOOM_Corporation_L-12-00.multichannel-input
                hw: hw:L12,0
              - id: m8-usb-source
                kind: alsa_source
                pipewire_name: alsa_input.usb-Dirtywave_M8_16558390-02.analog-stereo
                hw: hw:M8,0
                params:
                  audit_classification: external-hardware-optional
              - id: m8-instrument-capture
                kind: filter_chain
                pipewire_name: hapax-m8-instrument-capture
                target_object: alsa_input.usb-Dirtywave_M8_16558390-02.analog-stereo
            edges:
              - source: m8-usb-source
                target: m8-instrument-capture
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
                                "node.name": (
                                    "alsa_input.usb-ZOOM_Corporation_L-12-00.multichannel-input"
                                ),
                                "media.class": "Audio/Source",
                                "factory.name": "api.alsa.pcm.source",
                                "api.alsa.path": "hw:L12,0",
                            }
                        },
                    },
                    {
                        "id": 101,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "hapax-m8-instrument-capture",
                                "media.class": "Stream/Input/Audio",
                                "target.object": (
                                    "alsa_input.usb-Dirtywave_M8_16558390-02.analog-stereo"
                                ),
                            }
                        },
                    },
                    {
                        "id": 200,
                        "type": "PipeWire:Interface:Link",
                        "info": {"output-node-id": 100, "input-node-id": 101},
                    },
                ]
            )
        )

        result = _run(["verify", str(descriptor), "--dump-file", str(dump)])

        assert result.returncode == 0
        assert "runtime-fallback-m8-source-absent" in result.stdout
        assert "depends-on-external-hardware-optional" in result.stdout

    def test_m8_l12_extra_edge_is_drift_when_m8_source_is_live(self, tmp_path: Path) -> None:
        import json

        descriptor = _write_yaml(
            tmp_path / "d",
            """
            schema_version: 2
            nodes:
              - id: l12-capture
                kind: alsa_source
                pipewire_name: alsa_input.usb-ZOOM_Corporation_L-12-00.multichannel-input
                hw: hw:L12,0
              - id: m8-usb-source
                kind: alsa_source
                pipewire_name: alsa_input.usb-Dirtywave_M8_16558390-02.analog-stereo
                hw: hw:M8,0
                params:
                  audit_classification: external-hardware-optional
              - id: m8-instrument-capture
                kind: filter_chain
                pipewire_name: hapax-m8-instrument-capture
                target_object: alsa_input.usb-Dirtywave_M8_16558390-02.analog-stereo
            edges:
              - source: m8-usb-source
                target: m8-instrument-capture
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
                                "node.name": (
                                    "alsa_input.usb-ZOOM_Corporation_L-12-00.multichannel-input"
                                ),
                                "media.class": "Audio/Source",
                                "factory.name": "api.alsa.pcm.source",
                                "api.alsa.path": "hw:L12,0",
                            }
                        },
                    },
                    {
                        "id": 101,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "alsa_input.usb-Dirtywave_M8_16558390-02.analog-stereo",
                                "media.class": "Audio/Source",
                                "factory.name": "api.alsa.pcm.source",
                                "api.alsa.path": "hw:M8,0",
                            }
                        },
                    },
                    {
                        "id": 102,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "hapax-m8-instrument-capture",
                                "media.class": "Stream/Input/Audio",
                                "target.object": (
                                    "alsa_input.usb-Dirtywave_M8_16558390-02.analog-stereo"
                                ),
                            }
                        },
                    },
                    {
                        "id": 200,
                        "type": "PipeWire:Interface:Link",
                        "info": {"output-node-id": 101, "input-node-id": 102},
                    },
                    {
                        "id": 201,
                        "type": "PipeWire:Interface:Link",
                        "info": {"output-node-id": 100, "input-node-id": 102},
                    },
                ]
            )
        )

        result = _run(["verify", str(descriptor), "--dump-file", str(dump)])

        assert result.returncode == 2
        assert "+ edges only in right:" in result.stdout
        assert "runtime-fallback-m8-source-absent" not in result.stdout

    def test_private_monitor_runtime_playback_edge_is_classified(self, tmp_path: Path) -> None:
        import json

        descriptor = _write_yaml(
            tmp_path / "d",
            """
            schema_version: 2
            nodes:
              - id: yeti-headphone-output
                kind: alsa_sink
                pipewire_name: alsa_output.usb-Blue_Microphones_Yeti-00.analog-stereo
                hw: front:Yeti
                params:
                  private_monitor_endpoint: true
              - id: private-monitor-output
                kind: loopback
                pipewire_name: hapax-private-playback
                target_object: alsa_output.usb-Blue_Microphones_Yeti-00.analog-stereo
                params:
                  private_monitor_bridge: true
            edges: []
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
                                "node.name": "hapax-private-playback",
                                "media.class": "Stream/Output/Audio",
                                "target.object": "alsa_output.usb-Blue_Microphones_Yeti-00.analog-stereo",
                            }
                        },
                    },
                    {
                        "id": 101,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "alsa_output.usb-Blue_Microphones_Yeti-00.analog-stereo",
                                "media.class": "Audio/Sink",
                                "factory.name": "api.alsa.pcm.sink",
                                "api.alsa.path": "front:Yeti",
                            }
                        },
                    },
                    {
                        "id": 200,
                        "type": "PipeWire:Interface:Link",
                        "info": {"output-node-id": 100, "input-node-id": 101},
                    },
                ]
            )
        )

        result = _run(["verify", str(descriptor), "--dump-file", str(dump)])

        assert result.returncode == 0
        assert "private-monitor-runtime-output-binding" in result.stdout


class TestAudit:
    def test_audit_prints_counts(self, tmp_path: Path) -> None:
        """Audit always exits 0 and prints declared vs live totals."""
        import json

        descriptor = _write_yaml(
            tmp_path / "d",
            """
            schema_version: 2
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


class TestTtsBroadcastCheck:
    def test_tts_broadcast_check_ok_for_current_mpc_wet_return_path(
        self,
        tmp_path: Path,
    ) -> None:
        import json

        dump = tmp_path / "dump.json"
        dump.write_text(
            json.dumps(
                [
                    {
                        "id": 100,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "input.loopback.sink.role.broadcast",
                                "media.class": "Audio/Sink",
                                "factory.name": "loopback",
                            }
                        },
                    },
                    {
                        "id": 101,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "hapax-voice-fx-capture",
                                "media.class": "Audio/Sink",
                                "factory.name": "filter-chain",
                            }
                        },
                    },
                    {
                        "id": 102,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "hapax-loudnorm-capture",
                                "media.class": "Audio/Sink",
                                "factory.name": "filter-chain",
                            }
                        },
                    },
                    {
                        "id": 103,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": (
                                    "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00"
                                    ".multichannel-output"
                                ),
                                "media.class": "Audio/Sink",
                                "factory.name": "api.alsa.pcm.sink",
                                "api.alsa.path": "hw:7",
                                "audio.channels": 24,
                            }
                        },
                    },
                    {
                        "id": 104,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "hapax-l12-usb-return-capture",
                                "media.class": "Audio/Sink",
                                "factory.name": "filter-chain",
                            }
                        },
                    },
                    {
                        "id": 105,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "hapax-livestream-tap",
                                "media.class": "Audio/Sink",
                                "factory.name": "support.null-audio-sink",
                            }
                        },
                    },
                    {
                        "id": 106,
                        "type": "PipeWire:Interface:Node",
                        "info": {
                            "props": {
                                "node.name": "hapax-broadcast-master-capture",
                                "media.class": "Audio/Sink",
                                "factory.name": "filter-chain",
                            }
                        },
                    },
                    {
                        "id": 200,
                        "type": "PipeWire:Interface:Link",
                        "info": {"output-node-id": 105, "input-node-id": 106},
                    },
                ]
            )
        )
        result = _run(["tts-broadcast-check", "--dump-file", str(dump)])
        assert result.returncode == 0
        assert "TTS broadcast path: OK" in result.stdout

    def test_tts_broadcast_check_fails_when_mpc_wet_return_missing(
        self,
        tmp_path: Path,
    ) -> None:
        import json

        dump = tmp_path / "dump.json"
        dump.write_text(json.dumps([]))
        result = _run(["tts-broadcast-check", "--dump-file", str(dump)])
        assert result.returncode == 2
        assert "TTS broadcast path: FAIL" in result.stdout
        assert "hapax-l12-usb-return-capture" in result.stdout


class TestL12ForwardCheck:
    def test_l12_forward_check_accepts_canonical_descriptor(self) -> None:
        result = _run(["l12-forward-check", str(CANONICAL_YAML)])

        assert result.returncode == 0, result.stdout + result.stderr
        assert "L-12 forward invariant: OK" in result.stdout

    def test_l12_forward_check_fails_private_to_broadcast_path(self, tmp_path: Path) -> None:
        descriptor = TopologyDescriptor.from_yaml(CANONICAL_YAML)
        descriptor = _replace_node(
            descriptor,
            "role-assistant",
            target_object="hapax-voice-fx-capture",
        )
        broken = tmp_path / "broken-audio-topology.yaml"
        broken.write_text(descriptor.to_yaml(), encoding="utf-8")

        result = _run(["l12-forward-check", str(broken)])

        assert result.returncode == 2
        assert "L-12 forward invariant: FAIL" in result.stdout
        assert "private_route_reaches_broadcast_path" in result.stdout


class TestL12SceneCheck:
    def test_l12_scene_check_accepts_canonical_descriptor_and_hot_pcm(
        self,
        tmp_path: Path,
    ) -> None:
        raw = _write_l12_scene_pcm(tmp_path / "l12-hot.s16le")

        result = _run(
            [
                "l12-scene-check",
                str(CANONICAL_YAML),
                "--raw-pcm-file",
                str(raw),
            ]
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "L-12 broadcast scene: OK" in result.stdout
        assert "expected_scene: BROADCAST-V2" in result.stdout

    def test_l12_scene_check_returns_2_when_content_return_is_cold(
        self,
        tmp_path: Path,
    ) -> None:
        raw = _write_l12_scene_pcm(
            tmp_path / "l12-cold.s16le",
            content_l_amp=0,
            content_r_amp=0,
        )

        result = _run(
            [
                "l12-scene-check",
                str(CANONICAL_YAML),
                "--raw-pcm-file",
                str(raw),
            ]
        )

        assert result.returncode == 2
        assert "L-12 broadcast scene: FAIL" in result.stdout
        assert "AUX8 content return L peak" in result.stdout


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


class TestPinCheck:
    """Pin-check subcommand wires the pin-glitch detector into the CLI."""

    def test_healthy_sink_exits_zero(self, tmp_path: Path) -> None:
        """RUNNING + active input + audible signal → no diagnostic, exit 0."""
        state = tmp_path / "state.json"
        result = _run(
            [
                "pin-check",
                "--state",
                "RUNNING",
                "--has-active-input",
                "--rms-db",
                "-12.0",
                "--state-file",
                str(state),
            ]
        )
        assert result.returncode == 0, result.stderr
        assert "diagnostic=OK" in result.stdout

    def test_idle_sink_exits_zero(self, tmp_path: Path) -> None:
        """IDLE sink → no diagnostic regardless of RMS."""
        state = tmp_path / "state.json"
        result = _run(
            [
                "pin-check",
                "--state",
                "IDLE",
                "--no-active-input",
                "--rms-db",
                "-90.0",
                "--state-file",
                str(state),
            ]
        )
        assert result.returncode == 0
        assert "diagnostic=OK" in result.stdout

    def test_first_silent_tick_no_fire_yet(self, tmp_path: Path) -> None:
        """First symptomatic tick stamps silence_started_at but does not
        fire the diagnostic — needs accumulation across ticks."""
        state = tmp_path / "state.json"
        result = _run(
            [
                "pin-check",
                "--state",
                "RUNNING",
                "--has-active-input",
                "--rms-db",
                "-90.0",
                "--state-file",
                str(state),
                "--min-silence-s",
                "5.0",
            ]
        )
        assert result.returncode == 0
        assert "diagnostic=OK" in result.stdout
        # State file must now carry a silence_started_at timestamp.
        import json

        persisted = json.loads(state.read_text())
        assert persisted["silence_started_at"] is not None

    def test_persisted_old_silence_fires_diagnostic(self, tmp_path: Path) -> None:
        """If silence_started_at is far enough in the past, the next
        symptomatic tick fires PIN_GLITCH and exits 1 (no auto-fix)."""
        import json
        import time

        state = tmp_path / "state.json"
        # Pre-seed with a silence start 10s ago — well past the 5s threshold.
        state.write_text(json.dumps({"silence_started_at": time.time() - 10.0}))
        result = _run(
            [
                "pin-check",
                "--state",
                "RUNNING",
                "--has-active-input",
                "--rms-db",
                "-90.0",
                "--state-file",
                str(state),
                "--min-silence-s",
                "5.0",
            ]
        )
        assert result.returncode == 1
        assert "diagnostic=PIN_GLITCH" in result.stdout
        assert "PIN_GLITCH detected" in result.stderr

    def test_signal_returns_clears_state(self, tmp_path: Path) -> None:
        """A non-symptomatic tick clears the persisted silence window
        so a brief between-utterance silence doesn't persist into the
        next quiet period and falsely fire."""
        import json
        import time

        state = tmp_path / "state.json"
        state.write_text(json.dumps({"silence_started_at": time.time() - 3.0}))
        result = _run(
            [
                "pin-check",
                "--state",
                "RUNNING",
                "--has-active-input",
                "--rms-db",
                "-12.0",  # signal returned
                "--state-file",
                str(state),
            ]
        )
        assert result.returncode == 0
        persisted = json.loads(state.read_text())
        assert persisted["silence_started_at"] is None

    def test_state_file_corrupt_starts_fresh(self, tmp_path: Path) -> None:
        """Corrupt persisted state must not crash — fall back to empty."""
        state = tmp_path / "state.json"
        state.write_text("{not valid json")
        result = _run(
            [
                "pin-check",
                "--state",
                "RUNNING",
                "--has-active-input",
                "--rms-db",
                "-90.0",
                "--state-file",
                str(state),
            ]
        )
        assert result.returncode == 0  # First tick after recovery — no fire yet.


class TestInvalidDescriptor:
    def test_dangling_edge_exits_1(self, tmp_path: Path) -> None:
        bad = _write_yaml(
            tmp_path,
            """
            schema_version: 2
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
