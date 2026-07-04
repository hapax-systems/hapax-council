"""Durable dispatch-unwedge pins for hapax-quota-telemetry.service (MOVE 4).

Root cause (2026-07-03, live-verified on appendix): the dispatch wedge had a
3-part cause; two parts were fixed only TRANSIENTLY (lost on reboot /
cache-clear), so the wedge could silently re-arm:

  (b) the systemd user PATH (``/usr/local/bin:/usr/bin``) excluded
      ``~/.npm-global/bin`` + ``~/.local/bin``, so the capability-receipt probe
      (``hapax-platform-capability-receipts``, spawned by the quota-telemetry
      writer and inheriting its environment) could not resolve the claude/codex
      CLIs -> ``cli_missing_or_unusable`` -> stale capability receipts ->
      route-policy HOLD -> ``dispatched=0``.
  (c) ``~/.cache/hapax/stage0-durable-sink`` was absent -> the durable
      gate-event emit failed -> dispatch failed.

The transient fixes were ``systemctl --user set-environment PATH=...`` (lost on
reboot) and a one-off ``mkdir`` (lost on cache-clear). These pins move both into
the unit itself so a reboot or cache-clear can never silently re-strand the
consumer. See cc-task-appendix-provisioner-topology-source-20260703.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-quota-telemetry.service"
SINK = "%h/.cache/hapax/stage0-durable-sink"


def _service_values(text: str, key: str) -> list[str]:
    """All values for ``key`` inside the ``[Service]`` section (skips comments)."""
    in_service = False
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_service = s == "[Service]"
            continue
        if not in_service or not s or s.startswith(("#", ";")) or "=" not in s:
            continue
        k, _, v = s.partition("=")
        if k.strip() == key:
            out.append(v.strip())
    return out


def _unit_text() -> str:
    return UNIT.read_text(encoding="utf-8")


def test_writer_path_exposes_cli_bins_for_capability_probe() -> None:
    """PATH must expose the operator CLI bins so the capability-receipt probe can
    resolve claude/codex (root cause b). Without ~/.npm-global/bin + ~/.local/bin
    the probe reports cli_missing_or_unusable and the receipts go stale, which
    is what latched the wedge."""
    env_vals = _service_values(_unit_text(), "Environment")
    path_vals = [v[len("PATH=") :] for v in env_vals if v.startswith("PATH=")]
    assert path_vals, "hapax-quota-telemetry.service must set Environment=PATH="
    entries = path_vals[0].split(":")
    assert "%h/.npm-global/bin" in entries, f"PATH missing ~/.npm-global/bin (codex): {entries}"
    assert "%h/.local/bin" in entries, f"PATH missing ~/.local/bin (claude): {entries}"


def test_execstartpre_creates_durable_sink() -> None:
    """The durable gate-event sink dir must be (re)created before the writer runs
    so a cache-clear cannot strand the emit (root cause c). The timer fires every
    ~10m, so an ExecStartPre mkdir is self-healing against cache-clear."""
    pre = _service_values(_unit_text(), "ExecStartPre")
    assert any("mkdir" in p and SINK in p for p in pre), (
        f"hapax-quota-telemetry.service must ExecStartPre mkdir -p {SINK}; got {pre}"
    )
