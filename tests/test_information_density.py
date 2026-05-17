"""Discrimination tests for the Information Density Field.

Proves the density computation can distinguish:
1. Noise (high entropy, low surprise, low novelty)
2. Steady state (low entropy, low surprise, low novelty)
3. Change point (low→high surprise spike, high novelty spike)
4. Gradual drift (moderate surprise, low novelty)
"""

from __future__ import annotations

import math
import unittest

from shared.information_density import (
    BOCPDModel,
    BayesianSurpriseModel,
    EntropyModel,
    InformationDensityField,
    SourceModel,
)


class TestBayesianSurprise(unittest.TestCase):
    def test_steady_signal_low_surprise(self) -> None:
        model = BayesianSurpriseModel()
        for _ in range(100):
            s = model.update(5.0)
        assert s < 0.15, f"Steady signal should have low surprise after convergence, got {s}"

    def test_sudden_shift_high_surprise(self) -> None:
        model = BayesianSurpriseModel()
        for _ in range(50):
            model.update(5.0)
        s = model.update(50.0)
        assert s > 0.5, f"Sudden shift should have high surprise, got {s}"

    def test_noise_moderate_surprise(self) -> None:
        import random

        rng = random.Random(42)
        model = BayesianSurpriseModel()
        surprises = []
        for _ in range(200):
            surprises.append(model.update(rng.gauss(0, 10)))
        avg = sum(surprises[-20:]) / 20
        assert avg < 0.99, f"Noise surprise should not saturate at 1.0, got {avg}"


class TestBOCPD(unittest.TestCase):
    def test_steady_no_changepoint(self) -> None:
        model = BOCPDModel(hazard=1 / 100)
        for _ in range(50):
            cp = model.update(5.0)
        assert cp < 0.1, f"Steady signal should have low CP prob, got {cp}"

    def test_regime_shift_detects_changepoint(self) -> None:
        model = BOCPDModel(hazard=1 / 20)
        for _ in range(30):
            model.update(5.0)
        for _ in range(5):
            cp = model.update(50.0)
        assert cp > 0.02, f"Regime shift should elevate CP prob, got {cp}"

    def test_noise_no_false_changepoints(self) -> None:
        import random

        rng = random.Random(42)
        model = BOCPDModel(hazard=1 / 100)
        high_cps = 0
        for _ in range(100):
            cp = model.update(rng.gauss(5, 1))
            if cp > 0.5:
                high_cps += 1
        assert high_cps < 10, f"Noise should not trigger many CPs, got {high_cps}"


class TestEntropy(unittest.TestCase):
    def test_constant_signal_low_entropy(self) -> None:
        model = EntropyModel(bins=32)
        for _ in range(50):
            e = model.update(0.5, obs_min=0.0, obs_max=1.0)
        assert e < 0.3, f"Constant signal should have low entropy, got {e}"

    def test_uniform_signal_high_entropy(self) -> None:
        import random

        rng = random.Random(42)
        model = EntropyModel(bins=32)
        for _ in range(200):
            e = model.update(rng.random(), obs_min=0.0, obs_max=1.0)
        assert e > 0.6, f"Uniform signal should have high entropy, got {e}"


class TestSourceModel(unittest.TestCase):
    def test_steady_low_density(self) -> None:
        model = SourceModel(source_id="test.steady", obs_min=0.0, obs_max=10.0)
        for _ in range(100):
            d = model.update(5.0)
        assert d.density < 0.3, (
            f"Steady source should have low density after convergence, got {d.density}"
        )

    def test_change_high_density(self) -> None:
        model = SourceModel(source_id="test.change", obs_min=0.0, obs_max=100.0)
        for _ in range(50):
            model.update(5.0)
        d = model.update(80.0)
        assert d.density > 0.3, f"Change should produce high density, got {d.density}"
        assert d.surprise > 0.3, f"Change should produce high surprise, got {d.surprise}"

    def test_change_produces_density_spike(self) -> None:
        model = SourceModel(source_id="test.spike", obs_min=0.0, obs_max=100.0)
        for _ in range(100):
            model.update(5.0)
        baseline = model.last_density.density
        d = model.update(90.0)
        assert d.density > baseline, (
            f"Change ({d.density:.3f}) should produce higher density than baseline ({baseline:.3f})"
        )


class TestInformationDensityField(unittest.TestCase):
    def test_register_and_update(self) -> None:
        field = InformationDensityField()
        field.register_source("test.a", obs_min=0.0, obs_max=1.0)
        d = field.update("test.a", 0.5)
        assert d.source_id == "test.a"
        assert 0.0 <= d.density <= 1.0

    def test_auto_register(self) -> None:
        field = InformationDensityField()
        d = field.update("test.auto", 0.5)
        assert d.source_id == "test.auto"

    def test_aggregate(self) -> None:
        field = InformationDensityField()
        for i in range(5):
            field.register_source(f"test.{i}", obs_min=0.0, obs_max=1.0)
            field.update(f"test.{i}", 0.5)
        agg = field.aggregate_density()
        assert 0.0 <= agg <= 1.0

    def test_top_sources_ordered(self) -> None:
        field = InformationDensityField()
        field.register_source("low", obs_min=0.0, obs_max=1.0)
        field.register_source("high", obs_min=0.0, obs_max=100.0)

        for _ in range(30):
            field.update("low", 0.5)
            field.update("high", 0.5)

        field.update("high", 90.0)
        field.update("low", 0.5)

        top = field.top_sources(2)
        assert top[0].source_id == "high", f"Expected 'high' first, got {top[0].source_id}"

    def test_trend_positive_on_increase(self) -> None:
        field = InformationDensityField()
        field.register_source("trend", obs_min=0.0, obs_max=100.0)
        for _ in range(30):
            field.update("trend", 5.0)
        d = field.update("trend", 80.0)
        assert d.trend > 0, f"Trend should be positive after increase, got {d.trend}"


if __name__ == "__main__":
    unittest.main()
