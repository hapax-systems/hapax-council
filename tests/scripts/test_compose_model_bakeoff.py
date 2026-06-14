"""Behavioral pins for the compose-model bakeoff (scripts/compose-model-bakeoff.py).

The bakeoff's empirical scores are inherently non-deterministic (live stochastic
model calls), so the headline numbers cannot be a CI fixture. But its DECISION
LOGIC must be: the gate must mirror the live coherence gate (incl. the
critical-axis floor), cloud composers must be opt-in (fail-closed egress), and the
chat payload must route to the right endpoint.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compose-model-bakeoff.py"
_spec = importlib.util.spec_from_file_location("compose_model_bakeoff", SCRIPT)
assert _spec and _spec.loader
bake = importlib.util.module_from_spec(_spec)
sys.modules["compose_model_bakeoff"] = bake  # so @dataclass can resolve __module__
_spec.loader.exec_module(bake)


def _result(scores: dict[str, int], conv: str = "converged") -> object:
    composer = bake.Composer("x", "tabby", "m", "n")
    valid = [v for v in scores.values() if v is not None]
    mean = (sum(valid) / len(valid)) if valid else None
    return bake.BakeoffResult(composer=composer, mean_score=mean, scores=scores, convergence=conv)


def test_clears_gate_requires_mean_at_least_3() -> None:
    assert _result({"a": 4, "b": 4}).clears_gate is True
    assert _result({"a": 2, "b": 3}).clears_gate is False  # mean 2.5 < 3


def test_clears_gate_enforces_critical_axis_floor() -> None:
    # mean 3.75 but one axis at the floor (1) — the live gate rejects this, so the
    # bakeoff must too, or it would report a model as clearing that the runtime drops.
    r = _result({"opening_pressure": 5, "argumentative_specificity": 5, "payoff_resolution": 1})
    assert r.mean_score is not None and r.mean_score >= 3.0
    assert r.clears_gate is False


def test_clears_gate_false_when_refused_or_unscored() -> None:
    assert _result({"a": 5}, conv="refused").clears_gate is False
    assert _result({}).clears_gate is False


def test_cloud_composers_off_by_default() -> None:
    # The default composer set is local-only; cloud egress is opt-in.
    assert all(c.endpoint == "tabby" for c in bake.LOCAL_COMPOSERS)
    assert all(c.endpoint == "litellm" for c in bake.CLOUD_COMPOSERS)
    assert {c.label for c in bake.CLOUD_COMPOSERS} == {"opus", "gemini-3-pro"}


def test_chat_routes_local_to_tabby_without_auth(monkeypatch) -> None:
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            import json

            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    def _fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["headers"] = req.headers
        return _Resp()

    monkeypatch.setattr(bake.urllib.request, "urlopen", _fake_urlopen)
    out = bake._chat(bake.LOCAL_COMPOSERS[0])
    assert out == "ok"
    assert captured["url"] == bake.TABBY_CHAT_URL
    # no bearer auth on the local tabby path
    assert not any(k.lower() == "authorization" for k in captured["headers"])
