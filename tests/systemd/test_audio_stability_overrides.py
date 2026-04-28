"""Static install-path pins for audio-stability systemd drop-ins."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"
OVERRIDES_DIR = SYSTEMD_ROOT / "overrides" / "audio-stability"

DROPINS = {
    "pipewire.service.d/cpu-affinity.conf": "pipewire-cpu-affinity.conf",
    "wireplumber.service.d/cpu-affinity.conf": "wireplumber-cpu-affinity.conf",
    "pipewire-pulse.service.d/cpu-affinity.conf": "pipewire-pulse-cpu-affinity.conf",
    "studio-compositor.service.d/cpu-affinity.conf": "studio-compositor-cpu-affinity.conf",
}


def _without_comments(text: str) -> list[str]:
    return [
        line for line in text.splitlines() if not line.lstrip().startswith("#") and line.strip()
    ]


def test_audio_stability_dropins_are_install_visible() -> None:
    install_script = SYSTEMD_ROOT / "scripts" / "install-units.sh"
    body = install_script.read_text(encoding="utf-8")
    assert '"$REPO_DIR"/*.service.d' in body
    for relative_path in DROPINS:
        assert (UNITS_DIR / relative_path).exists(), (
            f"{relative_path} must live under systemd/units so install-units.sh links it"
        )


def test_audio_stability_deployable_dropins_match_documented_source() -> None:
    for relative_path, source_name in DROPINS.items():
        deployed = _without_comments((UNITS_DIR / relative_path).read_text(encoding="utf-8"))
        documented = _without_comments((OVERRIDES_DIR / source_name).read_text(encoding="utf-8"))
        assert deployed == documented
