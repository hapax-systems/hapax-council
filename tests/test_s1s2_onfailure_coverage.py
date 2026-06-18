"""Coverage pin for cc-task audit-w4-observability-honesty-20260611.

Exit predicate of the task (audit v2, REPORT.md §observability): **every
S1/S2-constituent systemd unit versioned in this repo has ``OnFailure=``
or a declared probe exemption.** Before this task, ~40 S1/S2-constituent
unit files notified nobody on failure — the audit's universal
"watcher dies silently" class (W4-ONFAILURE-GAP).

The map below is FROZEN from the audit's ex-ante unit registry
(``subsystem-audit-2026-06-11-v2/unit-registry.yaml``, basis 2.1.0,
S1 = live path of segment execution, S2 = segment prep depends on it)
plus the W4 prep-packet gap sweep. Grouping keys are audit subsystem
``unit_id``s; values are the constituent repo unit files in
``systemd/units/``. Units the dossiers did not name explicitly are
attributed by registry ``scope_hint`` keywords and marked in comments.

Maintenance contract:
- Adding a new S1/S2-path unit file? Add it here in the same PR.
- A unit may only drop ``OnFailure=`` by gaining an entry in
  ``PROBE_EXEMPT`` naming the probe/reason — never silently.
- Deployed-only units (pipewire/wireplumber system-managed; litellm
  container) are out of scope: this pin covers repo-versioned files.

Freeze verifiability (review round 2, PR #4106): the ex-ante registry
lives in the operator vault (outside the repo), so the map itself is
the reviewable freeze. Known deliberate EXCLUSIONS, with rationale:
- pipewire/wireplumber: system-managed, no repo unit files.
- litellm/qdrant/prometheus: containers; failure visibility is the
  HapaxExporterDown rule, not systemd OnFailure.
- hapax-claude-lane@/hapax-quake-live-camera@ etc. template instances
  whose parent subsystems are S3 in the registry.
Units the registry plausibly implies that earlier drafts MISSED were
added in round 2 (hapax-darkplaces — the live Screwm render surface;
hapax-secrets — root of the secrets→logos-api→tabbyapi→daimonion key
chain; the hapax-screwm-* live-surface trio). If you believe a unit is
S1/S2-constituent and absent here, add it with a comment — the cost of
an extra OnFailure= line is one ntfy; the cost of a miss is a silent
death.

Pattern: tests/test_wgsl_node_affordance_coverage.py (regression pin).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UNITS_DIR = REPO_ROOT / "systemd" / "units"

ONFAILURE_RE = re.compile(r"^OnFailure=notify-failure@%n\.service\s*$", re.MULTILINE)

# Audit subsystem unit_id -> constituent repo unit files (S1/S2 only).
S1S2_CONSTITUENT_UNITS: dict[str, tuple[str, ...]] = {
    # S1 — voice pipeline & daimonion
    "voice-daimonion": (
        "hapax-daimonion.service",
        # The witness watchdog is itself the probe for daimonion liveness;
        # if the watcher dies silently the probe class collapses — it needs
        # OnFailure= like any other unit (audit "watcher dies" class).
        "hapax-voice-witness-watchdog.service",
    ),
    # S1 — audio routing, PipeWire topology & health
    "audio-routing-topology-health": (
        "hapax-audio-router.service",
        "hapax-audio-reconciler.service",
        "hapax-audio-ducker.service",
        "hapax-lufs-panic-cap.service",
        "hapax-audio-routing-check.service",
    ),
    # S1 — audio perception, prosody & grounding adapters
    "audio-perception-prosody-grounding": (
        "hapax-audio-grounding.service",
        "hapax-audio-self-perception.service",
    ),
    # S1 — studio compositor, director & broadcast chain
    "compositor-director-broadcast": (
        # The renderer itself — the live Screwm/DarkPlaces surface
        # (round-2 review gap: satellites were mapped, the core wasn't).
        "hapax-darkplaces.service",
        "hapax-darkplaces-v4l2.service",
        "hapax-darkplaces-obs-media-stream.service",
        # Round-3 review gaps: the /dev/video42 shmsrc writer + its
        # watchdog (same egress chain as the format guard), and the
        # already-protected chain members that were unmapped — an
        # unmapped unit is unpinned: a future PR could drop its
        # OnFailure= without any test going red.
        "hapax-v4l2-bridge.service",
        "hapax-v4l2-bridge-watchdog.service",
        "studio-compositor.service",
        "hapax-obs-livestream.service",
        "studio-fx-output.service",
        "hapax-broadcast-orchestrator.service",
        "hapax-live-surface-guard.service",
        "hapax-private-broadcast-echo-probe.service",
        "hapax-private-broadcast-leak-guard.service",
        # scope_hint-attributed: live-surface format/compat guards.
        "hapax-obs-video50-yuyv-compat-bridge.service",
        "hapax-video42-format-guard.service",
        # scope_hint-attributed: on-air overlay producers.
        "album-identifier.service",
        "weather-sync.service",
    ),
    # S1 — reverie, visual layer, GPU shaders & effect graph
    "reverie-visual-effects": (
        "hapax-reverie.service",
        "hapax-imagination.service",
        "hapax-imagination-watchdog.service",
        "visual-layer-aggregator.service",
        "hapax-screwm-drift-state-source.service",
        "hapax-darkplaces-bridge.service",
        # Live-surface screwm feeds (round-2 review gap).
        "hapax-screwm-audio-reactivity.service",
        "hapax-screwm-media-drift.service",
        "hapax-screwm-self-perception.service",
    ),
    # S1 — governance, consent & refusal
    "governance-consent-refusal": ("hapax-refusal-brief-rotate.service",),
    # S1 — logos runtime & reactive engine (round-3 review gap: logos-api
    # is the key-chain link the hapax-secrets rationale itself names —
    # it carried OnFailure= but nothing pinned it).
    "logos-runtime-reactive": ("logos-api.service",),
    # S1 — grounding inference substrate (repo-versioned part only;
    # litellm container config is deployed-only and out of scope).
    # hapax-secrets is the root of the documented key chain
    # (secrets → logos-api → tabbyapi → daimonion): its failure cascades,
    # but the cascade's OnFailure storms don't name the root cause — the
    # root unit must notify in its own name (round-2 review gap).
    "grounding-inference-substrate": (
        "tabbyapi.service",
        "hapax-secrets.service",
    ),
    # S2 — coordination & SDLC (dispatch, lanes, PR plumbing)
    "coordination-sdlc": (
        "hapax-coordinator.service",
        "hapax-coord.service",
        "hapax-coord-rebuild.service",
        "hapax-lane-idle-watchdog.service",
        "hapax-lane-reaper.service",
        "hapax-cc-cascade-unblock.service",
        "hapax-cc-hygiene.service",
        "hapax-cc-pr-autoqueue.service",
        "hapax-cc-pr-merge-watcher.service",
        "codex-claim-audit.service",  # exempt — see PROBE_EXEMPT
    ),
    # S2 — health & observability
    "health-observability": (
        "llm-cost-alert.service",
        "log-anomaly-alert.service",
        "hapax-quota-observability.service",
        "hapax-storage-pressure-check.service",
        "vram-watchdog.service",
    ),
}

# Units that intentionally do NOT carry OnFailure=, each with the probe or
# design reason that covers the failure path instead. An entry here is a
# reviewed decision, not a hole.
PROBE_EXEMPT: dict[str, str] = {
    # codex-claim-audit exits 1 BY DESIGN when it detects claim/lane issues
    # it could not auto-release, and posts its own ntfy alert in that path
    # (scripts/codex-claim-audit, detection branch). OnFailure= would
    # double-notify every detection. Its own silent death is covered by the
    # timer cadence + cc-hygiene dashboards, not unit failure state.
    "codex-claim-audit.service": "self-notifying by design (exit 1 = issues found + own ntfy)",
}


def _all_mapped_units() -> list[str]:
    return [u for units in S1S2_CONSTITUENT_UNITS.values() for u in units]


class TestFrozenMapIntegrity:
    def test_no_duplicate_entries(self) -> None:
        units = _all_mapped_units()
        dupes = {u for u in units if units.count(u) > 1}
        assert not dupes, f"unit files mapped to more than one subsystem: {sorted(dupes)}"

    def test_every_mapped_unit_file_exists(self) -> None:
        missing = [u for u in _all_mapped_units() if not (UNITS_DIR / u).is_file()]
        assert not missing, (
            f"S1/S2 frozen map names unit files absent from systemd/units/: "
            f"{missing}. Restore the file or update the map in the same PR "
            f"with the audit-registry rationale."
        )

    def test_exempt_units_are_in_the_map(self) -> None:
        mapped = set(_all_mapped_units())
        orphans = set(PROBE_EXEMPT) - mapped
        assert not orphans, f"PROBE_EXEMPT names units not in the frozen map: {sorted(orphans)}"

    def test_notify_failure_handler_exists(self) -> None:
        """The OnFailure target itself must be versioned, or every line
        added by this sweep points at nothing."""
        assert (UNITS_DIR / "notify-failure@.service").is_file()


class TestOnFailureCoverage:
    """The exit predicate, made mechanical."""

    def test_every_s1s2_unit_has_onfailure_or_declared_probe(self) -> None:
        gaps: list[str] = []
        for subsystem, units in S1S2_CONSTITUENT_UNITS.items():
            for unit in units:
                if unit in PROBE_EXEMPT:
                    continue
                path = UNITS_DIR / unit
                if not path.is_file():
                    continue  # existence asserted separately
                if not ONFAILURE_RE.search(path.read_text()):
                    gaps.append(f"{subsystem}/{unit}")
        assert not gaps, (
            f"S1/S2-constituent units missing OnFailure=notify-failure@%n.service "
            f"({len(gaps)}): {gaps}. Add the line to the [Unit] section, or add "
            f"a PROBE_EXEMPT entry naming the probe that covers the failure path."
        )

    def test_onfailure_lines_live_in_unit_section(self) -> None:
        """OnFailure= is a [Unit]-section directive; a line landed in
        [Service] is silently ignored by systemd — worse than absent."""
        misplaced: list[str] = []
        for unit in _all_mapped_units():
            path = UNITS_DIR / unit
            if not path.is_file():
                continue
            section = None
            for line in path.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    section = stripped
                elif stripped.startswith("OnFailure=") and section != "[Unit]":
                    misplaced.append(f"{unit} (in {section})")
        assert not misplaced, f"OnFailure= outside [Unit] section: {misplaced}"
