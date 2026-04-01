# tests/test_consent_staleness.py
"""Test consent state file staleness detection."""

import json
import os
import time


def test_consent_state_file_staleness(tmp_path):
    """Verify stale consent state file is detected."""
    from shared.governance.consent import check_consent_state_freshness

    state_file = tmp_path / "consent-state.json"
    state_file.write_text(json.dumps({"phase": "NO_GUEST"}))
    old_time = time.time() - 600
    os.utime(state_file, (old_time, old_time))

    assert check_consent_state_freshness(state_file, stale_threshold_s=300.0) is False


def test_fresh_consent_state_file(tmp_path):
    """Verify fresh consent state file passes."""
    from shared.governance.consent import check_consent_state_freshness

    state_file = tmp_path / "consent-state.json"
    state_file.write_text(json.dumps({"phase": "NO_GUEST"}))

    assert check_consent_state_freshness(state_file, stale_threshold_s=300.0) is True


def test_missing_consent_state_file(tmp_path):
    """Missing file should be treated as stale (fail-closed)."""
    from shared.governance.consent import check_consent_state_freshness

    assert (
        check_consent_state_freshness(tmp_path / "missing.json", stale_threshold_s=300.0) is False
    )
