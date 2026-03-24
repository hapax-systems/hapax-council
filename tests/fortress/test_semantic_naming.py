"""Tests for agents.fortress.semantic_naming — profile generation and assignment."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agents.fortress.semantic_naming import (
    DIMENSION_TO_FACET,
    HAPAX_CONCEPT_NAMES,
    assign_profile,
    generate_profiles,
    write_profiles,
)


class TestGenerateProfiles(unittest.TestCase):
    def test_default_generates_20(self) -> None:
        profiles = generate_profiles()
        self.assertEqual(len(profiles), 20)

    def test_each_profile_has_nickname(self) -> None:
        profiles = generate_profiles()
        for p in profiles:
            self.assertIsInstance(p.nickname, str)
            self.assertGreater(len(p.nickname), 0)

    def test_each_profile_has_facets(self) -> None:
        profiles = generate_profiles()
        for p in profiles:
            self.assertIsInstance(p.facets, dict)
            self.assertGreater(len(p.facets), 0)

    def test_each_profile_has_beliefs(self) -> None:
        profiles = generate_profiles()
        for p in profiles:
            self.assertIsInstance(p.beliefs, dict)
            self.assertGreater(len(p.beliefs), 0)

    def test_each_profile_has_goals(self) -> None:
        profiles = generate_profiles()
        for p in profiles:
            self.assertIsInstance(p.goals, tuple)
            self.assertGreater(len(p.goals), 0)

    def test_nicknames_match_concepts(self) -> None:
        profiles = generate_profiles()
        names = [p.nickname for p in profiles]
        self.assertEqual(tuple(names), HAPAX_CONCEPT_NAMES)

    def test_custom_concepts(self) -> None:
        custom = ("Alpha", "Beta", "Gamma")
        profiles = generate_profiles(concept_names=custom)
        self.assertEqual(len(profiles), 3)
        self.assertEqual(profiles[0].nickname, "Alpha")

    def test_creative_dimension_has_art_belief(self) -> None:
        profiles = generate_profiles()
        # creative_process is at index 3
        creative_profile = profiles[3]
        self.assertIn("ART", creative_profile.beliefs)

    def test_information_dimension_has_truth_belief(self) -> None:
        profiles = generate_profiles()
        # information_seeking is at index 2
        info_profile = profiles[2]
        self.assertIn("TRUTH", info_profile.beliefs)


class TestAssignProfile(unittest.TestCase):
    def test_deterministic(self) -> None:
        profiles = generate_profiles()
        p1 = assign_profile(profiles, 42)
        p2 = assign_profile(profiles, 42)
        self.assertEqual(p1.nickname, p2.nickname)

    def test_wraps_around(self) -> None:
        profiles = generate_profiles()
        p0 = assign_profile(profiles, 0)
        p20 = assign_profile(profiles, 20)
        self.assertEqual(p0.nickname, p20.nickname)

    def test_empty_profiles_returns_unnamed(self) -> None:
        p = assign_profile([], 0)
        self.assertEqual(p.nickname, "Unnamed")

    def test_different_ids_different_profiles(self) -> None:
        profiles = generate_profiles()
        p0 = assign_profile(profiles, 0)
        p1 = assign_profile(profiles, 1)
        self.assertNotEqual(p0.nickname, p1.nickname)


class TestWriteProfiles(unittest.TestCase):
    def test_creates_valid_json(self) -> None:
        profiles = generate_profiles()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "subdir" / "profiles.json"
            write_profiles(profiles, path)
            self.assertTrue(path.exists())
            data = json.loads(path.read_text())
            self.assertEqual(len(data), 20)

    def test_json_structure(self) -> None:
        profiles = generate_profiles()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            write_profiles(profiles, path)
            data = json.loads(path.read_text())
            entry = data[0]
            self.assertIn("nickname", entry)
            self.assertIn("facets", entry)
            self.assertIn("beliefs", entry)
            self.assertIn("goals", entry)
            self.assertIsInstance(entry["goals"], list)


class TestDimensionToFacet(unittest.TestCase):
    def test_covers_all_11_dimensions(self) -> None:
        self.assertEqual(len(DIMENSION_TO_FACET), 11)

    def test_all_values_are_dicts(self) -> None:
        for dim, facets in DIMENSION_TO_FACET.items():
            self.assertIsInstance(facets, dict, f"Dimension {dim} has non-dict facets")
            self.assertGreater(len(facets), 0, f"Dimension {dim} has empty facets")


if __name__ == "__main__":
    unittest.main()
