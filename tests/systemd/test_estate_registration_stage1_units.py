"""Stage 1 estate-registration units: what merge is and is not allowed to do."""

from pathlib import Path


def test_stage1_timers_are_parked_so_merge_does_not_activate_them() -> None:
    """Four review families, 2026-09-04: the post-merge deploy runs `enable --now` on every
    unmarked new timer, so an unparked Stage 1 timer activates on merge — the stage gate the
    whole PR exists to respect. Activation is a deliberate step after merge, never a side effect
    of it."""
    units = Path(__file__).resolve().parents[2] / "systemd" / "units"
    for name in (
        "hapax-estate-canary.timer",
        "hapax-estate-canary-peer-check.timer",
        "hapax-estate-drift-sweep.timer",
    ):
        text = (units / name).read_text(encoding="utf-8")
        assert "# Hapax-Parked: true" in text, f"{name} would activate on merge"


#: Sandboxing options that make a USER-manager unit run inside a user namespace (systemd.exec(5):
#: without privileges to mount, the user manager implies PrivateUsers= for them). Inside that
#: namespace root-owned files map to `nobody`, and ssh refuses its own configuration
#: ("Bad owner or permissions on /etc/ssh/ssh_config.d/…"). Measured 2026-09-26T23:56Z: a
#: transient `PrivateTmp=true` user unit sees the ssh config target as `nobody:nobody 644`, and the
#: first scheduled check-peer failed with exit 255 for exactly that reason.
_USER_NAMESPACE_OPTIONS = (
    "PrivateTmp",
    "PrivateUsers",
    "PrivateDevices",
    "PrivateNetwork",
    "PrivateIPC",
    "PrivateMounts",
    "ProtectSystem",
    "ProtectHome",
    "ProtectKernelTunables",
    "ProtectKernelModules",
    "ProtectKernelLogs",
    "ProtectControlGroups",
    "ProtectClock",
    "ProtectHostname",
)
_FALSE_VALUES = {"false", "no", "off", "0"}


def _enabled_options(text: str) -> set[str]:
    enabled: set[str] = set()
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in _USER_NAMESPACE_OPTIONS:
            if value.strip().lower() not in _FALSE_VALUES:
                enabled.add(key.strip())
    return enabled


def test_ssh_running_estate_units_declare_no_user_namespace_sandboxing() -> None:
    """The peer-facing units run `check-peer` or `sweep-peer`, and both reach the peer over ssh. A
    user-namespace sandbox makes ssh reject its config, so these units could never run."""
    units = Path(__file__).resolve().parents[2] / "systemd" / "units"
    ssh_units = [
        path
        for path in sorted(units.glob("hapax-estate-*.service"))
        if any(
            command in path.read_text(encoding="utf-8") for command in ("check-peer", "sweep-peer")
        )
    ]
    assert {path.name for path in ssh_units} == {
        "hapax-estate-canary-peer-check.service",
        "hapax-estate-drift-sweep.service",
    }, "the set of ssh-running estate units changed; review this pin"
    for path in ssh_units:
        text = path.read_text(encoding="utf-8")
        assert not _enabled_options(text), (path.name, sorted(_enabled_options(text)))
        assert "NoNewPrivileges=true" in text, f"{path.name} must keep NoNewPrivileges"


def test_user_namespace_option_detector_is_not_vacuous() -> None:
    """The detector itself: each option counts when enabled, and only an explicit false clears it."""
    for option in _USER_NAMESPACE_OPTIONS:
        assert _enabled_options(f"[Service]\n{option}=true\n") == {option}
        assert _enabled_options(f"[Service]\n{option}=read-only\n") == {option}
        assert _enabled_options(f"[Service]\n{option}=no\n") == set()
    assert _enabled_options("[Service]\nNoNewPrivileges=true\n") == set()
