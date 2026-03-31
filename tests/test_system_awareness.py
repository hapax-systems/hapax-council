"""tests/test_system_awareness.py — SystemAwarenessCapability unit tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

from agents.hapax_daimonion.system_awareness import SystemAwarenessCapability
from shared.impingement import Impingement, ImpingementType


def _make_degradation_imp(
    source: str = "dmn.ollama_degraded",
    strength: float = 0.7,
) -> Impingement:
    return Impingement(
        timestamp=time.time(),
        source=source,
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=strength,
        content={"metric": "ollama_degraded", "consecutive_failures": 5},
    )


class TestSystemAwareness:
    def test_blocks_when_nominal(self, tmp_path: Path) -> None:
        stimmung_path = tmp_path / "state.json"
        stimmung_path.write_text(json.dumps({"overall_stance": "nominal"}))
        cap = SystemAwarenessCapability(stimmung_path=stimmung_path)
        assert cap.can_resolve(_make_degradation_imp()) == 0.0

    def test_blocks_when_cautious(self, tmp_path: Path) -> None:
        stimmung_path = tmp_path / "state.json"
        stimmung_path.write_text(json.dumps({"overall_stance": "cautious"}))
        cap = SystemAwarenessCapability(stimmung_path=stimmung_path)
        assert cap.can_resolve(_make_degradation_imp()) == 0.0

    def test_allows_when_degraded(self, tmp_path: Path) -> None:
        stimmung_path = tmp_path / "state.json"
        stimmung_path.write_text(json.dumps({"overall_stance": "degraded"}))
        cap = SystemAwarenessCapability(stimmung_path=stimmung_path)
        imp = _make_degradation_imp(strength=0.8)
        assert cap.can_resolve(imp) == 0.8

    def test_allows_when_critical(self, tmp_path: Path) -> None:
        stimmung_path = tmp_path / "state.json"
        stimmung_path.write_text(json.dumps({"overall_stance": "critical"}))
        cap = SystemAwarenessCapability(stimmung_path=stimmung_path)
        assert cap.can_resolve(_make_degradation_imp()) > 0.0

    def test_cooldown_suppresses(self, tmp_path: Path) -> None:
        stimmung_path = tmp_path / "state.json"
        stimmung_path.write_text(json.dumps({"overall_stance": "degraded"}))
        cap = SystemAwarenessCapability(stimmung_path=stimmung_path, cooldown_s=300.0)
        imp = _make_degradation_imp()
        assert cap.can_resolve(imp) > 0.0
        cap.activate(imp, 0.7)
        assert cap.can_resolve(_make_degradation_imp()) == 0.0

    def test_cooldown_expires(self, tmp_path: Path) -> None:
        stimmung_path = tmp_path / "state.json"
        stimmung_path.write_text(json.dumps({"overall_stance": "degraded"}))
        cap = SystemAwarenessCapability(stimmung_path=stimmung_path, cooldown_s=300.0)
        cap.activate(_make_degradation_imp(), 0.7)
        cap._last_activation = time.monotonic() - 301.0
        assert cap.can_resolve(_make_degradation_imp()) > 0.0

    def test_activate_queues_impingement(self, tmp_path: Path) -> None:
        stimmung_path = tmp_path / "state.json"
        stimmung_path.write_text(json.dumps({"overall_stance": "degraded"}))
        cap = SystemAwarenessCapability(stimmung_path=stimmung_path)
        imp = _make_degradation_imp()
        cap.activate(imp, 0.7)
        assert cap.has_pending()
        consumed = cap.consume_pending()
        assert consumed is not None
        assert consumed.source == "dmn.ollama_degraded"
        assert not cap.has_pending()

    def test_missing_stimmung_blocks(self, tmp_path: Path) -> None:
        cap = SystemAwarenessCapability(stimmung_path=tmp_path / "nope.json")
        assert cap.can_resolve(_make_degradation_imp()) == 0.0
