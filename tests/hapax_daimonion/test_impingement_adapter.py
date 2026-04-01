"""Tests for CPAL impingement adapter."""

from unittest.mock import MagicMock

from agents.hapax_daimonion.cpal.impingement_adapter import ImpingementAdapter, ImpingementEffect


def _make_impingement(
    source="imagination", strength=0.5, metric="", narrative="", interrupt_token=None
):
    imp = MagicMock()
    imp.source = source
    imp.strength = strength
    imp.content = {"metric": metric, "narrative": narrative}
    imp.interrupt_token = interrupt_token
    return imp


class TestImpingementAdapter:
    def test_imagination_gentle_gain(self):
        adapter = ImpingementAdapter()
        imp = _make_impingement(source="imagination", strength=0.5, narrative="interesting thought")
        effect = adapter.adapt(imp)
        assert effect.gain_update is not None
        assert effect.gain_update.delta < 0.1  # gentle
        assert not effect.should_surface  # strength < 0.7

    def test_critical_stimmung_high_gain(self):
        adapter = ImpingementAdapter()
        imp = _make_impingement(source="stimmung", strength=0.9, metric="stimmung_critical")
        effect = adapter.adapt(imp)
        assert effect.gain_update is not None
        assert effect.gain_update.delta > 0.2  # forceful
        assert effect.should_surface  # critical always surfaces

    def test_high_strength_surfaces(self):
        adapter = ImpingementAdapter()
        imp = _make_impingement(source="imagination", strength=0.8, narrative="urgent thought")
        effect = adapter.adapt(imp)
        assert effect.should_surface

    def test_low_strength_no_surface(self):
        adapter = ImpingementAdapter()
        imp = _make_impingement(source="imagination", strength=0.3)
        effect = adapter.adapt(imp)
        assert not effect.should_surface

    def test_operator_distress_max_priority(self):
        adapter = ImpingementAdapter()
        imp = _make_impingement(source="sensor", strength=0.6, interrupt_token="operator_distress")
        effect = adapter.adapt(imp)
        assert effect.gain_update is not None
        assert effect.gain_update.delta > 0.2
        assert effect.should_surface

    def test_error_boost_scales_with_strength(self):
        adapter = ImpingementAdapter()
        low = adapter.adapt(_make_impingement(strength=0.2))
        high = adapter.adapt(_make_impingement(strength=0.8))
        assert low.error_boost == 0.0  # below 0.3 threshold
        assert high.error_boost > 0.0

    def test_narrative_from_content(self):
        adapter = ImpingementAdapter()
        imp = _make_impingement(narrative="the system needs attention")
        effect = adapter.adapt(imp)
        assert effect.narrative == "the system needs attention"

    def test_narrative_fallback_to_metric(self):
        adapter = ImpingementAdapter()
        imp = _make_impingement(metric="cpu_high", narrative="")
        effect = adapter.adapt(imp)
        assert effect.narrative == "cpu_high"

    def test_effect_is_frozen(self):
        effect = ImpingementEffect(
            gain_update=None, error_boost=0.0, should_surface=False, narrative="test"
        )
        try:
            effect.error_boost = 0.5
            raise AssertionError("Should be frozen")
        except (AttributeError, TypeError):
            pass

    def test_very_low_gain_produces_no_update(self):
        adapter = ImpingementAdapter()
        imp = _make_impingement(source="unknown_source", strength=0.01)
        effect = adapter.adapt(imp)
        assert effect.gain_update is None  # below 0.01 threshold
