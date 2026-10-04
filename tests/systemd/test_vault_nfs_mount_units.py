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
# The user-manager vault writers that must skip cleanly when the vault is absent.
VAULT_WRITERS = (
    UNITS_DIR / "obsidian-sync.service",
    UNITS_DIR / "vault-context-writer.service",
    UNITS_DIR / "vault-git-snapshot.service",
)


def _directives(path: Path) -> list[str]:
    """Non-comment, non-blank directive lines — so assertions never match a unit's own prose
    (the conformance-greps-match-their-own-comments trap)."""
    return [
        line
        for raw in path.read_text().splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    ]


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


def test_mount_waits_for_network_online() -> None:
    """The backing .mount must wait for the network so it does not fire into an unreachable
    server at boot (#5021 defect 1)."""
    directives = _directives(MOUNT)
    assert "After=network-online.target" in directives, (
        ".mount must order After=network-online.target"
    )
    assert "Wants=network-online.target" in directives, ".mount must Wants=network-online.target"


def test_mount_does_not_latch_on_start_limit() -> None:
    """A transient network-down must retry on the next automount access, not latch failed past the
    start limit (the 2026-10-03 failure mode)."""
    assert "StartLimitIntervalSec=0" in _directives(MOUNT), (
        ".mount must set StartLimitIntervalSec=0 so a transient failure is not latched"
    )


def test_mount_alerts_on_failure() -> None:
    """A failed vault mount must never be silent."""
    assert any(line.startswith("OnFailure=") for line in _directives(MOUNT)), (
        ".mount must declare an OnFailure= alert handler"
    )


def test_mount_and_automount_have_timeouts() -> None:
    """The .mount bounds its own attempt (TimeoutSec) and the automount pins the mount once up
    (TimeoutIdleSec=0, so the hot vault is not auto-unmounted)."""
    assert any(line.startswith("TimeoutSec=") for line in _directives(MOUNT)), (
        ".mount must bound its attempt with TimeoutSec="
    )
    assert "TimeoutIdleSec=0" in _directives(AUTOMOUNT), (
        ".automount must pin the mount with TimeoutIdleSec=0"
    )


def test_vault_writers_skip_cleanly_when_vault_absent() -> None:
    """A USER-manager unit cannot order against the SYSTEM vault .mount, so RequiresMountsFor binds
    to nothing (#5021 re-round major 1). Each writer instead gates on an ExecCondition that probes
    the vault-root marker (.git / .obsidian — the defect-3 marker a shadow writer never creates), so
    it SKIPS cleanly (condition-not-met, not a failure) when the vault is unmounted/absent."""
    for unit in VAULT_WRITERS:
        directives = _directives(unit)
        assert not any(line.startswith("RequiresMountsFor=") for line in directives), (
            f"{unit.name}: RequiresMountsFor binds to nothing in the user manager — remove it"
        )
        conditions = [line for line in directives if line.startswith("ExecCondition=")]
        assert conditions, f"{unit.name}: must gate on an ExecCondition vault-marker probe"
        assert any(
            "Documents/Personal/.git" in line or "Documents/Personal/.obsidian" in line
            for line in conditions
        ), (
            f"{unit.name}: ExecCondition must probe the vault-root marker (.git/.obsidian): {conditions}"
        )


def test_no_unit_references_the_mutable_dev_tree() -> None:
    """Every unit this PR touches must run from the governed activation worktree, never the mutable
    dev tree ~/projects/hapax-council (canonical-root lens; raised by gemini and glm). Checked on
    DIRECTIVE lines so a unit's own explanatory comment naming the dev tree does not match."""
    pr_units = (MOUNT, AUTOMOUNT, *VAULT_WRITERS)
    for unit in pr_units:
        offenders = [line for line in _directives(unit) if "projects/hapax-council" in line]
        assert not offenders, (
            f"{unit.name}: directive references the mutable dev tree — use "
            f"%h/.cache/hapax/source-activation/worktree: {offenders}"
        )
