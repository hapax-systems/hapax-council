"""Layer C runtime backstop — private->broadcast leak guard.

Covers parsing of `pw-link -l`, forbidden-edge detection, repair via
`pw-link -d`, JSON status writing, and Prometheus textfile output.
The script under test is loaded by file path (no `.py` extension on
the executable) via `importlib`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
import types
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "hapax-private-broadcast-leak-guard"
WP_CONF_DIR = REPO_ROOT / "config" / "wireplumber"
DOC_PATH = REPO_ROOT / "docs" / "governance" / "private-broadcast-leak-guard.md"
TIMER_PATH = REPO_ROOT / "systemd" / "units" / "hapax-private-broadcast-leak-guard.timer"
SERVICE_PATH = REPO_ROOT / "systemd" / "units" / "hapax-private-broadcast-leak-guard.service"


def _load_module() -> types.ModuleType:
    # Script has no `.py` suffix so `spec_from_file_location` infers no
    # loader. Pass an explicit `SourceFileLoader`.
    loader = SourceFileLoader("leak_guard", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("leak_guard", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["leak_guard"] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def guard() -> types.ModuleType:
    return _load_module()


# ---------------------------------------------------------------------------
# pw-link parser
# ---------------------------------------------------------------------------


def test_parser_handles_forward_and_backward_links(guard: types.ModuleType) -> None:
    text = textwrap.dedent(
        """\
        hapax-livestream-tap:monitor_FL
          |-> hapax-broadcast-master-capture:input_FL
          |-> hapax-livestream-tap-src:input_FL
        hapax-livestream-tap:playback_FL
          |<- hapax-l12-evilpet-playback:output_FL
          |<- hapax-s4-tap:output_FL
        """
    )
    edges = guard.parse_pw_link(text)
    assert (
        "hapax-livestream-tap:monitor_FL",
        "hapax-broadcast-master-capture:input_FL",
    ) in edges
    assert (
        "hapax-livestream-tap:monitor_FL",
        "hapax-livestream-tap-src:input_FL",
    ) in edges
    # Backward links are normalised so output port comes first.
    assert (
        "hapax-l12-evilpet-playback:output_FL",
        "hapax-livestream-tap:playback_FL",
    ) in edges
    assert (
        "hapax-s4-tap:output_FL",
        "hapax-livestream-tap:playback_FL",
    ) in edges


def test_parser_ignores_blank_lines_and_unrelated_text(guard: types.ModuleType) -> None:
    text = textwrap.dedent(
        """\

        hapax-private:monitor_FL
          |-> hapax-private-monitor-capture:input_FL

        hapax-private:monitor_FR
          |-> hapax-private-monitor-capture:input_FR
        """
    )
    edges = guard.parse_pw_link(text)
    assert len(edges) == 2
    assert all(src.startswith("hapax-private:") for src, _ in edges)


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------


def test_detect_legitimate_yeti_route_is_not_flagged(guard: types.ModuleType) -> None:
    legitimate = textwrap.dedent(
        """\
        hapax-private-playback:output_FL
          |-> alsa_output.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo:playback_FL
        hapax-private-playback:output_FR
          |-> alsa_output.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo:playback_FR
        hapax-private:monitor_FL
          |-> hapax-private-monitor-capture:input_FL
        """
    )
    edges = guard.parse_pw_link(legitimate)
    leaks = guard.detect_forbidden(edges)
    assert leaks == []


def test_detect_today_incident_l12_leak(guard: types.ModuleType) -> None:
    """Reproduces the 2026-05-02 incident edge."""
    incident = textwrap.dedent(
        """\
        hapax-private-playback:output_FL
          |-> alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FL
        hapax-private-playback:output_FR
          |-> alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FR
        """
    )
    edges = guard.parse_pw_link(incident)
    leaks = guard.detect_forbidden(edges)
    assert len(leaks) == 2
    for leak in leaks:
        assert leak.source_node == "hapax-private-playback"
        assert "ZOOM_Corporation_L-12" in leak.target_node


def test_detect_notification_private_to_broadcast(guard: types.ModuleType) -> None:
    text = textwrap.dedent(
        """\
        hapax-notification-private-playback:output_FL
          |-> hapax-livestream-tap:playback_FL
        """
    )
    edges = guard.parse_pw_link(text)
    leaks = guard.detect_forbidden(edges)
    assert len(leaks) == 1
    assert leaks[0].target_node == "hapax-livestream-tap"


def test_detect_covers_all_forbidden_target_families(guard: types.ModuleType) -> None:
    """One edge per forbidden target family — guard must catch every one.

    MPC Live III AUX8/AUX9 is the only allowed private-monitor ingress.
    S-4 USB audio is no longer an approved private target in HN readiness.
    """
    forbidden_targets = [
        "alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40:playback_FL",
        "alsa_input.usb-Torso_Electronics_S-4_fedcba9876543220-03.multichannel-input:capture_FL",
        "alsa_output.usb-Torso_Electronics_S-4_fedcba9876543220-03.multichannel-output:playback_AUX0",
        # S-4 virtual loopback nodes that forward to broadcast.
        "hapax-s4-content:input_FL",
        "hapax-s4-tap:output_FL",
        "hapax-livestream:playback_FL",
        "hapax-livestream-tap:playback_FL",
        "hapax-broadcast-master:capture_FL",
        "hapax-broadcast-normalized:capture_FL",
        "hapax-music-duck:input_FL",
        "hapax-tts-duck:input_FL",
        "hapax-music-loudnorm:input_FL",
        "hapax-pc-loudnorm:input_FL",
        "hapax-voice-fx-capture:input_FL",
        "hapax-loudnorm-capture:input_FL",
        "hapax-obs-broadcast-remap:input_FL",
    ]
    body = ""
    for target in forbidden_targets:
        body += f"hapax-private-playback:output_FL\n  |-> {target}\n"
    edges = guard.parse_pw_link(body)
    leaks = guard.detect_forbidden(edges)
    assert len(leaks) == len(forbidden_targets), (
        f"missing detections for {set(forbidden_targets) - {leak.target_port for leak in leaks}}"
    )


def test_detect_dedupes_identical_links(guard: types.ModuleType) -> None:
    """Multiple traversals of the same edge in pw-link should produce one record."""
    text = textwrap.dedent(
        """\
        hapax-private-playback:output_FL
          |-> hapax-livestream-tap:playback_FL
        hapax-livestream-tap:playback_FL
          |<- hapax-private-playback:output_FL
        """
    )
    edges = guard.parse_pw_link(text)
    leaks = guard.detect_forbidden(edges)
    assert len(leaks) == 1


def test_detect_ignores_non_private_sources(guard: types.ModuleType) -> None:
    """Legitimate broadcast feeds (s4-tap, evilpet) are NOT private streams."""
    text = textwrap.dedent(
        """\
        hapax-s4-tap:output_FL
          |-> hapax-livestream-tap:playback_FL
        hapax-l12-evilpet-playback:output_FL
          |-> hapax-livestream-tap:playback_FL
        """
    )
    edges = guard.parse_pw_link(text)
    leaks = guard.detect_forbidden(edges)
    assert leaks == []


# ---------------------------------------------------------------------------
# repair
# ---------------------------------------------------------------------------


class FakeRunner:
    def __init__(self, pw_link_text: str = "", disconnect_ok: bool = True) -> None:
        self._pw_link_text = pw_link_text
        self._disconnect_ok = disconnect_ok
        self.disconnect_calls: list[tuple[str, str]] = []

    def list_links(self) -> str:
        return self._pw_link_text

    def disconnect(self, src: str, dst: str) -> tuple[bool, str]:
        self.disconnect_calls.append((src, dst))
        return self._disconnect_ok, "" if self._disconnect_ok else "pw-link: failed"


def test_run_once_repairs_each_detected_leak(guard: types.ModuleType, tmp_path: Path) -> None:
    text = textwrap.dedent(
        """\
        hapax-private-playback:output_FL
          |-> alsa_output.usb-ZOOM_Corporation_L-12_aaa-00.analog-surround-40:playback_FL
        hapax-private-playback:output_FR
          |-> alsa_output.usb-ZOOM_Corporation_L-12_aaa-00.analog-surround-40:playback_FR
        """
    )
    runner = FakeRunner(text)
    status = guard.run_once(
        runner=runner,
        status_path=tmp_path / "status.json",
        metrics_path=tmp_path / "metrics.prom",
    )
    assert status["leak_count"] == 2
    assert all(leak["repaired"] for leak in status["leaks"])
    assert len(runner.disconnect_calls) == 2
    # Each call uses (output_port, input_port) ordering.
    for src, dst in runner.disconnect_calls:
        assert src.startswith("hapax-private-playback:")
        assert "ZOOM_Corporation_L-12" in dst


def test_run_once_no_repair_when_disabled(guard: types.ModuleType, tmp_path: Path) -> None:
    text = "hapax-private-playback:output_FL\n  |-> hapax-livestream-tap:playback_FL\n"
    runner = FakeRunner(text)
    status = guard.run_once(
        runner=runner,
        repair=False,
        status_path=tmp_path / "status.json",
    )
    assert status["leak_count"] == 1
    assert status["leaks"][0]["repaired"] is False
    assert runner.disconnect_calls == []


def test_run_once_records_repair_failure(guard: types.ModuleType, tmp_path: Path) -> None:
    text = "hapax-private-playback:output_FL\n  |-> hapax-livestream-tap:playback_FL\n"
    runner = FakeRunner(text, disconnect_ok=False)
    status = guard.run_once(
        runner=runner,
        status_path=tmp_path / "status.json",
    )
    assert status["leak_count"] == 1
    assert status["leaks"][0]["repaired"] is False
    assert "pw-link: failed" in status["leaks"][0]["error"]


def test_run_once_writes_status_json(guard: types.ModuleType, tmp_path: Path) -> None:
    runner = FakeRunner("")  # empty graph
    status_path = tmp_path / "shm" / "hapax-private-broadcast" / "status.json"
    status = guard.run_once(runner=runner, status_path=status_path)
    assert status["ok"] is True
    assert status_path.exists()
    persisted = json.loads(status_path.read_text(encoding="utf-8"))
    assert persisted["leak_count"] == 0
    assert persisted["leaks"] == []


def test_run_once_writes_prometheus_metrics(guard: types.ModuleType, tmp_path: Path) -> None:
    text = textwrap.dedent(
        """\
        hapax-private-playback:output_FL
          |-> alsa_output.usb-ZOOM_Corporation_L-12_aaa-00.analog-surround-40:playback_FL
        hapax-notification-private-playback:output_FL
          |-> hapax-livestream-tap:playback_FL
        """
    )
    runner = FakeRunner(text)
    metrics = tmp_path / "metrics.prom"
    guard.run_once(
        runner=runner,
        status_path=tmp_path / "status.json",
        metrics_path=metrics,
    )
    body = metrics.read_text(encoding="utf-8")
    assert "hapax_private_broadcast_leak_detected_total" in body
    assert "hapax_private_broadcast_leak_repaired_total" in body
    # One detection per target node — both labels present.
    assert 'target="hapax-livestream-tap"' in body
    assert (
        any(
            line.startswith("hapax_private_broadcast_leak_detected_total")
            and "ZOOM_Corporation_L-12" not in line  # label is target NODE not raw
            for line in body.splitlines()
        )
        or 'target="alsa_output.usb-ZOOM_Corporation_L-12_aaa-00.analog-surround-40"' in body
    )


def test_run_once_clean_graph_returns_ok(guard: types.ModuleType, tmp_path: Path) -> None:
    legitimate = textwrap.dedent(
        """\
        hapax-private-playback:output_FL
          |-> alsa_output.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo:playback_FL
        hapax-private:monitor_FL
          |-> hapax-private-monitor-capture:input_FL
        """
    )
    runner = FakeRunner(legitimate)
    status = guard.run_once(runner=runner, status_path=tmp_path / "status.json")
    assert status["ok"] is True
    assert status["leak_count"] == 0


# ---------------------------------------------------------------------------
# fail-CLOSED on pw-link unreachable
# ---------------------------------------------------------------------------
#
# REGRESSION PIN — 2026-05-02 audit finding (D, B1).
#
# Before this fix, `PwLinkRunner.list_links()` ran `pw-link -l` with
# `check=False` and returned `proc.stdout` unconditionally. If `pw-link`
# was missing, exited non-zero, or PipeWire was restarting, `parse_pw_link("")`
# returned `[]` and the guard wrote `{"ok": true, "leak_count": 0}` and
# exited 0 — silent fail-OPEN of the privacy invariant
# `feedback_l12_equals_livestream_invariant`. These tests pin the
# fail-CLOSED behaviour: PwLinkUnavailableError raised by the runner, witness
# JSON `ok=false`/`unavailable=true`, and `main()` exit code 2 distinct
# from "leak detected" (exit 1).


class _RaisingRunner:
    """Runner whose `list_links` always raises PwLinkUnavailableError."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.disconnect_calls: list[tuple[str, str]] = []

    def list_links(self) -> str:
        raise self._exc

    def disconnect(self, src: str, dst: str) -> tuple[bool, str]:
        self.disconnect_calls.append((src, dst))
        return True, ""


def test_pw_link_runner_raises_on_nonzero_exit(guard: types.ModuleType) -> None:
    """Real PwLinkRunner.list_links must raise on non-zero pw-link exit."""
    fake_proc = subprocess.CompletedProcess(
        args=["pw-link", "-l"],
        returncode=2,
        stdout="",
        stderr="Connection refused",
    )
    runner = guard.PwLinkRunner()
    with mock.patch.object(guard.subprocess, "run", return_value=fake_proc):
        with pytest.raises(guard.PwLinkUnavailableError) as excinfo:
            runner.list_links()
    assert "Connection refused" in excinfo.value.stderr
    assert excinfo.value.returncode == 2


def test_pw_link_runner_raises_on_missing_binary(guard: types.ModuleType) -> None:
    """Real PwLinkRunner.list_links must raise if `pw-link` is not on PATH."""
    runner = guard.PwLinkRunner()
    with mock.patch.object(
        guard.subprocess, "run", side_effect=FileNotFoundError("no such file: pw-link")
    ):
        with pytest.raises(guard.PwLinkUnavailableError) as excinfo:
            runner.list_links()
    assert "not found" in str(excinfo.value).lower()


def test_pw_link_runner_returns_empty_string_when_graph_is_empty(
    guard: types.ModuleType,
) -> None:
    """Empty stdout with returncode 0 IS a legitimate state (early boot)."""
    fake_proc = subprocess.CompletedProcess(
        args=["pw-link", "-l"], returncode=0, stdout="", stderr=""
    )
    runner = guard.PwLinkRunner()
    with mock.patch.object(guard.subprocess, "run", return_value=fake_proc):
        out = runner.list_links()
    assert out == ""


def test_run_once_writes_unavailable_witness_when_pw_link_fails(
    guard: types.ModuleType, tmp_path: Path
) -> None:
    """run_once must catch PwLinkUnavailableError and write fail-CLOSED witness."""
    runner = _RaisingRunner(
        guard.PwLinkUnavailableError(
            "pw-link -l exited 2",
            stderr="Connection refused",
            returncode=2,
        )
    )
    status_path = tmp_path / "status.json"
    metrics_path = tmp_path / "metrics.prom"
    status = guard.run_once(
        runner=runner,
        status_path=status_path,
        metrics_path=metrics_path,
    )
    assert status["ok"] is False
    assert status["unavailable"] is True
    assert status["leak_count"] == 0
    assert status["leaks"] == []
    assert "Connection refused" in status["error"]
    assert "pw-link unreachable" in status["error"]
    # Witness JSON persisted on disk for the operator + observability.
    persisted = json.loads(status_path.read_text(encoding="utf-8"))
    assert persisted["ok"] is False
    assert persisted["unavailable"] is True
    assert "Connection refused" in persisted["error"]
    # No repair attempts when the graph couldn't even be read.
    assert runner.disconnect_calls == []
    # Stale prom file MUST NOT be overwritten with zeroed counters during
    # a transient pw-link outage — the witness JSON carries the signal.
    assert not metrics_path.exists()


def test_main_exits_2_when_pw_link_unreachable(
    guard: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main() must exit 2 (guard cannot evaluate) — distinct from exit 1 (leak)."""
    fake_proc = subprocess.CompletedProcess(
        args=["pw-link", "-l"],
        returncode=2,
        stdout="",
        stderr="Connection refused",
    )
    monkeypatch.setattr(guard.subprocess, "run", lambda *a, **kw: fake_proc)
    status_path = tmp_path / "status.json"
    rc = guard.main(
        [
            "--status-path",
            str(status_path),
            "--no-repair",
        ]
    )
    assert rc == 2, "guard cannot evaluate must exit 2 (distinct from leak-detected exit 1)"
    persisted = json.loads(status_path.read_text(encoding="utf-8"))
    assert persisted["ok"] is False
    assert persisted["unavailable"] is True
    assert "Connection refused" in persisted["error"]


def test_main_exits_1_when_leak_detected(guard: types.ModuleType, tmp_path: Path) -> None:
    """main() must exit 1 on leak detection — distinct from fail-CLOSED exit 2."""
    fixture = tmp_path / "pw-link.txt"
    fixture.write_text(
        "hapax-private-playback:output_FL\n  |-> hapax-livestream-tap:playback_FL\n",
        encoding="utf-8",
    )
    status_path = tmp_path / "status.json"
    rc = guard.main(
        [
            "--status-path",
            str(status_path),
            "--fixture",
            str(fixture),
            "--no-repair",
        ]
    )
    assert rc == 1, "leak-detected must exit 1 (distinct from guard-broken exit 2)"
    persisted = json.loads(status_path.read_text(encoding="utf-8"))
    assert persisted["ok"] is False
    assert persisted.get("unavailable") is not True
    assert persisted["leak_count"] == 1


def test_main_exits_0_on_clean_graph(guard: types.ModuleType, tmp_path: Path) -> None:
    """main() must exit 0 when no forbidden links observed."""
    fixture = tmp_path / "pw-link.txt"
    fixture.write_text("", encoding="utf-8")
    status_path = tmp_path / "status.json"
    rc = guard.main(
        [
            "--status-path",
            str(status_path),
            "--fixture",
            str(fixture),
        ]
    )
    assert rc == 0


# ---------------------------------------------------------------------------
# config + systemd shape
# ---------------------------------------------------------------------------


def test_layer_a_disables_state_restore() -> None:
    body = (WP_CONF_DIR / "55-hapax-private-no-restore.conf").read_text(encoding="utf-8")
    assert "restore-stream.rules" in body
    assert "state.restore-target = false" in body
    assert "state.restore-props = false" in body
    assert 'node.name = "hapax-private-playback"' in body
    assert 'node.name = "hapax-notification-private-playback"' in body
    # Must reference today's incident so the why doesn't get lost.
    assert "2026-05-02" in body


def test_layer_b_pins_mpc_target_with_fail_closed_props() -> None:
    body = (WP_CONF_DIR / "56-hapax-private-pin-s4-track-1.conf").read_text(encoding="utf-8")
    assert "target.object" in body
    assert "Akai_Professional_MPC_LIVE_III" in body
    assert "Torso_Electronics_S-4" not in body
    assert "multichannel-output" in body
    assert "node.dont-fallback = true" in body
    assert "node.linger = true" in body
    assert "priority.session = -1" in body
    assert 'node.name = "hapax-private-playback"' in body


def test_layer_b_yeti_pin_preserved_disabled() -> None:
    """Legacy Yeti pin remains disabled on disk, not active."""
    disabled = WP_CONF_DIR / "56-hapax-private-pin-yeti.conf.disabled-2026-05-02-option-c"
    assert disabled.exists(), "Yeti pin must remain on disk for revert capability"
    body = disabled.read_text(encoding="utf-8")
    assert "Blue_Microphones_Yeti_Stereo_Microphone_REV8" in body


def test_systemd_timer_runs_every_30s() -> None:
    body = TIMER_PATH.read_text(encoding="utf-8")
    assert "OnUnitActiveSec=30s" in body
    assert "Persistent=true" in body


def test_systemd_service_invokes_leak_guard_with_metrics_path() -> None:
    body = SERVICE_PATH.read_text(encoding="utf-8")
    assert "ExecStart=" in body
    assert "hapax-private-broadcast-leak-guard" in body
    assert "--metrics-path" in body
    assert "After=pipewire.service wireplumber.service" in body


def test_governance_doc_explains_three_layers() -> None:
    body = DOC_PATH.read_text(encoding="utf-8")
    for marker in [
        "Layer A",
        "Layer B",
        "Layer C",
        "feedback_l12_equals_livestream_invariant",
        "2026-05-02",
        "55-hapax-private-no-restore.conf",
        "56-hapax-private-pin-s4-track-1.conf",
        "hapax-private-broadcast-leak-guard",
    ]:
        assert marker in body, f"governance doc missing: {marker}"
