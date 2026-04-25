"""Tests for ``agents.live_captions.routing``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import yaml

from agents.live_captions.routing import RoutedCaptionWriter, RoutingPolicy
from agents.live_captions.writer import CaptionWriter


def _write_config(path: Path, **kwargs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(kwargs), encoding="utf-8")


# ── RoutingPolicy.load ─────────────────────────────────────────────


class TestPolicyLoad:
    def test_missing_file_defaults_allow(self, tmp_path):
        policy = RoutingPolicy.load(tmp_path / "absent.yaml")
        assert policy.default_allow is True
        assert policy.allow == frozenset()
        assert policy.deny == frozenset()

    def test_malformed_yaml_defaults_allow(self, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text(":not yaml::", encoding="utf-8")
        policy = RoutingPolicy.load(path)
        assert policy.default_allow is True

    def test_loads_allow_deny_lists(self, tmp_path):
        path = tmp_path / "routing.yaml"
        _write_config(path, allow=["op", "guest"], deny=["banned"], default="deny")
        policy = RoutingPolicy.load(path)
        assert policy.allow == frozenset({"op", "guest"})
        assert policy.deny == frozenset({"banned"})
        assert policy.default_allow is False

    def test_default_field_default_is_allow(self, tmp_path):
        path = tmp_path / "routing.yaml"
        _write_config(path, allow=["op"])
        policy = RoutingPolicy.load(path)
        assert policy.default_allow is True

    def test_non_dict_yaml_defaults_allow(self, tmp_path):
        path = tmp_path / "routing.yaml"
        path.write_text("- just a list\n", encoding="utf-8")
        policy = RoutingPolicy.load(path)
        assert policy.default_allow is True
        assert policy.allow == frozenset()


# ── RoutingPolicy.allows ──────────────────────────────────────────


class TestPolicyAllows:
    def test_empty_speaker_always_allowed(self):
        policy = RoutingPolicy(default_allow=False)
        assert policy.allows("") is True
        assert policy.allows(None) is True

    def test_explicit_deny_wins(self):
        policy = RoutingPolicy(allow=frozenset({"op"}), deny=frozenset({"op"}))
        assert policy.allows("op") is False

    def test_explicit_allow_passes(self):
        policy = RoutingPolicy(allow=frozenset({"op"}), default_allow=False)
        assert policy.allows("op") is True

    def test_unknown_speaker_default_allow(self):
        policy = RoutingPolicy(default_allow=True)
        assert policy.allows("unknown") is True

    def test_unknown_speaker_default_deny(self):
        policy = RoutingPolicy(default_allow=False)
        assert policy.allows("unknown") is False


# ── RoutedCaptionWriter ───────────────────────────────────────────


class TestRoutedWriter:
    def _make(self, policy: RoutingPolicy, tmp_path: Path):
        writer = mock.Mock(spec=CaptionWriter)
        return RoutedCaptionWriter(policy=policy, writer=writer), writer

    def test_allowed_caption_forwarded(self, tmp_path):
        routed, writer = self._make(RoutingPolicy(allow=frozenset({"op"})), tmp_path)
        ok = routed.emit(ts=1.0, text="hi", speaker="op")
        assert ok is True
        writer.emit.assert_called_once_with(ts=1.0, text="hi", duration_ms=0, speaker="op")

    def test_denied_caption_dropped(self, tmp_path):
        routed, writer = self._make(RoutingPolicy(deny=frozenset({"banned"})), tmp_path)
        ok = routed.emit(ts=1.0, text="hi", speaker="banned")
        assert ok is False
        writer.emit.assert_not_called()

    def test_no_speaker_always_emits(self, tmp_path):
        # Even with default-deny, missing speaker still emits (operator narration).
        routed, writer = self._make(RoutingPolicy(default_allow=False), tmp_path)
        ok = routed.emit(ts=1.0, text="hi")
        assert ok is True
        writer.emit.assert_called_once()

    def test_default_deny_drops_unknown(self, tmp_path):
        routed, writer = self._make(RoutingPolicy(default_allow=False), tmp_path)
        ok = routed.emit(ts=1.0, text="hi", speaker="unknown")
        assert ok is False
        writer.emit.assert_not_called()

    def test_reload_policy_swaps_decision(self, tmp_path):
        routed, writer = self._make(RoutingPolicy(allow=frozenset({"op"})), tmp_path)
        # First emit: op allowed.
        assert routed.emit(ts=1.0, text="ok1", speaker="op") is True
        # Reload from a config that denies op.
        path = tmp_path / "routing.yaml"
        _write_config(path, deny=["op"])
        routed.reload_policy(path)
        # Second emit: op now denied.
        assert routed.emit(ts=2.0, text="ok2", speaker="op") is False
        # Only the first emit reached the underlying writer.
        assert writer.emit.call_count == 1


# ── End-to-end: real writer with on-disk JSONL ────────────────────


class TestRoutedWriterE2E:
    def test_filtered_captions_dont_hit_jsonl(self, tmp_path):
        out = tmp_path / "live.jsonl"
        writer = CaptionWriter(captions_path=out)
        routed = RoutedCaptionWriter(
            policy=RoutingPolicy(deny=frozenset({"banned"}), default_allow=True),
            writer=writer,
        )
        routed.emit(ts=1.0, text="kept", speaker="op")
        routed.emit(ts=2.0, text="dropped", speaker="banned")
        routed.emit(ts=3.0, text="kept-too")
        records = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l]
        assert [r["text"] for r in records] == ["kept", "kept-too"]
