"""Tests for agents.audio_codegen.spec_emitter (audit F)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agents.audio_codegen.spec_emitter import (
    DEFAULT_TOPOLOGY,
    SUPPORTED_CHAIN_KINDS,
    emit,
    main,
    validate_yaml_fragment_merges,
)

# ── emit() artifact production ──────────────────────────────────────


class TestEmit:
    def test_produces_three_artifacts(self, tmp_path: Path) -> None:
        artifacts = emit(
            source_id="new-mic-loudnorm",
            chain_kind="loudnorm",
            description="New mic loudnorm chain",
            staging_dir=tmp_path,
        )
        assert set(artifacts.keys()) == {"conf", "service", "yaml_fragment"}
        for path in artifacts.values():
            assert path.exists(), f"missing artifact: {path}"
            assert path.stat().st_size > 0, f"empty artifact: {path}"

    def test_conf_template_includes_source_identity(self, tmp_path: Path) -> None:
        artifacts = emit(
            source_id="x-loudnorm",
            chain_kind="loudnorm",
            description="x mic loudnorm",
            staging_dir=tmp_path,
        )
        conf_text = artifacts["conf"].read_text(encoding="utf-8")
        assert "x-loudnorm" in conf_text
        # Default pipewire_name = hapax-<source_id>.
        assert "hapax-x-loudnorm" in conf_text
        assert "fast_lookahead_limiter_1913" in conf_text

    def test_service_template_includes_conf_basename(self, tmp_path: Path) -> None:
        artifacts = emit(
            source_id="y-duck",
            chain_kind="duck",
            description="y duck",
            staging_dir=tmp_path,
        )
        service_text = artifacts["service"].read_text(encoding="utf-8")
        assert "hapax-y-duck.conf" in service_text
        assert "[Service]" in service_text
        # Standard hapax sandboxing markers present.
        assert "ProtectSystem=strict" in service_text
        assert "PrivateTmp=true" in service_text

    def test_yaml_fragment_parses_as_node_list(self, tmp_path: Path) -> None:
        artifacts = emit(
            source_id="z-loudnorm",
            chain_kind="loudnorm",
            description="z loudnorm",
            staging_dir=tmp_path,
        )
        fragment_text = artifacts["yaml_fragment"].read_text(encoding="utf-8")
        # The fragment is a list-shape (`- id: ...`). Wrap in a doc
        # to parse for validation.
        as_doc = yaml.safe_load("nodes:\n" + fragment_text)
        assert isinstance(as_doc, dict)
        nodes = as_doc.get("nodes")
        assert isinstance(nodes, list)
        assert len(nodes) == 1
        node = nodes[0]
        assert node["id"] == "z-loudnorm"
        assert node["kind"] == "filter_chain"
        assert node["chain_kind"] == "loudnorm"

    def test_unsupported_chain_kind_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="chain_kind"):
            emit(
                source_id="x",
                chain_kind="bogus",
                description="x",
                staging_dir=tmp_path,
            )

    def test_supported_chain_kinds_pinned(self) -> None:
        # Regression pin so a future code change doesn't silently
        # accept new chain_kind values without updating the live
        # TopologyDescriptor schema.
        assert SUPPORTED_CHAIN_KINDS == ("loudnorm", "duck", "usb-bias", "none")

    def test_custom_pipewire_name_honored(self, tmp_path: Path) -> None:
        artifacts = emit(
            source_id="abc",
            chain_kind="loudnorm",
            description="abc",
            staging_dir=tmp_path,
            pipewire_name="custom-pw-name",
        )
        conf_text = artifacts["conf"].read_text(encoding="utf-8")
        assert "custom-pw-name" in conf_text


# ── validate_yaml_fragment_merges() against live topology ───────────


class TestValidateMerges:
    def test_clean_fragment_validates_against_live(self, tmp_path: Path) -> None:
        artifacts = emit(
            source_id="generated-mic-loudnorm",
            chain_kind="loudnorm",
            description="Generated mic loudnorm chain (test)",
            staging_dir=tmp_path,
        )
        ok, msg = validate_yaml_fragment_merges(fragment_path=artifacts["yaml_fragment"])
        assert ok, f"validation failed: {msg}"

    def test_missing_topology_returns_false(self, tmp_path: Path) -> None:
        artifacts = emit(
            source_id="x",
            chain_kind="loudnorm",
            description="x",
            staging_dir=tmp_path,
        )
        ok, msg = validate_yaml_fragment_merges(
            fragment_path=artifacts["yaml_fragment"],
            topology_path=tmp_path / "no-such-topology.yaml",
        )
        assert ok is False
        assert "missing" in msg

    def test_empty_fragment_returns_false(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.yaml"
        empty.write_text("", encoding="utf-8")
        ok, msg = validate_yaml_fragment_merges(fragment_path=empty)
        assert ok is False
        assert "empty" in msg


# ── CLI entrypoint ──────────────────────────────────────────────────


class TestCli:
    def test_main_returns_zero_on_clean_emit(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(
            [
                "--source-id",
                "cli-test-mic-loudnorm",
                "--chain-kind",
                "loudnorm",
                "--description",
                "CLI test mic loudnorm",
                "--staging-dir",
                str(tmp_path),
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "Generated 3 artifacts" in out
        assert "Validation:" in out

    def test_main_skip_validate_returns_zero_without_validation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(
            [
                "--source-id",
                "skip-validate-test",
                "--chain-kind",
                "duck",
                "--description",
                "Skip-validate test",
                "--staging-dir",
                str(tmp_path),
                "--skip-validate",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "Validation:" not in out


# ── Live topology regression pin ────────────────────────────────────


class TestLiveTopologyExists:
    """The default topology path must point at a real file. If the
    operator moves the topology yaml, this test catches the spec_emitter
    breaking before live use."""

    def test_default_topology_exists(self) -> None:
        assert DEFAULT_TOPOLOGY.is_file(), (
            f"DEFAULT_TOPOLOGY={DEFAULT_TOPOLOGY} doesn't exist; "
            "spec_emitter validation will always fail until this points "
            "at a real audio-topology.yaml."
        )
