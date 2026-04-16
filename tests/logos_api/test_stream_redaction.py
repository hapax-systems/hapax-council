"""Tests for logos.api.deps.stream_redaction (LRR Phase 6 §4.A helpers)."""

from __future__ import annotations

import pytest

from logos.api.deps.stream_redaction import (
    band,
    band_coherence,
    band_energy,
    band_heart_rate,
    band_hrv,
    band_tension,
    omit_if_public,
    pii_redact,
    redact_field_if_public,
    require_private_stream,
)

# ── band() generic ──────────────────────────────────────────────────────────


class TestBand:
    def test_three_band_below(self):
        assert band(0.1, thresholds=(0.33, 0.66), labels=("low", "medium", "high")) == "low"

    def test_three_band_middle(self):
        assert band(0.5, thresholds=(0.33, 0.66), labels=("low", "medium", "high")) == "medium"

    def test_three_band_above(self):
        assert band(0.9, thresholds=(0.33, 0.66), labels=("low", "medium", "high")) == "high"

    def test_two_band(self):
        assert band(0.4, thresholds=(0.5,), labels=("low", "high")) == "low"
        assert band(0.6, thresholds=(0.5,), labels=("low", "high")) == "high"

    def test_none_preserves_none(self):
        assert band(None, thresholds=(0.5,), labels=("a", "b")) is None

    def test_boundary_inclusive_lower(self):
        # value == threshold falls into the lower band (<=)
        assert band(0.5, thresholds=(0.5,), labels=("low", "high")) == "low"

    def test_label_count_mismatch_raises(self):
        with pytest.raises(ValueError):
            band(
                0.5, thresholds=(0.3, 0.6), labels=("a", "b")
            )  # 2 labels for 2 thresholds (needs 3)


# ── Preset bands ────────────────────────────────────────────────────────────


class TestPresetBands:
    @pytest.mark.parametrize(
        "bpm,expected",
        [(60, "nominal"), (70, "nominal"), (71, "elevated"), (110, "elevated"), (130, "critical")],
    )
    def test_heart_rate(self, bpm, expected):
        assert band_heart_rate(bpm) == expected

    @pytest.mark.parametrize("ms,expected", [(20, "reduced"), (30, "reduced"), (50, "stable")])
    def test_hrv(self, ms, expected):
        assert band_hrv(ms) == expected

    def test_energy_coherence_tension(self):
        assert band_energy(0.1) == "low"
        assert band_coherence(0.6) == "coherent"
        assert band_tension(0.9) == "stressed"


# ── Dotted-path redaction ───────────────────────────────────────────────────


@pytest.fixture
def public_visible(monkeypatch):
    monkeypatch.setattr("logos.api.deps.stream_redaction._is_publicly_visible", lambda: True)


@pytest.fixture
def private_visible(monkeypatch):
    monkeypatch.setattr("logos.api.deps.stream_redaction._is_publicly_visible", lambda: False)


class TestOmitIfPublic:
    def test_omits_on_public(self, public_visible):
        r = {"a": 1, "dimensions": {"skin_temperature_c": 37.0, "energy": 0.5}}
        omit_if_public(r, "dimensions.skin_temperature_c")
        assert "skin_temperature_c" not in r["dimensions"]
        assert r["dimensions"]["energy"] == 0.5  # sibling untouched

    def test_preserves_on_private(self, private_visible):
        r = {"dimensions": {"skin_temperature_c": 37.0}}
        omit_if_public(r, "dimensions.skin_temperature_c")
        assert r["dimensions"]["skin_temperature_c"] == 37.0

    def test_missing_path_no_op(self, public_visible):
        r = {"a": 1}
        omit_if_public(r, "nonexistent.field")
        assert r == {"a": 1}

    def test_returns_dict_for_chaining(self, public_visible):
        r = {"a": 1, "b": 2}
        result = omit_if_public(r, "a")
        assert result is r


class TestRedactFieldIfPublic:
    def test_replaces_on_public(self, public_visible):
        r = {"user": {"email": "x@y.com"}}
        redact_field_if_public(r, "user.email")
        assert r["user"]["email"] == "[redacted]"

    def test_custom_placeholder(self, public_visible):
        r = {"user": {"email": "x@y.com"}}
        redact_field_if_public(r, "user.email", placeholder="***")
        assert r["user"]["email"] == "***"

    def test_preserves_on_private(self, private_visible):
        r = {"user": {"email": "x@y.com"}}
        redact_field_if_public(r, "user.email")
        assert r["user"]["email"] == "x@y.com"


# ── PII patterns ────────────────────────────────────────────────────────────


class TestPiiRedact:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("contact me at alice@example.com", "contact me at [redacted]"),
            ("call 555-123-4567 tonight", "call [redacted] tonight"),
            ("SSN 123-45-6789 on file", "SSN [redacted] on file"),
            ("cc 4111 1111 1111 1111 ok?", "cc [redacted] ok?"),
        ],
    )
    def test_patterns(self, text, expected):
        assert pii_redact(text) == expected

    def test_no_pii_pass_through(self):
        s = "nothing sensitive here"
        assert pii_redact(s) == s


# ── require_private_stream dependency ───────────────────────────────────────


class TestRequirePrivateStream:
    def test_raises_403_when_public(self, public_visible):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            require_private_stream()
        assert exc.value.status_code == 403
        assert "redacted_stream_mode_public" in str(exc.value.detail)

    def test_passes_when_private(self, private_visible):
        # Should not raise
        require_private_stream()
