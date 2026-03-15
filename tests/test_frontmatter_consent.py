"""Tests for frontmatter consent label extraction (DD-11) and labeled reads (DD-12)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.governance.consent_label import ConsentLabel
from shared.frontmatter import extract_consent_label, extract_provenance, labeled_read


class TestExtractConsentLabel(unittest.TestCase):
    def test_no_field_returns_none(self):
        assert extract_consent_label({}) is None

    def test_empty_field_returns_bottom(self):
        assert extract_consent_label({"consent_label": {}}) == ConsentLabel.bottom()

    def test_non_dict_returns_bottom(self):
        assert extract_consent_label({"consent_label": "invalid"}) == ConsentLabel.bottom()

    def test_single_policy(self):
        fm = {
            "consent_label": {
                "policies": [{"owner": "alice", "readers": ["bob"]}],
            }
        }
        label = extract_consent_label(fm)
        assert label is not None
        assert label.policies == frozenset({("alice", frozenset({"bob"}))})

    def test_multiple_policies(self):
        fm = {
            "consent_label": {
                "policies": [
                    {"owner": "alice", "readers": ["bob"]},
                    {"owner": "carol", "readers": ["dave", "eve"]},
                ],
            }
        }
        label = extract_consent_label(fm)
        assert label is not None
        assert len(label.policies) == 2

    def test_empty_readers(self):
        fm = {"consent_label": {"policies": [{"owner": "alice", "readers": []}]}}
        label = extract_consent_label(fm)
        assert label == ConsentLabel(frozenset({("alice", frozenset())}))

    def test_empty_policies_list(self):
        fm = {"consent_label": {"policies": []}}
        label = extract_consent_label(fm)
        assert label == ConsentLabel.bottom()

    def test_bad_policy_entry_skipped(self):
        fm = {"consent_label": {"policies": ["not a dict", {"owner": "alice", "readers": []}]}}
        label = extract_consent_label(fm)
        assert label is not None
        assert len(label.policies) == 1

    def test_missing_owner_skipped(self):
        fm = {"consent_label": {"policies": [{"readers": ["bob"]}]}}
        label = extract_consent_label(fm)
        assert label == ConsentLabel.bottom()


class TestExtractProvenance(unittest.TestCase):
    def test_no_field(self):
        assert extract_provenance({}) == frozenset()

    def test_list_of_strings(self):
        assert extract_provenance({"provenance": ["c1", "c2"]}) == frozenset({"c1", "c2"})

    def test_non_list(self):
        assert extract_provenance({"provenance": "not a list"}) == frozenset()

    def test_coerces_values(self):
        assert extract_provenance({"provenance": [1, 2]}) == frozenset({"1", "2"})


class TestLabeledRead(unittest.TestCase):
    def _write_temp(self, content: str) -> Path:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        f.write(content)
        f.flush()
        return Path(f.name)

    def test_plain_file(self):
        path = self._write_temp("Hello world")
        result = labeled_read(path)
        assert result.value == "Hello world"
        assert result.label == ConsentLabel.bottom()
        assert result.provenance == frozenset()

    def test_file_with_consent_label(self):
        content = """---
consent_label:
  policies:
    - owner: alice
      readers: [bob]
---
Body text here.
"""
        path = self._write_temp(content)
        result = labeled_read(path)
        assert result.value == "Body text here.\n"
        assert result.label == ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))

    def test_file_with_provenance(self):
        content = """---
provenance: [contract-1, contract-2]
---
Data.
"""
        path = self._write_temp(content)
        result = labeled_read(path)
        assert result.provenance == frozenset({"contract-1", "contract-2"})

    def test_file_with_both(self):
        content = """---
consent_label:
  policies:
    - owner: carol
      readers: []
provenance: [c1]
---
Content.
"""
        path = self._write_temp(content)
        result = labeled_read(path)
        assert result.label == ConsentLabel(frozenset({("carol", frozenset())}))
        assert result.provenance == frozenset({"c1"})
        assert result.value == "Content.\n"

    def test_nonexistent_file(self):
        result = labeled_read(Path("/nonexistent/file.md"))
        assert result.value == ""
        assert result.label == ConsentLabel.bottom()


if __name__ == "__main__":
    unittest.main()
