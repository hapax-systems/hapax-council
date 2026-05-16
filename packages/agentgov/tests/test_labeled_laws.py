"""Property tests for Labeled[T] functor laws."""

from __future__ import annotations

from hypothesis import given, settings

from agentgov.labeled import Labeled
from tests.strategies import st_labeled


class TestLabeledFunctorLaws:
    """Verify functor laws for Labeled[T].map()."""

    @given(labeled=st_labeled())
    @settings(max_examples=100)
    def test_identity(self, labeled: Labeled):
        """map(id) == id: mapping identity preserves the labeled value."""
        result = labeled.map(lambda x: x)
        assert result.value == labeled.value
        assert result.label == labeled.label
        assert result.provenance == labeled.provenance

    @given(labeled=st_labeled())
    @settings(max_examples=100)
    def test_composition(self, labeled: Labeled):
        """map(f).map(g) == map(g . f): composition law."""

        def f(x):
            return x + 1

        def g(x):
            return x * 3

        lhs = labeled.map(f).map(g)
        rhs = labeled.map(lambda x: g(f(x)))
        assert lhs.value == rhs.value
        assert lhs.label == rhs.label
        assert lhs.provenance == rhs.provenance
