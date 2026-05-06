from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_SYSTEMD = REPO_ROOT / "config" / "systemd"
UNITS = REPO_ROOT / "systemd" / "units"
COMMAND_R_MODEL = "command-r-08-2024-exl3-5.0bpw"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_segment_prep_units_are_deploy_visible_only() -> None:
    assert (UNITS / "hapax-segment-prep.service").is_file()
    assert (UNITS / "hapax-segment-prep.timer").is_file()
    assert not (CONFIG_SYSTEMD / "hapax-segment-prep.service").exists()
    assert not (CONFIG_SYSTEMD / "hapax-segment-prep.timer").exists()


def test_segment_prep_service_checks_resident_command_r_without_loading_models() -> None:
    body = _read(UNITS / "hapax-segment-prep.service")

    assert f"Environment=HAPAX_SEGMENT_PREP_MODEL={COMMAND_R_MODEL}" in body
    assert "ExecStartPre=%h/.local/bin/uv run python -m shared.resident_command_r --check" in body
    assert (
        "ExecStart=%h/.local/bin/uv run python -m agents.hapax_daimonion.daily_segment_prep" in body
    )
    assert "tabbyapi.service" in body
    assert "WantedBy=default.target" not in body

    forbidden = [
        "/v1/model/load",
        "/v1/model/unload",
        "Qwen",
        "enable_thinking",
        "HAPAX_LITELLM_URL",
        "systemctl --user restart",
        "systemctl --user stop",
        "docker pause",
        "pkill",
        "fuser",
    ]
    for token in forbidden:
        assert token not in body


def test_segment_prep_timer_pairs_with_checked_service() -> None:
    body = _read(UNITS / "hapax-segment-prep.timer")

    assert "Unit=hapax-segment-prep.service" in body
    assert "WantedBy=timers.target" in body
    assert "Qwen" not in body


def test_active_content_prep_runtime_surfaces_have_no_swap_hazards() -> None:
    paths = [
        REPO_ROOT / "agents" / "hapax_daimonion" / "daily_segment_prep.py",
        REPO_ROOT / "agents" / "programme_manager" / "planner.py",
        REPO_ROOT / "scripts" / "batch_prep_segments.sh",
        REPO_ROOT / "shared" / "resident_command_r.py",
        UNITS / "hapax-segment-prep.service",
        UNITS / "hapax-segment-prep.timer",
        UNITS / "tabbyapi.service",
        UNITS / "tabbyapi.service.d" / "gpu-pin.conf",
    ]
    forbidden = [
        "/v1/model/load",
        "/v1/model/unload",
        "Qwen",
        "enable_thinking",
        "HAPAX_LITELLM_URL",
        "docker pause",
        "systemctl --user stop hapax-daimonion",
        "pkill",
        "fuser",
    ]

    for path in paths:
        body = _read(path)
        for token in forbidden:
            assert token not in body, f"{token!r} found in {path.relative_to(REPO_ROOT)}"
