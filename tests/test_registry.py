"""Tests for shared.registry — the generic typed Registry[Record, Key] (KIND-0 / MOVE 2).

The framework must guarantee, for ANY store that parameterizes it:
- atomic per-object write (no torn/partial file, no leftover temp);
- an ABSENT-vs-CORRUPT distinction on read (conflating them is the fail-open hole that let a corrupt
  pinned record be overwritten + reaped);
- per-record corruption isolation (one bad record file must NOT collapse the whole store — the C2
  crash class where a single malformed receipt returned None for the entire registry);
- a MANDATORY (classify, is_reapable) reaper pair — a store CANNOT be instantiated without it, so a
  persisted concept ships with its lifecycle terminator or not at all (Work-Unit Totality by construction).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest

from shared.registry import Registry


@dataclass
class _Toy:
    id: str
    done: bool = False
    note: str = ""


class _ToyRegistry(Registry[_Toy, str]):
    def to_json(self, record: _Toy) -> str:
        return json.dumps(asdict(record), sort_keys=True)

    def from_json(self, raw: str) -> _Toy:
        return _Toy(**json.loads(raw))

    def key_of(self, record: _Toy) -> str:
        return record.id

    def slug(self, key: str) -> str:
        return key

    def classify(self, record: _Toy, **signals: object) -> str:
        return "done" if record.done else "active"

    def is_reapable(self, status: str, **signals: object) -> bool:
        return status == "done"


@pytest.fixture
def reg(tmp_path: Path) -> _ToyRegistry:
    return _ToyRegistry(tmp_path / "toy")


def test_save_load_round_trip(reg: _ToyRegistry) -> None:
    reg.save(_Toy(id="a", note="hi"))
    got = reg.load("a")
    assert got is not None and got.id == "a" and got.note == "hi"


def test_absent_read_is_none_not_corrupt(reg: _ToyRegistry) -> None:
    rec, corrupt = reg.read("missing")
    assert rec is None and corrupt is False


def test_corrupt_read_is_flagged_not_absent(reg: _ToyRegistry) -> None:
    reg.save(_Toy(id="a"))
    reg.path_for("a").write_text("{not json", encoding="utf-8")
    rec, corrupt = reg.read("a")
    # CORRUPT, not ABSENT — a caller must never overwrite this (it may hold a pin) nor reap it.
    assert rec is None and corrupt is True


def test_load_returns_none_on_corrupt(reg: _ToyRegistry) -> None:
    reg.save(_Toy(id="a"))
    reg.path_for("a").write_text("garbage", encoding="utf-8")
    assert reg.load("a") is None  # best-effort; callers that must distinguish use read()


def test_list_records_isolates_corrupt(reg: _ToyRegistry) -> None:
    reg.save(_Toy(id="a"))
    reg.save(_Toy(id="b"))
    reg.path_for("a").write_text("garbage", encoding="utf-8")
    ids = {r.id for r in reg.list_records()}
    assert ids == {"b"}  # one bad file skipped; the whole store does NOT collapse (the C2 lesson)


def test_save_is_atomic_no_leftover_temp(reg: _ToyRegistry) -> None:
    reg.save(_Toy(id="a", note="v1"))
    reg.save(_Toy(id="a", note="v2"))
    assert not list(Path(reg.root).glob(".reg-*.tmp"))
    got = reg.load("a")
    assert got is not None and got.note == "v2"


def test_deregister_removes_and_is_idempotent(reg: _ToyRegistry) -> None:
    reg.save(_Toy(id="a"))
    reg.deregister("a")
    assert reg.load("a") is None
    reg.deregister("a")  # idempotent, no error


def test_unsafe_slug_is_rejected(tmp_path: Path) -> None:
    class _Bad(_ToyRegistry):
        def slug(self, key: str) -> str:
            return "../escape"

    bad = _Bad(tmp_path / "bad")
    with pytest.raises(ValueError):
        bad.save(_Toy(id="x"))


def test_cannot_instantiate_without_the_reaper_pair(tmp_path: Path) -> None:
    # Work-Unit Totality by construction: no store ships without (classify, is_reapable).
    class _NoReaper(Registry[_Toy, str]):
        def to_json(self, record: _Toy) -> str:
            return "{}"

        def from_json(self, raw: str) -> _Toy:
            return _Toy(id="x")

        def key_of(self, record: _Toy) -> str:
            return record.id

        def slug(self, key: str) -> str:
            return key

        # classify + is_reapable intentionally MISSING

    with pytest.raises(TypeError):
        _NoReaper(tmp_path / "noreaper")


def test_classify_and_reaper_drive_lifecycle(reg: _ToyRegistry) -> None:
    assert reg.classify(_Toy(id="a", done=False)) == "active"
    assert reg.classify(_Toy(id="b", done=True)) == "done"
    assert reg.is_reapable(reg.classify(_Toy(id="b", done=True))) is True
    assert reg.is_reapable(reg.classify(_Toy(id="a", done=False))) is False
