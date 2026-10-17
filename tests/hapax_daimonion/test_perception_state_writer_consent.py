"""The perception-state writer never emits persistence permission it was not given.

``persistence_allowed`` is written ``true`` only when a present consent
tracker answers exactly ``True``. No tracker, a tracker that raises, a
non-boolean answer, or a snapshot that failed to build all write ``false``
to both perception-state.json and consent-state.json, and curtail the
person-adjacent fields. Absence is never permission
(``interpersonal_transparency``; face privacy fails closed).

Positive controls: the operator-only ``no_guest`` tracker still allows,
and a guest-without-consent tracker still refuses, exactly as before.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.hapax_daimonion import _perception_state_writer as writer
from agents.hapax_daimonion.consent_state import ConsentStateTracker

_SENTINEL = "guest-alice-sentinel"


class _RaisingTracker:
    @property
    def persistence_allowed(self) -> bool:
        raise RuntimeError(_SENTINEL)

    @property
    def phase(self) -> SimpleNamespace:
        return SimpleNamespace(value="no_guest")


def _tracker(answer: object, phase: str = "no_guest") -> SimpleNamespace:
    return SimpleNamespace(persistence_allowed=answer, phase=SimpleNamespace(value=phase))


class _Unprintable:
    def __str__(self) -> str:
        raise RuntimeError(_SENTINEL)


def _perception(**behaviors: object) -> SimpleNamespace:
    return SimpleNamespace(
        behaviors={name: SimpleNamespace(value=v) for name, v in behaviors.items()},
        registered_backends={},
    )


_REGISTRY = SimpleNamespace(active_contracts=lambda: [])


@pytest.fixture()
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    perception_file = tmp_path / "perception-state.json"
    consent_file = tmp_path / "consent-state.json"
    monkeypatch.setattr(writer, "PERCEPTION_STATE_FILE", perception_file)
    monkeypatch.setattr(writer, "CONSENT_STATE_FILE", consent_file)
    monkeypatch.setattr(writer, "_push_to_ring", lambda state: None)
    monkeypatch.setattr(writer, "_last_persistence_block_cause", "", raising=False)
    return perception_file, consent_file


def _write(tracker: object, perception: SimpleNamespace | None = None) -> None:
    writer.write_perception_state(
        perception or _perception(top_emotion="happy", gaze_direction="camera"),
        _REGISTRY,
        tracker,  # type: ignore[arg-type]
    )


def _read(paths: tuple[Path, Path]) -> tuple[dict, dict]:
    perception_file, consent_file = paths
    return json.loads(perception_file.read_text()), json.loads(consent_file.read_text())


UNAVAILABLE = [
    pytest.param(None, "consent_tracker_absent", id="no-tracker"),
    pytest.param(_RaisingTracker(), "consent_tracker_error:RuntimeError", id="tracker-raises"),
    pytest.param(_tracker("yes"), "consent_tracker_non_bool", id="non-bool-string"),
    pytest.param(_tracker(1), "consent_tracker_non_bool", id="non-bool-int"),
    pytest.param(_tracker(None), "consent_tracker_non_bool", id="non-bool-none"),
]


@pytest.mark.parametrize(("tracker", "cause"), UNAVAILABLE)
def test_unavailable_tracker_never_emits_persistence_permission(
    paths: tuple[Path, Path], tracker: object, cause: str
) -> None:
    _write(tracker)

    perception, consent = _read(paths)
    assert perception["persistence_allowed"] is False
    assert consent["persistence_allowed"] is False
    assert perception["consent_curtailed"] is True
    assert perception["top_emotion"] == "[curtailed]"
    assert perception["gaze_direction"] == "[curtailed]"


@pytest.mark.parametrize("tracker", [None, _tracker(True)], ids=["no-tracker", "allowing"])
def test_failed_snapshot_never_emits_persistence_permission(
    paths: tuple[Path, Path], tracker: object
) -> None:
    _write(tracker, _perception(production_activity=_Unprintable()))

    perception, consent = _read(paths)
    assert perception.get("error") is True
    assert perception["persistence_allowed"] is False
    assert consent["persistence_allowed"] is False


def test_consent_state_never_reads_a_missing_key_as_permission(
    paths: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Any snapshot that reaches the consent-state write without the key
    # (here removed in flight) must not be published as permission.
    monkeypatch.setattr(writer, "_push_to_ring", lambda state: state.pop("persistence_allowed"))

    _write(ConsentStateTracker())

    _, consent = _read(paths)
    assert consent["persistence_allowed"] is False


def test_operator_only_no_guest_tracker_still_allows(paths: tuple[Path, Path]) -> None:
    tracker = ConsentStateTracker()
    assert tracker.phase.value == "no_guest"

    _write(tracker)

    perception, consent = _read(paths)
    assert perception["persistence_allowed"] is True
    assert consent["persistence_allowed"] is True
    assert consent["phase"] == "no_guest"
    assert "consent_curtailed" not in perception
    assert perception["top_emotion"] == "happy"


def test_guest_without_consent_still_refuses(paths: tuple[Path, Path]) -> None:
    _write(_tracker(False, phase="guest_detected"))

    perception, consent = _read(paths)
    assert perception["persistence_allowed"] is False
    assert consent["persistence_allowed"] is False
    assert consent["phase"] == "guest_detected"
    assert perception["consent_curtailed"] is True


@pytest.mark.parametrize(("tracker", "cause"), UNAVAILABLE)
def test_unavailable_tracker_logs_cause_and_remedy_once_without_raw_values(
    paths: tuple[Path, Path], tracker: object, cause: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=writer.log.name)

    _write(tracker)
    _write(tracker)

    blocked = [r for r in caplog.records if f"cause={cause}" in r.getMessage()]
    assert len(blocked) == 1
    assert blocked[0].levelno == logging.WARNING
    assert "remedy:" in blocked[0].getMessage()
    assert _SENTINEL not in caplog.text


def test_tracker_refusal_is_not_logged_as_unavailable(
    paths: tuple[Path, Path], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=writer.log.name)

    _write(_tracker(False, phase="guest_detected"))

    assert "cause=" not in caplog.text
