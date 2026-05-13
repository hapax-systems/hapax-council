from __future__ import annotations

from shared.memory_pressure import (
    BYTES_PER_GIB,
    MemoryPressureClass,
    SystemdMemoryProperties,
    classify_cgroup_memory_events,
    classify_critical_floor_risk,
    classify_global_ram_pressure,
    classify_live_swappiness,
    classify_swap_zram_saturation,
    memory_threshold,
    parse_cgroup_memory_events,
    parse_meminfo,
    parse_proc_swaps,
    parse_systemd_memory_properties,
    parse_zram_mm_stat,
)
from shared.resource_model import DEFAULT_SERVICE_PROFILES, ResourceState


def test_global_ram_pressure_uses_resource_model_thresholds() -> None:
    signal = classify_global_ram_pressure(
        {
            "MemTotal": 128 * BYTES_PER_GIB,
            "MemAvailable": 10 * BYTES_PER_GIB,
        }
    )

    assert signal.pressure_class == MemoryPressureClass.GLOBAL_RAM_PRESSURE
    assert signal.state == ResourceState.RED
    assert signal.threshold_signal == "mem_available_gb"
    assert signal.raw["threshold"]["signal"] == memory_threshold("mem_available_gb").signal


def test_zram_saturation_is_separate_from_global_ram_pressure() -> None:
    devices = parse_proc_swaps(
        "\n".join(
            [
                "Filename Type Size Used Priority",
                "/dev/zram0 partition 33554432 33030144 100",
                "/samples/swapfile file 33554432 0 5",
            ]
        )
    )

    signal = classify_swap_zram_saturation(devices)

    assert signal.pressure_class == MemoryPressureClass.ZRAM_SATURATION
    assert signal.state == ResourceState.RED
    assert signal.threshold_signal == "zram_used_pct"
    assert signal.raw["scope"] == "zram"
    assert signal.raw["devices"][0]["is_zram"] is True


def test_live_swappiness_drift_uses_injected_reader() -> None:
    signal = classify_live_swappiness(lambda: "150\n", expected_value=10)

    assert signal.pressure_class == MemoryPressureClass.SYSCTL_DRIFT
    assert signal.state == ResourceState.RED
    assert signal.raw == {"live_value": 150, "expected_value": 10, "drift": 140}


def test_service_cgroup_oom_events_are_representable_without_journal() -> None:
    events = parse_cgroup_memory_events("low 0\nhigh 2\nmax 3\noom 4\noom_kill 1\n")

    signal = classify_cgroup_memory_events("stimmung-sync.service", events)

    assert signal.pressure_class == MemoryPressureClass.SERVICE_CGROUP_OOM
    assert signal.state == ResourceState.RED
    assert signal.raw["events"]["oom_kill"] == 1


def test_critical_floor_risk_represents_stale_ceiling_against_profile() -> None:
    profile = DEFAULT_SERVICE_PROFILES["hapax-daimonion"]
    properties = SystemdMemoryProperties(
        service_name="hapax-daimonion.service",
        memory_max_bytes=8 * BYTES_PER_GIB,
        oom_score_adjust=0,
    )

    signal = classify_critical_floor_risk(
        "hapax-daimonion",
        properties,
        profile=profile,
    )

    assert signal.pressure_class == MemoryPressureClass.CRITICAL_FLOOR_RISK
    assert signal.state == ResourceState.RED
    assert "memory_max_below_profile_limit" in signal.raw["reasons"]
    assert "oom_score_less_protected_than_profile" in signal.raw["reasons"]


def test_parsers_preserve_raw_memory_evidence() -> None:
    meminfo = parse_meminfo("MemTotal: 131072000 kB\nMemAvailable: 68157440 kB\n")
    zram = parse_zram_mm_stat("1024 512 2048 0 4096 3 4 5 6\n")
    props = parse_systemd_memory_properties(
        "MemoryMax=512M\nMemoryHigh=infinity\nOOMScoreAdjust=-500\n",
        service_name="stimmung-sync.service",
    )

    assert meminfo["MemTotal"] == 131072000 * 1024
    assert zram.mem_used_total == 2048
    assert zram.raw_values == [1024, 512, 2048, 0, 4096, 3, 4, 5, 6]
    assert props.memory_max_bytes == 512 * 1024 * 1024
    assert props.memory_high_bytes is None
    assert props.oom_score_adjust == -500
