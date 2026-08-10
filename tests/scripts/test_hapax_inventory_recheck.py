"""The inventory recheck harness, and the direction it must never err in.

The measured correlation this exists to watch: over 52 systems, 26 of the 27 rows with no
absence witness are not live, and every ``dead`` and ``unbuilt`` row lacks one — fourteen for
fourteen. A row that cannot witness its own absence is a row that dies quietly.

The load-bearing property is therefore that the checker must **over**-report unwitnessed rows,
never under-report them. Its first version anchored the no-witness matcher to end-of-string and
found 9 of 28 on the live file, because most rows say "none" and then explain why. That is the
failure this suite pins: a coverage checker that understates the gap is worse than none, since
it converts an unexamined surface into a green one.

Self-contained per the repo testing convention (no shared conftest fixtures).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-inventory-recheck"

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def _load() -> ModuleType:
    name = "hapax_inventory_recheck_test_module"
    sys.modules.pop(name, None)
    loader = SourceFileLoader(name, str(SCRIPT))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def _inventory(rows: list[dict], generated: str = "2026-08-10T16:20:00Z") -> dict:
    return {"schema": "test.v1", "generated_at": generated, "systems": rows}


def _row(**kw) -> dict:
    base = {
        "system_id": "sys.example",
        "fact_status_class": "live",
        "absence_witness": "a timer whose failure is alarmed",
        "recheck_command": "systemctl --user is-active hapax-example.timer",
        "implementation_refs": [],
    }
    base.update(kw)
    return base


def test_prose_that_begins_with_none_counts_as_unwitnessed() -> None:
    """The regression that mattered: 18 of 28 rows were missed by an end-anchored matcher.

    Rows that say "none" and then explain why still have no witness. They are just honest.
    """
    module = _load()
    forms = [
        "none.",
        "none",
        "none - by construction, an unbuilt discovery system cannot witness its own absence",
        "none. A caught ValueError converts a structural refusal into a plausible zero.",
        "none. No timer, no consumer, no drift signal.",
        "N/A",
        "",
        None,
    ]
    rows = [_row(system_id=f"sys.{i}", absence_witness=f) for i, f in enumerate(forms)]
    result = module.check(_inventory(rows), now=NOW, max_age_days=14)
    assert len(result["unwitnessed"]) == len(forms), result["unwitnessed"]


def test_a_real_witness_is_not_flagged() -> None:
    """The over-report bias must not become an always-report bias, or the signal is gone."""
    module = _load()
    rows = [
        _row(
            system_id="sys.a", absence_witness="axiom-commit-scan.sh at commit time (fail-closed)"
        ),
        _row(system_id="sys.b", absence_witness="hapax-quota-telemetry.timer next-run scheduling"),
        _row(system_id="sys.c", absence_witness="route admission refusal on a stale receipt"),
    ]
    result = module.check(_inventory(rows), now=NOW, max_age_days=14)
    assert result["unwitnessed"] == []


def test_glob_and_directory_refs_resolve(tmp_path: Path) -> None:
    """A populated glob is present. Treating it literally cried wolf, which trains people to ignore."""
    module = _load()
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "hapax-one.json").write_text("{}", encoding="utf-8")
    rows = [
        _row(system_id="sys.glob", implementation_refs=[str(tmp_path / "d" / "hapax-*.json")]),
        _row(system_id="sys.dir", implementation_refs=[str(tmp_path / "d") + "/"]),
    ]
    assert module.check(_inventory(rows), now=NOW, max_age_days=14)["vanished"] == []


def test_a_genuinely_missing_ref_is_reported(tmp_path: Path) -> None:
    module = _load()
    rows = [_row(system_id="sys.gone", implementation_refs=[str(tmp_path / "nope.json")])]
    vanished = module.check(_inventory(rows), now=NOW, max_age_days=14)["vanished"]
    assert [sid for sid, _ in vanished] == ["sys.gone"]


def test_non_local_refs_are_skipped_not_guessed() -> None:
    """repo:/url:/container: refs are not resolvable from here; guessing would be noise."""
    module = _load()
    rows = [
        _row(
            system_id="sys.remote",
            implementation_refs=["repo:hapax-council:shared/x.py", "https://example.invalid/y"],
        )
    ]
    assert module.check(_inventory(rows), now=NOW, max_age_days=14)["vanished"] == []


def test_a_trivial_recheck_command_is_reported() -> None:
    """A placeholder recheck passes forever, which is indistinguishable from coverage."""
    module = _load()
    rows = [
        _row(system_id="sys.true", recheck_command="true"),
        _row(system_id="sys.echo", recheck_command="echo TODO"),
        _row(system_id="sys.empty", recheck_command=""),
        _row(system_id="sys.none", recheck_command=None),
        _row(system_id="sys.real", recheck_command="test -f ~/x && stat -c %y ~/x"),
    ]
    trivial = module.check(_inventory(rows), now=NOW, max_age_days=14)["trivial_recheck"]
    assert trivial == ["sys.true", "sys.echo", "sys.empty", "sys.none"]


def test_staleness_is_reported_against_the_horizon() -> None:
    module = _load()
    fresh = module.check(_inventory([_row()], "2026-08-09T00:00:00Z"), now=NOW, max_age_days=14)
    stale = module.check(_inventory([_row()], "2026-06-01T00:00:00Z"), now=NOW, max_age_days=14)
    assert fresh["stale"] is False
    assert stale["stale"] is True


def test_a_clean_inventory_exits_zero() -> None:
    module = _load()
    result = module.check(_inventory([_row()]), now=NOW, max_age_days=14)
    assert module.report(result) == module.OK


def test_any_finding_exits_nonzero() -> None:
    """The scheduler's failure path is this harness's own liveness signal.

    If it exited 0 on a finding, a timer would report success while the estate rotted — which
    is the exact class of defect it was written to detect.
    """
    module = _load()
    result = module.check(_inventory([_row(absence_witness="none.")]), now=NOW, max_age_days=14)
    assert module.report(result) == module.FINDING


def test_a_malformed_inventory_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """Refuse rather than green-light. An unreadable inventory is not a healthy one."""
    module = _load()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"generated_at": "2026-08-10T00:00:00Z"}), encoding="utf-8")
    assert module.main(["--inventory", str(bad)]) == module.ERROR

    missing = tmp_path / "nope.json"
    assert module.main(["--inventory", str(missing)]) == module.ERROR


def test_the_harness_writes_nothing(tmp_path: Path) -> None:
    """Read-only by construction: it must not be able to repair a row into looking healthy."""
    module = _load()
    path = tmp_path / "inv.json"
    payload = _inventory([_row(absence_witness="none.")])
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()
    module.main(["--inventory", str(path)])
    assert path.read_bytes() == before
