"""Tests for CircadianBackend — circadian alignment from operator profile."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from agents.hapax_daimonion.backends.circadian import CircadianBackend
from agents.hapax_daimonion.primitives import Behavior


class TestCircadianBackend:
    def test_no_profile_neutral_default(self, tmp_path):
        path = tmp_path / "operator-profile.json"
        backend = CircadianBackend(profile_path=path)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["circadian_alignment"].value == pytest.approx(0.5)

    def test_peak_hour(self, tmp_path):
        path = tmp_path / "operator-profile.json"
        path.write_text(
            json.dumps(
                {
                    "facts": [
                        {
                            "dimension": "energy_and_attention",
                            "text": "Peak productivity at 9am, 10am, 11am",
                        },
                    ],
                }
            )
        )
        backend = CircadianBackend(profile_path=path)
        mock_dt = datetime(2026, 3, 12, 10, 0)
        with patch("agents.hapax_daimonion.backends.circadian.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            behaviors: dict[str, Behavior] = {}
            backend.contribute(behaviors)
            assert behaviors["circadian_alignment"].value == pytest.approx(0.1)

    def test_transition_hour(self, tmp_path):
        path = tmp_path / "operator-profile.json"
        path.write_text(
            json.dumps(
                {
                    "facts": [
                        {
                            "dimension": "energy_and_attention",
                            "text": "Peak productivity hours are 9am to 11am",
                        },
                    ],
                }
            )
        )
        backend = CircadianBackend(profile_path=path)
        # 8am is adjacent to peak 9am → transition
        mock_dt = datetime(2026, 3, 12, 8, 0)
        with patch("agents.hapax_daimonion.backends.circadian.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            behaviors: dict[str, Behavior] = {}
            backend.contribute(behaviors)
            assert behaviors["circadian_alignment"].value == pytest.approx(0.3)

    def test_non_productive_hour(self, tmp_path):
        path = tmp_path / "operator-profile.json"
        path.write_text(
            json.dumps(
                {
                    "facts": [
                        {
                            "dimension": "energy_and_attention",
                            "text": "Peak productivity hours are 9am to 11am",
                        },
                    ],
                }
            )
        )
        backend = CircadianBackend(profile_path=path)
        # 3pm is far from peak
        mock_dt = datetime(2026, 3, 12, 15, 0)
        with patch("agents.hapax_daimonion.backends.circadian.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            behaviors: dict[str, Behavior] = {}
            backend.contribute(behaviors)
            assert behaviors["circadian_alignment"].value == pytest.approx(0.8)

    def test_empty_profile_facts(self, tmp_path):
        path = tmp_path / "operator-profile.json"
        path.write_text(json.dumps({"facts": []}))
        backend = CircadianBackend(profile_path=path)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["circadian_alignment"].value == pytest.approx(0.5)

    def test_corrupt_profile_graceful(self, tmp_path):
        path = tmp_path / "operator-profile.json"
        path.write_text("not json")
        backend = CircadianBackend(profile_path=path)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["circadian_alignment"].value == pytest.approx(0.5)
