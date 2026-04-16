"""Tests for ConsentRegistry.load(strict=True) — LRR Phase 6 §11."""

from __future__ import annotations

import pytest

from shared.governance.consent import ConsentContractLoadError, ConsentRegistry


def _write_good_contract(directory, contract_id="test-good"):
    (directory / f"{contract_id}.yaml").write_text(
        f"""\
id: {contract_id}
parties:
  - operator
  - test-subject
scope:
  - broadcast
direction: one_way
visibility_mechanism: on_request
created_at: "2026-04-16"
principal_class: adult
"""
    )


def _write_malformed_contract(directory, contract_id="test-bad"):
    (directory / f"{contract_id}.yaml").write_text("id: test-bad\nparties: [only_one]\n")


class TestStrictLoadFailsLoud:
    def test_strict_raises_on_malformed(self, tmp_path):
        _write_good_contract(tmp_path)
        _write_malformed_contract(tmp_path)
        registry = ConsentRegistry()
        with pytest.raises(ConsentContractLoadError) as exc_info:
            registry.load(tmp_path, strict=True)
        assert "test-bad.yaml" in str(exc_info.value)

    def test_strict_error_includes_root_cause(self, tmp_path):
        _write_malformed_contract(tmp_path)
        registry = ConsentRegistry()
        with pytest.raises(ConsentContractLoadError) as exc_info:
            registry.load(tmp_path, strict=True)
        assert exc_info.value.__cause__ is not None

    def test_strict_all_good_loads_cleanly(self, tmp_path):
        _write_good_contract(tmp_path, contract_id="c1")
        _write_good_contract(tmp_path, contract_id="c2")
        registry = ConsentRegistry()
        registry.load(tmp_path, strict=True)
        # Note: count is "active contracts" which requires non-expired state;
        # we mostly care about not-raising here.
        assert registry._fail_closed is False


class TestNonStrictPreservesBehavior:
    def test_non_strict_skips_malformed_and_loads_good(self, tmp_path, caplog):
        _write_good_contract(tmp_path, contract_id="keep")
        _write_malformed_contract(tmp_path, contract_id="skip")
        registry = ConsentRegistry()
        registry.load(tmp_path)  # default strict=False
        # Good contract loaded despite bad neighbor
        assert registry.get("keep") is not None
        # Bad contract was logged
        assert any("skip.yaml" in r.getMessage() for r in caplog.records)

    def test_non_strict_all_malformed_does_not_raise(self, tmp_path):
        _write_malformed_contract(tmp_path, contract_id="bad1")
        _write_malformed_contract(tmp_path, contract_id="bad2")
        registry = ConsentRegistry()
        # Does not raise
        registry.load(tmp_path)
