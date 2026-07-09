"""Static pins for the SDLC resource-shielding units (the anti-kill scheme).

Shield real-time workloads (audio data-loops, the coordinator) from the SDLC
fleet via a cpu.idle slice + an audio-core cpuset fence. These pins keep the
load-bearing directives from silently regressing.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
INSTALLER = REPO_ROOT / "systemd" / "scripts" / "install-units.sh"

# Logical cores carrying the SCHED_FIFO 88 audio data-loops (Ryzen 7700X: phys
# 6+7 with SMT siblings). No SDLC worker may ever land here.
AUDIO_CORES = {6, 7, 14, 15}
FLEET_FENCE = {0, 1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13}


def _directive(text: str, key: str) -> str | None:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip() == key:
            return v.strip()
    return None


def _parse_cpu_set(spec: str) -> set[int]:
    out: set[int] = set()
    for token in spec.replace(",", " ").split():
        if "-" in token:
            lo, hi = token.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(token))
    return out


# ── L1: the elastic yield slice ──────────────────────────────────────────────


def test_sdlc_slice_exists_and_is_idle_weighted() -> None:
    slice_file = UNITS_DIR / "hapax-sdlc.slice"
    assert slice_file.exists(), "hapax-sdlc.slice is the elastic baseline — must exist"
    text = slice_file.read_text()
    assert _directive(text, "CPUWeight") == "idle", "CPUWeight=idle → cpu.idle=1 (SCHED_IDLE)"


def test_sdlc_slice_fences_audio_cores() -> None:
    text = (UNITS_DIR / "hapax-sdlc.slice").read_text()
    allowed = _parse_cpu_set(_directive(text, "AllowedCPUs") or "")
    assert allowed == FLEET_FENCE
    assert not (allowed & AUDIO_CORES), "no pytest/cargo worker may land on the audio cores"


def test_sdlc_slice_throttles_memory_without_killing() -> None:
    text = (UNITS_DIR / "hapax-sdlc.slice").read_text()
    assert _directive(text, "MemoryHigh") == "48G", "MemoryHigh reclaim-throttles, never kills"
    # MemoryMax-as-throttle would SIGKILL a lane mid-work — that is degradation.
    assert _directive(text, "MemoryMax") is None, "MemoryMax must not be used as a throttle"
    assert _directive(text, "Delegate") == "yes"


def test_app_slice_has_aggregate_oom_backstop() -> None:
    text = (UNITS_DIR / "app.slice.d" / "oom-containment.conf").read_text()
    assert _directive(text, "MemoryHigh") == "80G"
    assert _directive(text, "MemoryMax") == "104G"
    assert _directive(text, "MemorySwapMax") == "8G"


def test_user_manager_does_not_protect_every_interactive_workload() -> None:
    text = (REPO_ROOT / "systemd" / "system" / "user@1000.service.d" / "oom.conf").read_text()
    assert _directive(text, "OOMScoreAdjust") == "100"


# ── L2: the audio-core cpuset fence ──────────────────────────────────────────


def test_compositor_excluded_from_audio_cores() -> None:
    conf = UNITS_DIR / "studio-compositor.service.d" / "cpu-affinity.conf"
    allowed = _parse_cpu_set(_directive(conf.read_text(), "CPUAffinity") or "")
    assert not (allowed & AUDIO_CORES)


def test_daimonion_cpu_side_fenced_off_audio_cores() -> None:
    conf = UNITS_DIR / "hapax-daimonion.service.d" / "cpu-affinity.conf"
    assert conf.exists(), "daimonion CPU-side work must be pinned off the audio data-loops"
    allowed = _parse_cpu_set(_directive(conf.read_text(), "CPUAffinity") or "")
    assert allowed, "CPUAffinity must be set"
    assert not (allowed & AUDIO_CORES), "daimonion vision/STT spikes must not preempt audio"


# ── Cross-cutting: the controller never starves while throttling the fleet ───


def test_coordinator_has_high_cpuweight() -> None:
    text = (UNITS_DIR / "hapax-coordinator.service").read_text()
    weight = _directive(text, "CPUWeight")
    assert weight is not None and weight.isdigit() and int(weight) >= 1000, (
        "the controller must out-weight the idle fleet it throttles"
    )


def test_coordinator_pinned_to_a_fleet_fenced_core() -> None:
    # The controller gets cores the SDLC fleet is fenced OUT of, so it never
    # starves while throttling the controlled (the exact death of 2026-06-01).
    text = (UNITS_DIR / "hapax-coordinator.service").read_text()
    allowed = _parse_cpu_set(_directive(text, "AllowedCPUs") or "")
    assert allowed, "coordinator must pin to a protected cpuset"
    assert not (allowed & FLEET_FENCE), "coordinator cores must be off the SDLC fleet's cpuset"


def test_coordinator_runs_from_source_activation_worktree() -> None:
    text = (UNITS_DIR / "hapax-coordinator.service").read_text()
    assert "WorkingDirectory=%h/.cache/hapax/source-activation/worktree" in text
    assert "ConditionPathExists=%h/.cache/hapax/source-activation/worktree/pyproject.toml" in text
    assert ".cache/hapax/rebuild/worktree" not in text


def test_coordinator_dispatcher_uses_source_activation_worktree() -> None:
    text = (UNITS_DIR / "hapax-coordinator.service").read_text()
    assert (
        "Environment=HAPAX_METHODOLOGY_DISPATCHER=%h/.cache/hapax/source-activation/"
        "worktree/scripts/hapax-methodology-dispatch"
    ) in text


# ── Deploy visibility: install-units.sh links the slice + drop-ins ───────────


def test_installer_links_slice_units() -> None:
    body = INSTALLER.read_text()
    assert '"$REPO_DIR"/*.slice' in body, "install-units.sh must symlink .slice units"


def test_installer_links_service_dropins() -> None:
    body = INSTALLER.read_text()
    assert '"$REPO_DIR"/*.service.d' in body
    assert '"$REPO_DIR"/*.slice.d' in body
