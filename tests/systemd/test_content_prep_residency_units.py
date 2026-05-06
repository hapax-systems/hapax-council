from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SEGMENT_PREP_SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-segment-prep.service"
SEGMENT_PREP_TIMER = REPO_ROOT / "systemd" / "units" / "hapax-segment-prep.timer"
INSTALL_UNITS = REPO_ROOT / "systemd" / "scripts" / "install-units.sh"
PREP_SCRIPT = REPO_ROOT / "scripts" / "batch_prep_segments.sh"
DAILY_PREP = REPO_ROOT / "agents" / "hapax_daimonion" / "daily_segment_prep.py"

RESIDENT_COMMAND_R = "command-r-08-2024-exl3-5.0bpw"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_segment_prep_units_live_only_in_canonical_systemd_units() -> None:
    assert SEGMENT_PREP_SERVICE.exists()
    assert SEGMENT_PREP_TIMER.exists()
    assert not (REPO_ROOT / "config" / "systemd" / "hapax-segment-prep.service").exists()
    assert not (REPO_ROOT / "config" / "systemd" / "hapax-segment-prep.timer").exists()


def test_segment_prep_unit_requires_resident_command_r() -> None:
    service = _read(SEGMENT_PREP_SERVICE)
    timer = _read(SEGMENT_PREP_TIMER)

    assert f"Environment=HAPAX_SEGMENT_PREP_MODEL={RESIDENT_COMMAND_R}" in service
    assert "shared.resident_command_r --check" in service
    assert "agents.hapax_daimonion.daily_segment_prep" in service
    assert "Unit=hapax-segment-prep.service" in timer


def test_active_content_prep_paths_have_no_qwen_or_model_swap_calls() -> None:
    scanned = {
        PREP_SCRIPT: _read(PREP_SCRIPT),
        DAILY_PREP: _read(DAILY_PREP),
        SEGMENT_PREP_SERVICE: _read(SEGMENT_PREP_SERVICE),
        SEGMENT_PREP_TIMER: _read(SEGMENT_PREP_TIMER),
    }
    forbidden = (
        "qwen",
        "/v1/model/load",
        "/v1/model/unload",
        "model/load",
        "model/unload",
        "enable_thinking",
        "chat_template_kwargs",
        "systemctl --user restart tabbyapi",
        "systemctl --user stop tabbyapi",
        "systemctl --user start tabbyapi",
    )

    for path, body in scanned.items():
        lowered = body.lower()
        for token in forbidden:
            assert token not in lowered, f"{path} contains retired prep token {token!r}"


def test_legacy_break_prep_units_are_decommissioned() -> None:
    body = _read(INSTALL_UNITS)

    assert "hapax-break-prep.service" in body
    assert "hapax-break-prep.timer" in body
    assert not (REPO_ROOT / "systemd" / "units" / "hapax-break-prep.service").exists()
    assert not (REPO_ROOT / "systemd" / "units" / "hapax-break-prep.timer").exists()
