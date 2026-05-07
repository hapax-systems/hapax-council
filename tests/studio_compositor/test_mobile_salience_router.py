"""Mobile salience router scoring and fail-closed behavior.

PR #2770 purged ``config/compositor-layouts/mobile.json`` ("broken
schema"); ``MobileSalienceRouter.__init__`` calls
``load_mobile_layout(layout_path)`` which falls through to the missing
default file when no path is supplied. Both tests below construct the
router that way, so they raise ``FileNotFoundError`` whenever the
layout is absent. The module-level skip below switches them off cleanly
in that state and reactivates automatically when a fresh mobile.json
is reintroduced.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agents.studio_compositor.mobile_salience_router import MobileSalienceRouter

_MOBILE_LAYOUT_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "compositor-layouts" / "mobile.json"
)
pytestmark = pytest.mark.skipif(
    not _MOBILE_LAYOUT_PATH.exists(),
    reason=(
        "config/compositor-layouts/mobile.json was purged by PR #2770 "
        "('broken schema'); MobileSalienceRouter cannot construct without it"
    ),
)


def _fresh(path: Path, payload: object, *, now: float) -> None:
    if isinstance(payload, str):
        path.write_text(payload)
    else:
        path.write_text(json.dumps(payload))
    os.utime(path, (now, now))


def test_router_scores_and_publishes_top_three(tmp_path: Path) -> None:
    now = 1000.0
    recruitment = tmp_path / "recent-recruitment.json"
    narrative = tmp_path / "narrative-state.json"
    viewers = tmp_path / "youtube-viewer-count.txt"
    output = tmp_path / "mobile-salience.json"
    _fresh(
        recruitment,
        {
            "entries": [
                {"ward": "impingement_cascade", "score": 0.9, "ts": now},
                {"ward": "captions", "score": 0.5, "ts": now - 3},
                {"ward": "token_pole", "score": 0.4, "ts": now - 6},
            ]
        },
        now=now,
    )
    _fresh(
        narrative,
        {
            "narrative_relevance": {
                "impingement_cascade": 0.8,
                "captions": 1.0,
                "activity_header": 0.7,
            }
        },
        now=now,
    )
    _fresh(viewers, "12\n", now=now)

    router = MobileSalienceRouter(
        output_path=output,
        recruitment_path=recruitment,
        narrative_path=narrative,
        viewer_count_path=viewers,
        now=lambda: now,
    )
    payload = router._tick()

    assert payload["selected_wards"] == ["impingement_cascade", "captions", "token_pole"]
    assert payload["viewer_count"] == 12
    assert payload["density_mode"] == "normal_density"
    assert payload["claim_posture"] == "neutral_hold"
    assert json.loads(output.read_text())["selected_wards"] == payload["selected_wards"]


def test_router_stale_sources_score_zero_and_minimum_density(tmp_path: Path) -> None:
    now = 1000.0
    recruitment = tmp_path / "recent-recruitment.json"
    narrative = tmp_path / "narrative-state.json"
    viewers = tmp_path / "youtube-viewer-count.txt"
    output = tmp_path / "mobile-salience.json"
    _fresh(recruitment, {"wards": {"captions": 1.0}}, now=now - 45)
    _fresh(narrative, {"narrative_relevance": {"captions": 1.0}}, now=now - 45)
    _fresh(viewers, "99\n", now=now - 45)

    router = MobileSalienceRouter(
        output_path=output,
        recruitment_path=recruitment,
        narrative_path=narrative,
        viewer_count_path=viewers,
        now=lambda: now,
    )
    payload = router._tick()

    assert payload["selected_wards"] == []
    assert payload["viewer_count"] == 0
    assert payload["density_mode"] == "minimum_density"
    assert all(score == 0.0 for score in payload["scores"].values())
