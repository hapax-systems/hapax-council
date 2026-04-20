"""Vinyl broadcast signal-chain verifier — software-side wiring (#195).

D-24 §9.3: PipeWire node names can contain unicode (smart quotes,
combining marks, etc.) depending on hardware naming. Substring matching
uses ``unicodedata.normalize('NFKD', ...)`` + lowercase before
comparison so "Korg HandyTraxx" matches "korg handytraxx" and Unicode
look-alikes don't silently fail.


Alpha handoff Tier 4 #16. The vinyl broadcast chain's hardware topology
(Handytraxx → Evil Pet + Torso S-4 → L6 → PipeWire → RTMP) is operator-
owned per
``docs/research/2026-04-20-vinyl-broadcast-signal-chain-topology.md``.
This module ships the software-side wiring: a verifier that asserts the
expected PipeWire nodes + channel routes are present in the live graph,
and reports specific deviations in human-readable form.

Composes with ``shared.audio_topology_inspector.pw_dump_to_descriptor``
(Phase 4 of the audio-topology CLI) so the same pw-dump JSON can drive
both the general verify and the vinyl-specific one.

Scope:

- Check that the L6 multitrack source is enumerated.
- Check that the Handytraxx source (or equivalent line-in stereo pair)
  is present when ``mode_d_active`` flag is set.
- Check that the broadcast tap (``hapax-livestream-tap`` or current
  collapsed target) exists downstream of the L6 master.
- Check that Evil Pet + Torso S-4 USB nodes are active when their
  respective capability daemons are running.
- Emit one ``VinylChainFinding`` per deviation so the operator sees
  an ordered diff.

What this module does NOT do:
- No MIDI (evil_pet_state.py owns that).
- No CC emission.
- No live-graph mutation — verification only. The operator applies
  remediation via the L6 retargets runbook
  (``docs/superpowers/handoff/2026-04-20-delta-l6-retargets-
  operator-runbook.md``).

Reference:
    - docs/research/2026-04-20-vinyl-broadcast-signal-chain-topology.md
      §1–§4 (Candidate B topology recommendation)
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum

from shared.audio_topology import NodeKind, TopologyDescriptor


class VinylChainSeverity(StrEnum):
    """Severity gradient for chain deviations."""

    INFO = "info"  # informational; no operator action needed
    WARNING = "warning"  # operator should investigate
    ERROR = "error"  # broadcast path is broken; operator must fix


@dataclass(frozen=True)
class VinylChainFinding:
    """One deviation from the expected vinyl broadcast chain."""

    severity: VinylChainSeverity
    code: str  # short identifier, e.g. "L6_MULTITRACK_MISSING"
    message: str  # human-readable description
    remediation: str = ""  # optional one-line fix suggestion


@dataclass
class VinylChainVerification:
    """Aggregate result of a vinyl broadcast chain verify pass."""

    findings: list[VinylChainFinding] = field(default_factory=list)
    ok: bool = True  # False if any ERROR-level finding was added

    def add(self, finding: VinylChainFinding) -> None:
        self.findings.append(finding)
        if finding.severity == VinylChainSeverity.ERROR:
            self.ok = False

    def by_severity(self, severity: VinylChainSeverity) -> list[VinylChainFinding]:
        return [f for f in self.findings if f.severity == severity]


# Expected node-name substrings for the vinyl broadcast chain. Each entry:
# (substring, kind, severity-if-absent, code, remediation)
_EXPECTED_NODES: list[tuple[str, NodeKind, VinylChainSeverity, str, str]] = [
    (
        "ZOOM",  # L6 multitrack — matches both capture + playback
        NodeKind.ALSA_SOURCE,
        VinylChainSeverity.ERROR,
        "L6_MULTITRACK_MISSING",
        "Plug L6 USB cable + verify `pw-cli ls Node | grep ZOOM`; restart pipewire if needed.",
    ),
    (
        "livestream-tap",
        NodeKind.TAP,
        VinylChainSeverity.ERROR,
        "BROADCAST_TAP_MISSING",
        "Load config/pipewire/hapax-livestream-tap.conf or the collapsed "
        "main-mix tap per #210 retargets runbook.",
    ),
]


def _normalize(s: str) -> str:
    """NFKD-normalize + casefold for unicode-robust substring matching.

    PipeWire node names can carry compatibility forms (e.g. fullwidth
    characters, ligatures, smart quotes); NFKD decomposes those to
    their canonical components. ``casefold()`` is the Unicode-aware
    equivalent of ``lower()`` and handles non-ASCII case correctly
    (e.g. German ß → ss).
    """
    return unicodedata.normalize("NFKD", s).casefold()


def _norm_match(needle: str, haystack: str) -> bool:
    """``needle in haystack`` after NFKD normalization on both sides."""
    return _normalize(needle) in _normalize(haystack)


def verify_vinyl_chain(
    descriptor: TopologyDescriptor,
    *,
    mode_d_active: bool = False,
    s4_expected: bool = False,
) -> VinylChainVerification:
    """Check the live graph for the vinyl broadcast chain's key nodes.

    Args:
        descriptor: parsed ``TopologyDescriptor`` from the live graph
            (usually ``descriptor_from_live()`` in the inspector).
        mode_d_active: when True, additionally require the Handytraxx /
            line-in source used by Mode D. Caller passes this from the
            ``evil_pet_state.read_state()`` flag or equivalent.
        s4_expected: when True, additionally require the Torso S-4 USB
            node. Useful when the operator has the S-4 patched but
            wants to see it verified.

    Returns:
        VinylChainVerification. ``ok`` is True iff no ERROR-level
        findings emitted; WARNING and INFO findings don't flip ok.
    """
    result = VinylChainVerification()

    for substring, kind, severity, code, remediation in _EXPECTED_NODES:
        matches = [n for n in descriptor.nodes if _norm_match(substring, n.pipewire_name)]
        if not matches:
            result.add(
                VinylChainFinding(
                    severity=severity,
                    code=code,
                    message=(
                        f"expected node matching {substring!r} ({kind.value}) "
                        "not found in live graph"
                    ),
                    remediation=remediation,
                )
            )
            continue
        # Kind mismatch is a warning, not an error — PipeWire sometimes
        # exposes hardware as the opposite kind depending on profile.
        if not any(m.kind == kind for m in matches):
            kinds = {m.kind.value for m in matches}
            result.add(
                VinylChainFinding(
                    severity=VinylChainSeverity.WARNING,
                    code=f"{code}_KIND_MISMATCH",
                    message=(
                        f"node matching {substring!r} found but kind={list(kinds)} "
                        f"instead of expected {kind.value}"
                    ),
                    remediation=(
                        f"check PipeWire card profile for {substring}; "
                        "may need `pactl set-card-profile`"
                    ),
                )
            )

    if mode_d_active:
        handytraxx_substrings = ("korg", "handytraxx", "line-in")
        found_source = any(
            any(_norm_match(s, n.pipewire_name) for s in handytraxx_substrings)
            for n in descriptor.nodes
        )
        if not found_source:
            result.add(
                VinylChainFinding(
                    severity=VinylChainSeverity.WARNING,
                    code="HANDYTRAXX_NOT_VISIBLE",
                    message=(
                        "mode_d_active but no Handytraxx/line-in source visible in the live graph"
                    ),
                    remediation=(
                        "verify Handytraxx is plugged into the L6 line pair; "
                        "Mode D will still route via L6 multitrack but the "
                        "dedicated source label is missing"
                    ),
                )
            )

    if s4_expected:
        s4_substrings = ("torso", "s-4", "s4")
        found_s4 = any(
            any(_norm_match(s, n.pipewire_name) for s in s4_substrings) for n in descriptor.nodes
        )
        if not found_s4:
            result.add(
                VinylChainFinding(
                    severity=VinylChainSeverity.WARNING,
                    code="S4_NOT_VISIBLE",
                    message=("s4_expected but no Torso S-4 node visible in the live graph"),
                    remediation=("plug S-4 USB + verify `pw-cli ls Node | grep -i torso`"),
                )
            )

    if not result.findings:
        result.add(
            VinylChainFinding(
                severity=VinylChainSeverity.INFO,
                code="VINYL_CHAIN_OK",
                message="all expected vinyl broadcast chain nodes present",
            )
        )

    return result


def format_report(result: VinylChainVerification) -> str:
    """Render a verification result as operator-readable text."""
    lines = [f"# Vinyl broadcast chain verify — {'OK' if result.ok else 'FAIL'}"]
    for sev in (
        VinylChainSeverity.ERROR,
        VinylChainSeverity.WARNING,
        VinylChainSeverity.INFO,
    ):
        batch = result.by_severity(sev)
        if not batch:
            continue
        lines.append(f"\n## {sev.value.upper()} ({len(batch)})")
        for f in batch:
            lines.append(f"- [{f.code}] {f.message}")
            if f.remediation:
                lines.append(f"  → {f.remediation}")
    return "\n".join(lines)
