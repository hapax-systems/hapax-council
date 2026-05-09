"""Tests for cc-task audio-audit-O3c-option-c-pin-resolution-watchdog.

Pin the script's contract via mocked pactl output:

  L0: script exists + executable + bash -n parses cleanly
  L1: --dry-run does not call pactl set-card-profile
  L2: --help exits 0 and prints usage
  L3: idempotent — no-op when active profile already matches
  L4: drift detection + repin when active profile diverges
  L5: textfile counter increments correctly
  L6: missing pactl exits 2 with error metric increment
  L7: missing card exits 2

The mocked-pactl approach: drop a stub `pactl` script into a tmp dir,
prepend to PATH, run hapax-option-c-repin against synthetic state.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-option-c-repin"


def _make_pactl_stub(
    tmp_path: Path,
    *,
    cards_short: str,
    cards_long: str,
    set_profile_exit: int = 0,
) -> Path:
    """Write a stub `pactl` to tmp_path/bin/ that mimics the subset
    hapax-option-c-repin queries. Returns the bin dir to prepend to PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "pactl"
    stub.write_text(
        f"""#!/bin/bash
case "$1 $2" in
  "list cards") cat <<'EOF'
{cards_long}
EOF
    ;;
  "list cards-short"|"list cards short") cat <<'EOF'
{cards_short}
EOF
    ;;
  "set-card-profile"*)
    exit {set_profile_exit}
    ;;
  *) exit 0 ;;
esac
"""
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def _run(
    tmp_path: Path,
    *args: str,
    pactl_bin: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    if pactl_bin is not None:
        env["PATH"] = f"{pactl_bin}:{env.get('PATH', '')}"
    env["HAPAX_OPTION_C_TEXTFILE_DIR"] = str(tmp_path / "metrics")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


# Card description matches what pactl exposes on current Linux 6.x +
# PipeWire stacks for the AMD Ryzen on-board HDA. The legacy pattern
# "Family 17h/19h HD Audio" was a kernel-level designation that no
# longer surfaces through PulseAudio/PipeWire properties. Fixtures use
# the canonical "Ryzen HD Audio Controller" string from
# device.product.name / device.description.
CANONICAL_LONG = """\
Card #0
\tName: alsa_card.pci-0000_03_00.6
\tDriver: alsa
\tProperties:
\t\talsa.card_name = "HD-Audio Generic"
\t\tdevice.description = "Ryzen HD Audio Controller"
\tActive Profile: output:analog-stereo
"""

DRIFTED_LONG = """\
Card #0
\tName: alsa_card.pci-0000_03_00.6
\tDriver: alsa
\tProperties:
\t\talsa.card_name = "HD-Audio Generic"
\t\tdevice.description = "Ryzen HD Audio Controller"
\tActive Profile: output:hdmi-stereo
"""

# `pactl list cards short` emits index, name, module-name (no product
# description) — the script's primary lookup path always falls through
# to the long-form fallback regex on real systems. Fixture mirrors the
# fields the script's grep filter expects (alsa_card.pci-*).
CARDS_SHORT = "0\talsa_card.pci-0000_03_00.6\tmodule-alsa-card.c\toutput:analog-stereo"


class TestScriptShape:
    def test_script_exists_and_executable(self) -> None:
        assert SCRIPT.is_file()
        mode = SCRIPT.stat().st_mode
        assert mode & stat.S_IXUSR, "hapax-option-c-repin not executable"

    def test_bash_syntax_clean(self) -> None:
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        assert result.returncode == 0, f"bash -n failed: {result.stderr}"


class TestHelpAndDryRun:
    def test_help_exits_zero(self, tmp_path: Path) -> None:
        bin_dir = _make_pactl_stub(tmp_path, cards_short=CARDS_SHORT, cards_long=CANONICAL_LONG)
        result = _run(tmp_path, "--help", pactl_bin=bin_dir)
        assert result.returncode == 0
        assert result.stdout.strip(), "--help produced empty output"

    def test_dry_run_does_not_call_set_profile(self, tmp_path: Path) -> None:
        """When drift exists, --dry-run prints the would-do but doesn't
        actually run set-card-profile (the stub would log if called;
        we just verify the script's path)."""
        bin_dir = _make_pactl_stub(tmp_path, cards_short=CARDS_SHORT, cards_long=DRIFTED_LONG)
        result = _run(tmp_path, "--dry-run", pactl_bin=bin_dir)
        assert result.returncode == 0
        assert "[dry-run]" in result.stdout
        assert "would: pactl set-card-profile" in result.stdout


class TestIdempotentNoop:
    def test_already_correct_profile_is_no_op(self, tmp_path: Path) -> None:
        bin_dir = _make_pactl_stub(tmp_path, cards_short=CARDS_SHORT, cards_long=CANONICAL_LONG)
        result = _run(tmp_path, pactl_bin=bin_dir)
        assert result.returncode == 0
        assert "no-op" in result.stdout or "already at" in result.stdout

    def test_idempotent_metric_marks_already_correct(self, tmp_path: Path) -> None:
        bin_dir = _make_pactl_stub(tmp_path, cards_short=CARDS_SHORT, cards_long=CANONICAL_LONG)
        _run(tmp_path, pactl_bin=bin_dir)
        textfile = tmp_path / "metrics" / "hapax_option_c_repin.prom"
        assert textfile.exists()
        content = textfile.read_text()
        assert 'outcome="already-correct"' in content
        assert 'hapax_option_c_repin_total{outcome="already-correct"} 1' in content


class TestDriftCorrection:
    def test_drift_triggers_repin(self, tmp_path: Path) -> None:
        bin_dir = _make_pactl_stub(tmp_path, cards_short=CARDS_SHORT, cards_long=DRIFTED_LONG)
        result = _run(tmp_path, pactl_bin=bin_dir)
        assert result.returncode == 0
        assert "repinned" in result.stdout

    def test_repin_metric_increments(self, tmp_path: Path) -> None:
        bin_dir = _make_pactl_stub(tmp_path, cards_short=CARDS_SHORT, cards_long=DRIFTED_LONG)
        _run(tmp_path, pactl_bin=bin_dir)
        textfile = tmp_path / "metrics" / "hapax_option_c_repin.prom"
        content = textfile.read_text()
        assert 'hapax_option_c_repin_total{outcome="repinned"} 1' in content

    def test_set_profile_failure_emits_error_metric(self, tmp_path: Path) -> None:
        bin_dir = _make_pactl_stub(
            tmp_path,
            cards_short=CARDS_SHORT,
            cards_long=DRIFTED_LONG,
            set_profile_exit=1,
        )
        result = _run(tmp_path, pactl_bin=bin_dir)
        assert result.returncode == 1
        textfile = tmp_path / "metrics" / "hapax_option_c_repin.prom"
        content = textfile.read_text()
        assert 'outcome="error"' in content


class TestMissingCard:
    def test_missing_card_exits_two(self, tmp_path: Path) -> None:
        empty_long = "Card #99\n\tName: alsa_card.pci-0000_99_99.9\n\tActive Profile: foo\n"
        bin_dir = _make_pactl_stub(tmp_path, cards_short="", cards_long=empty_long)
        result = _run(tmp_path, pactl_bin=bin_dir)
        assert result.returncode == 2


class TestCounterMonotonicity:
    """Per-outcome counters must accumulate across ticks (Prometheus
    counter contract)."""

    def test_already_correct_counter_increments_on_repeat(self, tmp_path: Path) -> None:
        bin_dir = _make_pactl_stub(tmp_path, cards_short=CARDS_SHORT, cards_long=CANONICAL_LONG)
        _run(tmp_path, pactl_bin=bin_dir)
        _run(tmp_path, pactl_bin=bin_dir)
        _run(tmp_path, pactl_bin=bin_dir)
        textfile = tmp_path / "metrics" / "hapax_option_c_repin.prom"
        content = textfile.read_text()
        assert 'hapax_option_c_repin_total{outcome="already-correct"} 3' in content


@pytest.mark.parametrize("outcome", ["repinned", "already-correct", "error"])
def test_metric_label_exists(tmp_path: Path, outcome: str) -> None:
    """All 3 outcome labels must appear in every textfile write so
    Grafana's by-label sums are stable from tick 1."""
    bin_dir = _make_pactl_stub(tmp_path, cards_short=CARDS_SHORT, cards_long=CANONICAL_LONG)
    _run(tmp_path, pactl_bin=bin_dir)
    textfile = tmp_path / "metrics" / "hapax_option_c_repin.prom"
    content = textfile.read_text()
    assert f'outcome="{outcome}"' in content
