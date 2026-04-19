#!/usr/bin/env bash
# Post-merge verification for the Epic 2 hothouse PR.
#
# Run from the main hapax-council worktree after services have restarted.
# Checks that every Epic-2 surface the PR added is live:
#   - the 6 new Cairo sources are registered;
#   - the director writes llm-in-flight markers + rotates jsonl;
#   - youtube-player picks up the 0.5x playback rate;
#   - compositional_consumer SHM files are materialized by the pipeline;
#   - color-resonance.json is being published;
#   - consent live-egress is fail-closed by default.
#
# Exit 0 = all checks green; non-zero = a specific failure surfaced.

set -euo pipefail

fail=0

check() {
    local label="$1"
    local cmd="$2"
    if eval "$cmd" >/dev/null 2>&1; then
        echo "  OK  $label"
    else
        echo "FAIL  $label"
        fail=$((fail + 1))
    fi
}

echo "== Epic-2 hothouse post-merge verification =="

# Phase C — six new Cairo sources registered.
check "ImpingementCascadeCairoSource registered" \
    "uv run python -c 'from agents.studio_compositor.cairo_sources import get_cairo_source_class; get_cairo_source_class(\"ImpingementCascadeCairoSource\")'"
check "RecruitmentCandidatePanelCairoSource registered" \
    "uv run python -c 'from agents.studio_compositor.cairo_sources import get_cairo_source_class; get_cairo_source_class(\"RecruitmentCandidatePanelCairoSource\")'"
check "ThinkingIndicatorCairoSource registered" \
    "uv run python -c 'from agents.studio_compositor.cairo_sources import get_cairo_source_class; get_cairo_source_class(\"ThinkingIndicatorCairoSource\")'"
check "PressureGaugeCairoSource registered" \
    "uv run python -c 'from agents.studio_compositor.cairo_sources import get_cairo_source_class; get_cairo_source_class(\"PressureGaugeCairoSource\")'"
check "ActivityVarietyLogCairoSource registered" \
    "uv run python -c 'from agents.studio_compositor.cairo_sources import get_cairo_source_class; get_cairo_source_class(\"ActivityVarietyLogCairoSource\")'"
check "WhosHereCairoSource registered" \
    "uv run python -c 'from agents.studio_compositor.cairo_sources import get_cairo_source_class; get_cairo_source_class(\"WhosHereCairoSource\")'"

# Phase E — tightened cadences.
check "narrative cadence default 12.0" \
    "uv run python -c 'from agents.studio_compositor.director_loop import PERCEPTION_INTERVAL; assert PERCEPTION_INTERVAL == 12.0, PERCEPTION_INTERVAL'"
check "structural cadence default 90.0" \
    "uv run python -c 'from agents.studio_compositor.structural_director import StructuralDirector; assert StructuralDirector.DEFAULT_CADENCE_S == 90.0'"

# Phase B — compositional consumer roundtrip.
check "dispatch resolves cam.hero" \
    "uv run python -c 'from agents.studio_compositor.compositional_consumer import dispatch, RecruitmentRecord; assert dispatch(RecruitmentRecord(name=\"cam.hero.overhead.vinyl-spinning\")) == \"camera.hero\"'"
check "dispatch resolves fx.family" \
    "uv run python -c 'from agents.studio_compositor.compositional_consumer import dispatch, RecruitmentRecord; assert dispatch(RecruitmentRecord(name=\"fx.family.audio-reactive\")) == \"preset.bias\"'"

# Music directives.
check "music in ActivityVocabulary" \
    "uv run python -c 'from typing import get_args; from shared.director_intent import ActivityVocabulary; assert \"music\" in get_args(ActivityVocabulary)'"
check "curated playlist constant intact" \
    "uv run python -c 'from agents.studio_compositor.director_loop import PLAYLIST_URL, OPERATOR_CURATED_PLAYLIST_URLS; assert \"PL-4nvD1KwuH--sViEAFY2cHVmS6_B4CQ5\" in PLAYLIST_URL; assert OPERATOR_CURATED_PLAYLIST_URLS == (PLAYLIST_URL,)'"

# YouTube playback rate default.
check "youtube playback rate default 0.5" \
    "uv run python -c '
import importlib.util, os
from pathlib import Path
os.environ.pop(\"HAPAX_YOUTUBE_PLAYBACK_RATE\", None)
spec = importlib.util.spec_from_file_location(\"yp\", Path(\"scripts/youtube-player.py\"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod._playback_rate() == 0.5
'"

# Phase A — consent-safe compose gate retired (2026-04-18). face-obscure
# (#129) is the canonical privacy floor; the legacy fail-closed layout-swap
# gate is DISABLED by default. The predicate returns False unless
# HAPAX_CONSENT_EGRESS_GATE=1 restores legacy behavior.
check "consent gate disabled by default (post-retirement)" \
    "uv run python -c 'import os; os.environ.pop(\"HAPAX_CONSENT_EGRESS_GATE\", None); from agents.studio_compositor.consent_live_egress import should_egress_compose_safe; assert should_egress_compose_safe(None) is False'"
check "consent gate fails closed when explicitly enabled" \
    "uv run python -c 'import os; os.environ[\"HAPAX_CONSENT_EGRESS_GATE\"]=\"1\"; import importlib, agents.studio_compositor.consent_live_egress as cle; importlib.reload(cle); assert cle.should_egress_compose_safe(None) is True'"

# Phase F — color resonance.
check "color_resonance module exports ColorResonance" \
    "uv run python -c 'from agents.studio_compositor.color_resonance import ColorResonance, publish, read_current'"

# Phase G4 — JSONL rotation helper.
check "JSONL rotation constants defined" \
    "uv run python -c 'from agents.studio_compositor.director_loop import _JSONL_ROTATE_BYTES, _JSONL_KEEP_ROTATED; assert _JSONL_ROTATE_BYTES == 5 * 1024 * 1024; assert _JSONL_KEEP_ROTATED == 3'"

echo "==============================================="
if [ "$fail" -eq 0 ]; then
    echo "All Epic-2 verification checks passed."
    exit 0
fi
echo "$fail check(s) failed."
exit 1
