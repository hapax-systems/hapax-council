"""The vault NFS mount/automount units enable the RIGHT unit (#5021, defect 1/2).

Only the ``.automount`` is ever enabled: it is installed into ``remote-fs.target`` and pulls the
backing ``.mount`` ON DEMAND (the backing mount waits for network-online, so a boot-time access
blocks instead of failing into an unreachable server). The ``.mount`` must therefore carry NO
``[Install]`` section: an install target on it lets ``systemctl enable`` fire the mount directly at
boot via ``remote-fs.target``, bypassing the on-demand automount and re-creating the boot race this
task fixes (claude-1 major on PR #5021).
"""

from __future__ import annotations

from pathlib import Path

UNITS_DIR = Path(__file__).resolve().parents[2] / "systemd" / "units"
MOUNT = UNITS_DIR / "home-hapax-Documents-Personal.mount"
AUTOMOUNT = UNITS_DIR / "home-hapax-Documents-Personal.automount"


def test_mount_has_no_install_target() -> None:
    """The backing .mount is pulled on demand by the .automount — it is never enabled itself.

    Checked against SECTION HEADER / DIRECTIVE lines, not the raw text: the unit's own comment
    says "[Install]" in prose, and a text-anywhere check would match that comment rather than a
    real section (the conformance-greps-match-their-own-comments trap)."""
    non_comment = [
        line
        for raw in MOUNT.read_text().splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    ]
    assert "[Install]" not in non_comment, (
        "home-hapax-Documents-Personal.mount must have NO [Install] section: only the .automount "
        "is enabled; an install target lets the mount fire at boot via remote-fs.target, "
        "bypassing the on-demand automount and re-creating the boot race (#5021 defect 1)."
    )
    assert not [line for line in non_comment if line.startswith("WantedBy=")], (
        "the .mount must not declare a WantedBy install directive"
    )


def test_automount_is_the_enabled_unit() -> None:
    """Positive control: the .automount IS installable (it is the unit that gets enabled)."""
    text = AUTOMOUNT.read_text()
    assert "[Install]" in text and "WantedBy=remote-fs.target" in text, (
        "the .automount is the enabled unit and must install into remote-fs.target"
    )


def test_automount_does_not_order_after_network_online() -> None:
    """The automount point is established early (local-fs); ordering it after network-online forms
    the local-fs -> automount -> network-online -> sysinit -> local-fs cycle. The network wait
    lives on the .mount, which is what actually touches NFS (#5021 defect 1 companion).

    Assert the ORDERING DIRECTIVES, not the raw string: the explanatory comment names
    network-online.target too, and a text-anywhere check would match the comment, not a real
    dependency (the conformance-greps-match-their-own-comments trap).
    """
    ordering = [
        line.strip()
        for raw in AUTOMOUNT.read_text().splitlines()
        if (line := raw.strip())
        and not line.startswith("#")
        and line.startswith(("After=", "Wants=", "Requires=", "BindsTo=", "Requisite="))
        and "network-online.target" in line
    ]
    assert not ordering, (
        f"the .automount must not order after network-online.target (ordering cycle); the network "
        f"wait belongs on the .mount. Offending directives: {ordering}"
    )
