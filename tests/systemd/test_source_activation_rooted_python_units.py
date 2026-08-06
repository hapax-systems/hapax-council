"""Deploy-rooting regression pin + forward guard for python systemd units.

Root cause (2026-06-07): live services that set
``WorkingDirectory=%h/projects/hapax-council`` run from the operator's CANONICAL
interactive worktree — a feature branch behind main with local edits — so they
execute STALE code. ``hapax-segment-prep.service`` crashed daily on a removed
``CouncilConfig(max_models=…)`` signature for exactly this reason. The correct
pattern (``hapax-daimonion.service``) runs from the main-tracking
source-activation deploy tree via its own ``.venv``.

This module:

1. Pins every unit migrated by the deploy-hardening task to the
   source-activation deploy tree (positive regression pin).
2. Forward-guards the class: NO new unit may root a ``python -m agents.*`` /
   ``python -m shared.*`` ExecStart at the canonical worktree unless it is an
   explicitly documented exception (see
   ``docs/research/2026-06-07-canonical-rooted-unit-audit.md``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
ACTIVATION = "%h/.cache/hapax/source-activation/worktree"
CANON_FORMS = ("%h/projects/hapax-council", "/home/hapax/projects/hapax-council")
EXEC_KEYS = ("ExecCondition=", "ExecStartPre=", "ExecStart=", "ExecStartPost=", "ExecStop=")
PY_MODULE = re.compile(r"python3?\s+-m\s+(agents[\w.]*|shared[\w.]*)")

# ── units migrated to source-activation by this task (positive pins) ──
MIGRATED_UNITS = (
    "hapax-segment-prep.service",
    "vault-context-writer.service",
    "health-connect-parse.service",
    "hapax-information-density.service",
    "hapax-impingement-sampler.service",
    "hapax-inflection-bridge.service",
    "hapax-quota-observability.service",
    "hapax-conversion-broker.service",
    "hapax-cred-watch.service",
    "hapax-sprint-tracker.service",
    "hapax-relay-to-cc-tasks.service",
    "hapax-refused-lifecycle-conditional.service",
    "hapax-refused-lifecycle-constitutional.service",
    "hapax-refused-lifecycle-structural.service",
    "hapax-refusal-brief-rotate.service",
    "hapax-dataset-card-generator.service",
    "hapax-mail-monitor-fallback.service",
    "hapax-mail-monitor-watch-renewal.service",
    "hapax-mail-monitor-weekly-digest.service",
    "hapax-kdeconnect-bridge.service",
    "hapax-chronicle-quality-exporter.service",
    "hapax-self-federate-rss.service",
    "hapax-omg-weblog-composer.service",
    "hapax-assets-publisher.service",
    "hapax-datacite-graph-publish.service",
    "hapax-datacite-mirror.service",
    "hapax-datacite-snapshot.service",
    "hapax-orcid-verifier.service",
    "hapax-publish-orchestrator.service",
    "hapax-live-cuepoints.service",
)

# ── canonical-rooted python -m units intentionally NOT yet migrated. Each is
# justified in docs/research/2026-06-07-canonical-rooted-unit-audit.md. This is
# an upper-bound allow-list: migrating one later (so it leaves the canonical
# set) keeps this test green; adding a NEW canonical-rooted python unit, or
# regressing a migrated unit, does not. ──
KNOWN_CANONICAL_EXCEPTIONS = frozenset(
    {
        # audio / live-egress / broadcast / compositor / vision / video
        "audio-processor.service",
        "av-correlator.service",
        "hapax-audio-ab-recorder.service",
        "hapax-audio-ducker.service",
        "hapax-audio-perception.service",
        "hapax-audio-router.service",
        "hapax-audio-safety.service",
        "hapax-audio-signal-assertion.service",
        "hapax-broadcast-audio-health-producer.service",
        "hapax-broadcast-audio-health.service",
        "hapax-broadcast-egress-loopback-producer.service",
        "hapax-channel-trailer.service",
        "hapax-feedback-loop-detector.service",
        "hapax-lufs-panic-cap.service",
        "hapax-overlay-producer.service",
        "hapax-pipewire-graph-shadow.service",
        "hapax-rode-wireless-adapter.service",
        "hapax-steamdeck-monitor.service",
        "hapax-video-cam@.service",
        "hapax-vision-observer.service",
        "studio-person-detector.service",
        "video-processor.service",
        "visual-layer-aggregator.service",
        # external-platform-coupled
        "hapax-soundcloud-sync.service",
        "hapax-streamdeck-adapter.service",
        "hapax-thumbnail-rotator.service",
        "hapax-youtube-chat-reader.service",
        "hapax-youtube-telemetry.service",
        "youtube-sync.service",
        # dedicated ingest venv (.venv-ingest) not provisioned by source-activate
        "hapax-vault-bulk-rescan.service",
        "rag-ingest.service",
        # provider-billing-sensitive
        "hapax-money-rails.service",
        # special unit shape (device-conditioned, contract-tested separately)
        "hapax-m8-control.service",
        # uv->direct conversion batch 2 (non-sensitive uv-run units)
        "chrome-sync.service",
        "claude-code-sync.service",
        "deliberation-eval.service",
        "dev-story-index.service",
        "flow-journal.service",
        "gcalendar-sync.service",
        "gdrive-sync.service",
        "git-sync.service",
        "gmail-sync.service",
        "hapax-content-candidate-discovery.service",
        "hapax-content-resolver.service",
        "hapax-dmn.service",
        "hapax-imagination-loop.service",
        "hapax-omg-lol-fanout.service",
        "hapax-operator-awareness.service",
        "hapax-reverie-monitor.service",
        "hapax-vault-coherence.service",
        "hapax-weekly-review.service",
        "langfuse-sync.service",
        "manifest-snapshot.service",
        "obsidian-sync.service",
        "policy-decide-promote.service",
        "profile-update.service",
        "screen-context.service",
        "stimmung-sync.service",
        "storage-arbiter.service",
        "weather-sync.service",
    }
)


def _section_values(text: str, section: str, key: str) -> list[str]:
    in_section = False
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_section = s == f"[{section}]"
            continue
        if not in_section or not s or s.startswith(("#", ";")) or "=" not in s:
            continue
        k, _, v = s.partition("=")
        if k.strip() == key:
            out.append(v.strip())
    return out


def _exec_lines(text: str) -> list[str]:
    out: list[str] = []
    for key in ("ExecCondition", "ExecStartPre", "ExecStart", "ExecStartPost", "ExecStop"):
        out.extend(_section_values(text, "Service", key))
    return out


def _is_canonical(value: str) -> bool:
    return any(value == c or value.startswith(c + "/") for c in CANON_FORMS)


def _rooting_lines(text: str) -> list[str]:
    """Lines whose rooting must be source-activation (exec + WD + PYTHONPATH + PATH)."""
    lines: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith(
            EXEC_KEYS + ("WorkingDirectory=", "Environment=PYTHONPATH=", "Environment=PATH=")
        ):
            lines.append(s)
    return lines


def _canonical_rooted_python_units() -> set[str]:
    """Units whose WorkingDirectory is canonical (or an exec line references the
    canonical worktree) AND which run ``python -m agents.*``/``shared.*`` —
    i.e. the class that silently executes stale code."""
    found: set[str] = set()
    for unit in sorted(UNITS_DIR.glob("*.service")):
        text = unit.read_text(encoding="utf-8")
        execs = _exec_lines(text)
        if not any(PY_MODULE.search(e) for e in execs):
            continue
        wd = _section_values(text, "Service", "WorkingDirectory")
        wd_canon = bool(wd) and _is_canonical(wd[0])
        exec_canon = any(any(c in e for c in CANON_FORMS) for e in execs)
        if wd_canon or exec_canon:
            found.add(unit.name)
    return found


# ─────────────────── positive pins ───────────────────


def test_segment_prep_runs_from_source_activation_like_daimonion() -> None:
    """The flagship: segment-prep must mirror hapax-daimonion.service rooting,
    including the fail-closed source-freshness guard before the resident gate."""
    text = (UNITS_DIR / "hapax-segment-prep.service").read_text(encoding="utf-8")

    assert f"WorkingDirectory={ACTIVATION}" in text
    assert f"Environment=PYTHONPATH={ACTIVATION}" in text
    assert (
        f"ExecStart={ACTIVATION}/.venv/bin/python -m agents.hapax_daimonion.daily_segment_prep"
        in text
    )
    assert f"ExecCondition={ACTIVATION}/.venv/bin/python -m shared.segment_prep_pause" in text
    assert (
        f"ExecStartPre={ACTIVATION}/.venv/bin/python -m shared.resident_command_r --check" in text
    )
    # fail-closed source-freshness guard (mirrors hapax-daimonion.service)
    assert (
        f"ExecStartPre={ACTIVATION}/scripts/hapax-compositor-runtime-source-check "
        "--require-file agents/hapax_daimonion/daily_segment_prep.py" in text
    )
    # no residue of the canonical interactive worktree in any rooting line, and
    # no `uv run` (which re-syncs / runs from CWD) in any exec line
    for line in _rooting_lines(text):
        assert not any(c in line for c in CANON_FORMS), f"canonical residue: {line}"
    for line in _exec_lines(text):
        assert "uv run" not in line, f"exec line still uses uv run: {line}"


@pytest.mark.parametrize("unit_name", MIGRATED_UNITS)
def test_migrated_unit_is_source_activation_rooted(unit_name: str) -> None:
    text = (UNITS_DIR / unit_name).read_text(encoding="utf-8")

    # WorkingDirectory + PYTHONPATH both point at the deploy tree
    assert _section_values(text, "Service", "WorkingDirectory") == [ACTIVATION], (
        f"{unit_name} WorkingDirectory must be the source-activation deploy tree"
    )
    assert f"Environment=PYTHONPATH={ACTIVATION}" in text, (
        f"{unit_name} must export PYTHONPATH={ACTIVATION}"
    )
    # the python that runs the module is the deploy tree's own venv
    execs = _exec_lines(text)
    module_execs = [e for e in execs if PY_MODULE.search(e)]
    assert module_execs, f"{unit_name} has no python -m exec line"
    for e in module_execs:
        assert e.startswith(f"{ACTIVATION}/.venv/bin/python -m "), (
            f"{unit_name} python -m exec must run the deploy-tree venv: {e}"
        )
    # zero canonical residue in any rooting line
    for line in _rooting_lines(text):
        assert not any(c in line for c in CANON_FORMS), (
            f"{unit_name} retains canonical worktree reference: {line}"
        )


# ─────────────────── forward guard ───────────────────


def test_no_unexpected_canonical_rooted_python_units() -> None:
    """No NEW unit may root a python -m agents/shared ExecStart at the canonical
    interactive worktree, and no migrated unit may regress to it. Either run
    from the source-activation deploy tree, or add the unit to
    KNOWN_CANONICAL_EXCEPTIONS with a justification in the audit doc."""
    found = _canonical_rooted_python_units()
    unexpected = sorted(found - KNOWN_CANONICAL_EXCEPTIONS)
    assert not unexpected, (
        "Unit(s) root a `python -m agents.*`/`shared.*` ExecStart at the "
        "canonical interactive worktree (runs STALE code). Migrate to "
        f"{ACTIVATION} (see hapax-daimonion.service) or document in "
        "docs/research/2026-06-07-canonical-rooted-unit-audit.md and add to "
        f"KNOWN_CANONICAL_EXCEPTIONS: {unexpected}"
    )
    # migrated units must NOT be in the canonical set (regression tripwire)
    regressed = sorted(set(MIGRATED_UNITS) & found)
    assert not regressed, f"migrated unit(s) regressed to canonical rooting: {regressed}"


def test_known_canonical_exceptions_all_exist() -> None:
    """Keep the allow-list honest: a renamed/removed unit must be pruned."""
    missing = sorted(n for n in KNOWN_CANONICAL_EXCEPTIONS if not (UNITS_DIR / n).exists())
    assert not missing, f"KNOWN_CANONICAL_EXCEPTIONS lists nonexistent unit(s): {missing}"
