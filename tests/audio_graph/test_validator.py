"""Validator tests — synthetic confs decompose to expected AudioGraph;
broken confs surface gaps."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from shared.audio_graph.schema import NodeKind
from shared.audio_graph.validator import AudioGraphValidator


@pytest.fixture
def conf_dir(tmp_path: Path) -> Path:
    """Empty conf directory for synthetic tests."""
    d = tmp_path / "pipewire.conf.d"
    d.mkdir()
    return d


def _write(conf_dir: Path, filename: str, content: str) -> None:
    (conf_dir / filename).write_text(textwrap.dedent(content).lstrip())


class TestNullSinkDecompose:
    def test_minimal_null_sink(self, conf_dir: Path) -> None:
        _write(
            conf_dir,
            "hapax-test-tap.conf",
            """
            context.objects = [
                {   factory = adapter
                    args = {
                        factory.name     = support.null-audio-sink
                        node.name        = "hapax-test-tap"
                        node.description = "Test Tap"
                        media.class      = Audio/Sink
                        audio.position   = [ FL FR ]
                    }
                }
            ]
            """,
        )
        report = AudioGraphValidator().decompose(conf_dir)
        assert report.gaps == ()
        assert len(report.graph.nodes) == 1
        node = report.graph.nodes[0]
        assert node.kind == NodeKind.NULL_SINK
        assert node.pipewire_name == "hapax-test-tap"
        assert node.channels.count == 2
        assert node.channels.positions == ("FL", "FR")


class TestLoopbackDecompose:
    def test_minimal_loopback(self, conf_dir: Path) -> None:
        _write(
            conf_dir,
            "hapax-bridge.conf",
            """
            context.modules = [
                {   name = libpipewire-module-loopback
                    args = {
                        node.description = "Bridge"
                        capture.props = {
                            node.name      = "hapax-bridge-cap"
                            target.object  = "hapax-source"
                            audio.channels = 2
                            audio.position = [ FL FR ]
                        }
                        playback.props = {
                            node.name      = "hapax-bridge"
                            target.object  = "hapax-sink"
                            audio.channels = 2
                            audio.position = [ FL FR ]
                        }
                    }
                }
            ]
            """,
        )
        report = AudioGraphValidator().decompose(conf_dir)
        assert report.gaps == ()
        # Should produce one LOOPBACK node + one LoopbackTopology
        assert len(report.graph.nodes) == 1
        assert report.graph.nodes[0].kind == NodeKind.LOOPBACK
        assert len(report.graph.loopbacks) == 1
        lb = report.graph.loopbacks[0]
        assert lb.source == "hapax-source"
        assert lb.sink == "hapax-sink"


class TestFilterChainDecompose:
    def test_minimal_filter_chain(self, conf_dir: Path) -> None:
        _write(
            conf_dir,
            "hapax-chain.conf",
            """
            context.modules = [
                {   name = libpipewire-module-filter-chain
                    args = {
                        node.description = "Test Chain"
                        audio.channels = 2
                        audio.position = [ FL FR ]
                        filter.graph = {
                            nodes = [
                                { type = builtin label = mixer name = mix
                                  control = { "Gain 1" = 1.0 } }
                            ]
                            inputs = [ "mix:In 1" ]
                            outputs = [ "mix:Out" ]
                        }
                        capture.props = {
                            node.name = "hapax-chain"
                            target.object = "hapax-upstream"
                            audio.channels = 2
                            audio.position = [ FL FR ]
                        }
                        playback.props = {
                            node.name = "hapax-chain-playback"
                            audio.channels = 2
                            audio.position = [ FL FR ]
                        }
                    }
                }
            ]
            """,
        )
        report = AudioGraphValidator().decompose(conf_dir)
        assert report.gaps == ()
        assert len(report.graph.nodes) == 1
        node = report.graph.nodes[0]
        assert node.kind == NodeKind.FILTER_CHAIN
        assert node.pipewire_name == "hapax-chain"
        assert node.target_object == "hapax-upstream"
        # filter_graph blob captured as opaque
        assert node.filter_graph is not None
        assert "mix" in node.filter_graph["__raw_text__"]


class TestSkipPatterns:
    def test_disabled_files_skipped(self, conf_dir: Path) -> None:
        _write(conf_dir, "hapax-x.conf.disabled", "garbage that won't parse")
        _write(conf_dir, "hapax-y.conf.bak-1234", "more garbage")
        _write(conf_dir, "_disabled-foo.conf", "garbage")
        report = AudioGraphValidator().decompose(conf_dir)
        assert report.gaps == ()
        assert len(report.skipped_files) >= 3

    def test_non_conf_files_skipped(self, conf_dir: Path) -> None:
        _write(conf_dir, "readme.md", "## Notes")
        report = AudioGraphValidator().decompose(conf_dir)
        assert report.gaps == ()


class TestGraphTunables:
    def test_quantum_conf_recognised(self, conf_dir: Path) -> None:
        _write(
            conf_dir,
            "10-voice-quantum.conf",
            """
            context.properties = {
                default.clock.quantum = 128
                default.clock.min-quantum = 64
            }
            """,
        )
        report = AudioGraphValidator().decompose(conf_dir)
        assert report.gaps == ()
        # Tunable conf does not introduce nodes
        assert len(report.graph.nodes) == 0

    def test_wireplumber_rules_recognised(self, conf_dir: Path) -> None:
        _write(
            conf_dir,
            "s4-usb-sink.conf",
            """
            monitor.alsa.rules = [
                {
                    matches = [ { device.name = "~alsa_card.usb-Foo*" } ]
                    actions = { update-props = { device.profile = "pro-audio" } }
                }
            ]
            """,
        )
        report = AudioGraphValidator().decompose(conf_dir)
        assert report.gaps == ()


class TestGapDetection:
    def test_unknown_module_surfaces_gap(self, conf_dir: Path) -> None:
        _write(
            conf_dir,
            "hapax-bogus.conf",
            """
            context.modules = [
                {   name = libpipewire-module-undocumented-thing
                    args = {
                        node.name = "x"
                    }
                }
            ]
            """,
        )
        report = AudioGraphValidator().decompose(conf_dir)
        assert len(report.gaps) >= 1
        assert any("undocumented" in g.message for g in report.gaps)

    def test_unstructured_conf_surfaces_gap(self, conf_dir: Path) -> None:
        _write(
            conf_dir,
            "hapax-unparseable.conf",
            """
            some.weird.directive = something
            another.thing = [ a b c ]
            """,
        )
        report = AudioGraphValidator().decompose(conf_dir)
        assert len(report.gaps) >= 1


class TestEmptyDir:
    def test_empty_dir_no_gaps(self, conf_dir: Path) -> None:
        report = AudioGraphValidator().decompose(conf_dir)
        assert report.gaps == ()
        assert len(report.graph.nodes) == 0

    def test_missing_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            AudioGraphValidator().decompose(tmp_path / "does-not-exist")


class TestMultipleConfs:
    def test_two_confs_combine(self, conf_dir: Path) -> None:
        _write(
            conf_dir,
            "hapax-tap-a.conf",
            """
            context.objects = [
                {   factory = adapter
                    args = {
                        factory.name = support.null-audio-sink
                        node.name = "hapax-tap-a"
                        media.class = Audio/Sink
                        audio.position = [ FL FR ]
                    }
                }
            ]
            """,
        )
        _write(
            conf_dir,
            "hapax-tap-b.conf",
            """
            context.objects = [
                {   factory = adapter
                    args = {
                        factory.name = support.null-audio-sink
                        node.name = "hapax-tap-b"
                        media.class = Audio/Sink
                        audio.position = [ FL FR ]
                    }
                }
            ]
            """,
        )
        report = AudioGraphValidator().decompose(conf_dir)
        assert report.gaps == ()
        names = sorted(n.pipewire_name for n in report.graph.nodes)
        assert names == ["hapax-tap-a", "hapax-tap-b"]
