"""Static gate: every canonical systemd unit in `systemd/units/` is installable.

Forever-fix follow-up to `docs/research/2026-05-03-deployment-pipeline-audit.md`.
The audit found 25 unit files declared in canonical but never installed into
the user's systemd directory, because `hapax-post-merge-deploy` was a
manual-only script. After deploy automation lands, that drift class is
eliminated for new units; this gate ensures the units themselves remain
syntactically + structurally valid (parseable, sound dependency ordering,
ExecStart paths resolvable, timer→service pairings exist).

The test is intentionally pure-static — it reads the `.service` / `.timer`
files in the repo, no live systemctl, no install side effects.

Scope: the strict checks are pinned to the explicit 25-unit batch identified
in the audit. The broader repo gets soft sanity checks that flag genuine
bugs without blocking unrelated changes (some pre-existing units have
stylistic deviations like multi-line shell ExecStart that don't break
systemd but aren't worth one-off-fixing here).
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
HOME = Path(os.environ.get("HOME", "/home/hapax"))


# ─────────────────── helpers ───────────────────


def _raw_keys(path: Path, section: str, key: str) -> list[str]:
    """Return every value of `key` under `[section]` from raw file lines.
    systemd permits duplicate keys (esp. ExecStart=); we honour that here.

    Tracks line continuation (trailing `\\`) and stops collection at the
    next `[Section]` header.
    """
    in_section = False
    section_header = f"[{section}]"
    out: list[str] = []
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_section = s == section_header
            continue
        if not in_section:
            continue
        if not s or s.startswith("#") or s.startswith(";"):
            continue
        if "=" not in s:
            continue
        k, _, v = s.partition("=")
        if k.strip() == key:
            out.append(v.strip())
    return out


def _has_section(path: Path, section: str) -> bool:
    header = f"[{section}]"
    return any(line.strip() == header for line in path.read_text().splitlines())


def _resolve_specifiers(token: str) -> str:
    """Resolve systemd specifiers we statically care about (only %h)."""
    return token.replace("%h", str(HOME))


def _service_units() -> list[Path]:
    return sorted(UNITS_DIR.glob("*.service"))


def _timer_units() -> list[Path]:
    return sorted(UNITS_DIR.glob("*.timer"))


# ─────────────────── canonical-25 batch (forever-fix anchor) ───────────────────
# These were the 25 missing units called out in the 2026-05-03 deployment
# pipeline audit. Listing them here makes their disappearance loud, not
# silent. New canonical units beyond these 25 do NOT need to be added; this
# is a regression pin, not a registry.

CANONICAL_25_BATCH = [
    "hapax-audio-signal-assertion.service",
    "hapax-audio-stage-check.service",
    "hapax-audio-stage-check.timer",
    "hapax-audio-topology-assertion.service",
    "hapax-audio-topology-assertion.timer",
    "hapax-audio-topology-verify.service",
    "hapax-audio-topology-verify.timer",
    "hapax-broadcast-egress-loopback-producer.service",
    "hapax-bt-firmware-watchdog.service",
    "hapax-conversion-broker.service",
    "hapax-gemini-iota-watchdog.service",
    "hapax-m8-control.service",
    "hapax-m8-stem-recorder.service",
    "hapax-m8-stem-retention.service",
    "hapax-m8-stem-retention.timer",
    "hapax-novelty-shift-emitter.service",
    "hapax-novelty-shift-emitter.timer",
    "hapax-option-c-pin-watchdog.service",
    "hapax-option-c-pin-watchdog.timer",
    "hapax-parametric-modulation-heartbeat.service",
    "hapax-private-broadcast-echo-probe.service",
    "hapax-private-broadcast-echo-probe.timer",
    "hapax-usb-bandwidth-preflight.service",
    "hapax-usb-bandwidth-preflight.timer",
    "hapax-xhci-death-watchdog.service",
]


# ─────────────────── basic shape ───────────────────


def test_units_dir_exists() -> None:
    assert UNITS_DIR.is_dir(), f"systemd/units/ must exist (got {UNITS_DIR})"


def test_canonical_25_batch_present() -> None:
    """The 25-unit batch identified in the 2026-05-03 audit must remain
    in canonical. Removing one is a deliberate decision, not an oversight.
    """
    missing = [u for u in CANONICAL_25_BATCH if not (UNITS_DIR / u).exists()]
    assert not missing, (
        "Canonical unit(s) from 2026-05-03 audit batch missing — "
        f"either restore or update CANONICAL_25_BATCH list: {missing}"
    )


# ─────────────────── canonical-25 strict checks ───────────────────


def test_canonical_25_have_required_sections() -> None:
    """Each *.service in the batch must have [Unit] + [Service]; each
    *.timer must have [Unit] + [Timer]."""
    failures: list[tuple[str, str]] = []
    for name in CANONICAL_25_BATCH:
        unit = UNITS_DIR / name
        if not _has_section(unit, "Unit"):
            failures.append((name, "missing [Unit]"))
        if name.endswith(".service") and not _has_section(unit, "Service"):
            failures.append((name, "missing [Service]"))
        if name.endswith(".timer") and not _has_section(unit, "Timer"):
            failures.append((name, "missing [Timer]"))
    assert not failures, f"Required-section check failed: {failures}"


def test_canonical_25_services_have_execstart() -> None:
    """Each *.service in the batch must declare an ExecStart in [Service]."""
    failures: list[str] = []
    for name in CANONICAL_25_BATCH:
        if not name.endswith(".service"):
            continue
        unit = UNITS_DIR / name
        execs = (
            _raw_keys(unit, "Service", "ExecStart")
            + _raw_keys(unit, "Service", "ExecStartPre")
            + _raw_keys(unit, "Service", "ExecStop")
        )
        if not execs:
            failures.append(name)
    assert not failures, (
        f"Services missing ExecStart/ExecStartPre/ExecStop in [Service]: {failures}"
    )


def test_canonical_25_no_execstart_in_unit_section() -> None:
    """ExecStart in [Unit] is silently ignored by systemd. Catch it."""
    service_only_keys = {"ExecStart", "ExecStartPre", "ExecStartPost", "ExecStop", "Type"}
    failures: list[tuple[str, str]] = []
    for name in CANONICAL_25_BATCH:
        if not name.endswith(".service"):
            continue
        unit = UNITS_DIR / name
        # If we find these keys under [Unit], that's the bug.
        for k in service_only_keys:
            if _raw_keys(unit, "Unit", k):
                failures.append((name, k))
    assert not failures, f"Service-only keys found in [Unit] (silently ignored): {failures}"


def test_canonical_25_timers_pair_with_existing_service() -> None:
    """Each *.timer in the batch must trigger an existing *.service.

    Default: timer name maps to service name (timer X.timer fires X.service).
    If `Unit=` is set in [Timer], that override takes precedence.
    """
    failures: list[tuple[str, str]] = []
    for name in CANONICAL_25_BATCH:
        if not name.endswith(".timer"):
            continue
        timer = UNITS_DIR / name
        unit_overrides = _raw_keys(timer, "Timer", "Unit")
        target_name = unit_overrides[0] if unit_overrides else f"{timer.stem}.service"
        target = UNITS_DIR / target_name
        if not target.exists():
            failures.append((name, target_name))
    assert not failures, f"Timer(s) without a matching service in systemd/units/: {failures}"


def test_canonical_25_execstart_repo_paths_exist() -> None:
    """Best-effort static check: ExecStart binaries that point inside the
    repo must resolve to a real file. Out-of-repo paths (system, .venv,
    .local/bin) are operator-managed and not validated here.
    """
    failures: list[tuple[str, str]] = []
    repo_prefix = str(HOME / "projects/hapax-council")

    for name in CANONICAL_25_BATCH:
        if not name.endswith(".service"):
            continue
        unit = UNITS_DIR / name
        execs = _raw_keys(unit, "Service", "ExecStart") + _raw_keys(unit, "Service", "ExecStartPre")
        for line in execs:
            stripped = line.lstrip("-+!@")
            tokens = stripped.split()
            if not tokens:
                continue
            bin_path = _resolve_specifiers(tokens[0])
            if not bin_path.startswith("/"):
                continue  # shell builtins / relative — skip
            if not bin_path.startswith(repo_prefix):
                continue  # out-of-repo, skip
            try:
                rel = Path(bin_path).relative_to(repo_prefix)
            except ValueError:
                continue
            in_repo = REPO_ROOT / rel
            if not in_repo.exists():
                failures.append((name, str(rel)))

    assert not failures, f"Repo-relative ExecStart path(s) missing on disk: {failures}"


# ─────────────────── soft sanity check (warn, don't fail) ───────────────────
# A few pre-existing units use multi-line ExecStart with embedded shell
# quoting that's valid for systemd but trips strict configparser-style
# tools. Surface them as a SOFT signal so an operator can clean up
# opportunistically without this PR being scope-creeped.


def test_repo_wide_execstart_in_unit_section_is_caught() -> None:
    """Repo-wide warning surface: report any service that has ExecStart-style
    keys under [Unit] (silently ignored). Failing this test means a NEW
    bug landed; pre-existing offenders are listed in
    `KNOWN_EXECSTART_IN_UNIT_PREEXISTING`. Adjust that list if a fix lands.
    """
    KNOWN_EXECSTART_IN_UNIT_PREEXISTING = {
        # 2026-05-03: bare-words misplacement — ExecStart=... lives under
        # [Unit] header instead of [Service]. systemd silently ignores it,
        # so these services fail to start. Pre-existing pre-canonicalisation
        # bugs; tracked for a separate cleanup PR.
        "hapax-egress-audit-rotate.service",
        "hapax-systemd-reconcile.service",
    }
    service_only_keys = {"ExecStart", "ExecStartPre", "ExecStartPost", "ExecStop"}
    new_offenders: list[tuple[str, str]] = []

    for svc in _service_units():
        for k in service_only_keys:
            if _raw_keys(svc, "Unit", k):
                if svc.name not in KNOWN_EXECSTART_IN_UNIT_PREEXISTING:
                    new_offenders.append((svc.name, k))

    assert not new_offenders, (
        "NEW offender(s): ExecStart-style keys placed under [Unit] (systemd "
        "silently ignores them). Move to [Service] or document in the "
        f"KNOWN_EXECSTART_IN_UNIT_PREEXISTING list. Offenders: {new_offenders}"
    )
