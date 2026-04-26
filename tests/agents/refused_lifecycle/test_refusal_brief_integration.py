"""Integration: refused-lifecycle transitions land in the refusal-brief log.

Covers the schema extension on ``RefusalEvent`` (3 new optional fields),
the ``_to_refusal_event`` adapter, the ``is_public_safe`` classifier, and
the runner's apply_transition integration.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from agents.refusal_brief.writer import RefusalEvent
from agents.refused_lifecycle.runner import (
    _to_refusal_event,
    apply_transition,
    is_public_safe,
    parse_frontmatter,
)
from agents.refused_lifecycle.state import TransitionEvent

_NOW = datetime(2026, 4, 26, 22, 45, tzinfo=UTC)


def _write_task(path: Path, slug: str, automation_status: str = "REFUSED") -> None:
    fm = {
        "type": "cc-task",
        "task_id": slug,
        "title": f"refusal: {slug}",
        "automation_status": automation_status,
        "refusal_reason": "single_user axiom",
        "evaluation_trigger": ["constitutional"],
        "evaluation_probe": {"depends_on_slug": None},
    }
    path.write_text(f"---\n{yaml.safe_dump(fm)}---\n# body\n", encoding="utf-8")


# ── RefusalEvent backward-compatible extension ───────────────────────


class TestRefusalEventExtension:
    def test_new_fields_have_defaults(self):
        ev = RefusalEvent(
            timestamp=_NOW,
            axiom="single_user",
            surface="publication-bus:bandcamp-upload",
            reason="vendor lock-in",
        )
        # Backward-compat: defaults preserve existing subscribers' behaviour
        assert ev.transition == "created"
        assert ev.evidence_url is None
        assert ev.cc_task_slug is None

    def test_explicit_extension_fields(self):
        ev = RefusalEvent(
            timestamp=_NOW,
            axiom="constitutional",
            surface="refused-lifecycle:leverage-twitter",
            reason="probe-clear: lift-keyword present",
            transition="accepted",
            evidence_url="https://example.com/policy",
            cc_task_slug="leverage-twitter",
        )
        assert ev.transition == "accepted"
        assert ev.evidence_url == "https://example.com/policy"
        assert ev.cc_task_slug == "leverage-twitter"


# ── is_public_safe classifier ────────────────────────────────────────


class TestIsPublicSafe:
    @pytest.mark.parametrize(
        "slug",
        [
            "pub-bus-bandcamp-upload",
            "repo-pres-code-of-conduct",
            "awareness-refused-aggregation-api",
            "awareness-refused-public-marketing-dashboards",
        ],
    )
    def test_public_safe_slugs(self, slug):
        assert is_public_safe(slug) is True

    @pytest.mark.parametrize(
        "slug",
        [
            "cold-contact-email-last-resort",
            "cold-contact-public-archive-listserv",
        ],
    )
    def test_cold_contact_is_not_public(self, slug):
        # Cold-contact surfaces touch operator-personal-mail context;
        # always conservative-private.
        assert is_public_safe(slug) is False

    @pytest.mark.parametrize(
        "slug",
        [
            "leverage-twitter-linkedin-substack",  # leverage-* default conservative
            "unknown-surface",  # unknown → conservative
            "",  # empty → conservative
        ],
    )
    def test_conservative_default(self, slug):
        assert is_public_safe(slug) is False


# ── _to_refusal_event adapter ────────────────────────────────────────


class TestToRefusalEvent:
    def _ev(self, **overrides) -> TransitionEvent:
        defaults = dict(
            timestamp=_NOW,
            cc_task_slug="leverage-twitter",
            from_state="REFUSED",
            to_state="REFUSED",
            transition="re-affirmed",
            trigger=["constitutional"],
            reason="probe-content-unchanged",
        )
        defaults.update(overrides)
        return TransitionEvent(**defaults)

    def test_re_affirmed_event(self):
        te = self._ev()
        re = _to_refusal_event(te)
        assert re.transition == "re-affirmed"
        assert re.cc_task_slug == "leverage-twitter"
        assert re.surface == "refused-lifecycle:leverage-twitter"
        assert re.public is False  # leverage-* conservative default

    def test_accepted_event(self):
        te = self._ev(
            cc_task_slug="pub-bus-bandcamp-upload",
            to_state="ACCEPTED",
            transition="accepted",
            evidence_url="https://example.com/policy",
            reason="probe-clear: lift-keyword present",
        )
        re = _to_refusal_event(te)
        assert re.transition == "accepted"
        assert re.evidence_url == "https://example.com/policy"
        assert re.public is True  # pub-bus-* is public-safe

    def test_regressed_event(self):
        te = self._ev(
            from_state="ACCEPTED",
            to_state="REFUSED",
            transition="regressed",
            reason="regression-detected: lift-keyword disappeared",
        )
        re = _to_refusal_event(te)
        assert re.transition == "regressed"

    def test_removed_event(self):
        te = self._ev(
            to_state="REMOVED",
            transition="removed",
            reason="axiom retired",
        )
        re = _to_refusal_event(te)
        assert re.transition == "removed"

    def test_reason_truncated_to_160_chars(self):
        long_reason = "x" * 200
        te = self._ev(reason=long_reason)
        re = _to_refusal_event(te)
        assert len(re.reason) == 160

    def test_multi_trigger_axiom_field(self):
        te = self._ev(trigger=["structural", "constitutional"])
        re = _to_refusal_event(te)
        assert "structural" in re.axiom
        assert "constitutional" in re.axiom

    def test_jsonl_roundtrip(self):
        te = self._ev(
            evidence_url="https://example.com/x",
            transition="accepted",
            to_state="ACCEPTED",
        )
        re = _to_refusal_event(te)
        line = re.model_dump_json()
        decoded = json.loads(line)
        assert decoded["transition"] == "accepted"
        assert decoded["evidence_url"] == "https://example.com/x"
        assert decoded["cc_task_slug"] == "leverage-twitter"


# ── runner.apply_transition emits to refusal_brief.append ───────────


class TestApplyTransitionEmitsToLog:
    def test_emits_one_event_per_transition(self, tmp_path: Path, monkeypatch):
        log_path = tmp_path / "refusal-log.jsonl"
        monkeypatch.setenv("HAPAX_REFUSALS_LOG_PATH", str(log_path))

        # Force the module-level DEFAULT_LOG_PATH to honour the env override
        # by reloading the writer's path resolution. Tests pass an explicit
        # log_path to the writer's append() — we rely on that path through
        # apply_transition's call site.
        f = tmp_path / "pub-bus-bandcamp-upload.md"
        _write_task(f, "pub-bus-bandcamp-upload")
        task = parse_frontmatter(f)

        event = TransitionEvent(
            timestamp=_NOW,
            cc_task_slug=task.slug,
            from_state="REFUSED",
            to_state="REFUSED",
            transition="re-affirmed",
            trigger=["constitutional"],
            reason="probe-content-unchanged",
        )
        apply_transition(f, task, event, _NOW, refusal_log_path=log_path)

        assert log_path.exists()
        lines = [json.loads(line) for line in log_path.read_text().splitlines() if line]
        assert len(lines) == 1
        assert lines[0]["transition"] == "re-affirmed"
        assert lines[0]["cc_task_slug"] == "pub-bus-bandcamp-upload"
        assert lines[0]["public"] is True  # pub-bus-* is public-safe
