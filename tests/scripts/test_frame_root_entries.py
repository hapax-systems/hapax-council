"""Declared roots cannot disappear merely because the consumer cannot read their type."""

import json
from pathlib import Path

import pytest
import yaml

from shared import frame_verdicts as fv
from tests.scripts.test_hapax_methodology_dispatch import (
    _dispatch_receipt_only_scope,
    _frame_procedure_root,
)


def _root_dispatch(
    tmp_path,
    monkeypatch,
    capsys,
    location,
    *,
    reader="fs.content_query",
    cwd=None,
    candidate=None,
    unrelated=False,
):
    if cwd is None:
        cwd = tmp_path / "producer"
        candidate = cwd / "1/api_layers/explicit.d/XrApiLayer_api_dump.json"
        candidate.parent.mkdir(parents=True)
        candidate.write_text('{"api_layer": {}}\n')
    frame = _frame_procedure_root(
        tmp_path / "frame",
        decayed_root=cwd,
        reader=reader,
        location=location,
        query_params=reader == "fs.content_query",
    )
    if reader == "fs.content_query":
        params_path = frame / "declaration/params.yaml"
        params = yaml.safe_load(params_path.read_text())
        params["parameters"]["max_unit_bytes"]["value"] = 1024 * 1024
        params_path.write_text(yaml.safe_dump(params))
    (frame / "_runs/current/hypothesis.json").write_text(
        json.dumps({"iteration": {"environment": {"cwd": str(cwd)}}})
    )
    if unrelated:
        mass_path = frame / "declaration/mass.yaml"
        mass = yaml.safe_load(mass_path.read_text())
        mass["members"][1]["location"]["roots"] = [1]
        mass_path.write_text(yaml.safe_dump(mass))
        coverage = frame / "_runs/current/coverage.json"
        rows = json.loads(coverage.read_text())
        rows[1]["member_declaration_identity"] = fv._member_declaration_identity(
            mass["members"][1], mass["exclusions"]
        )
        coverage.write_text(json.dumps(rows))
    return _dispatch_receipt_only_scope(tmp_path, monkeypatch, capsys, frame, candidate)


def _location(root):
    return {
        "roots": [root, "review-no-such-root"],
        "patterns": ["XrApiLayer_api_dump.json"],
        "query": "api_layer",
    }


def _assert_root_refusal(rc, err, entry):
    assert rc == 10, "a declared root the consumer cannot read must not silently disappear"
    assert "legacy-surface" in err
    assert "location.roots[0] has unsupported entry" in err, (
        "this consumer requires string roots and refuses anything else by name. "
        "Reproducing the producer's Path(str(...)) mapping would be a defined "
        "interpretation of a declared value, not an invented path — but it is not this "
        "consumer's contract, and the named refusal is required even where that mapping "
        "would happen to return containment exit 10"
    )
    assert type(entry).__name__ in err
    assert repr(entry) in err
    assert "expected a string path or scheme-qualified location" in err
    assert "use a string such as '/path/to/root'" in err


@pytest.mark.parametrize("entry", [1, "1"], ids=["integer", "quoted"])
def test_main_reviewer_root_entry(tmp_path, monkeypatch, capsys, entry):
    """The reviewer's installed OpenXR surface, without invoking the producer."""
    cwd = Path("/usr/share/openxr")
    candidate = cwd / "1/api_layers/explicit.d/XrApiLayer_api_dump.json"
    if not candidate.is_file():
        pytest.skip("reviewer's installed OpenXR file absent; exact reproduction withheld")
    assert "api_layer" in candidate.read_text()
    location = _location(entry)
    location["roots"][1] = str(cwd / "review-no-such-root")
    assert not Path(location["roots"][1]).exists()
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        location,
        cwd=cwd,
        candidate=candidate,
    )
    with capsys.disabled():
        print(
            f"reviewer roots={location['roots']!r}; scope_exited=TRUE; main()={rc}; {err.strip()}"
        )
    if isinstance(entry, str):
        assert rc == 10
        assert "lies in legacy-surface (scope_exited)" in err
        assert "legacy-surface (scope_exited)" in err
        assert "unsupported entry" not in err
    else:
        _assert_root_refusal(rc, err, entry)


@pytest.mark.parametrize("reader", ["fs.content_query", "fs.glob"])
@pytest.mark.parametrize("entry", [1, {"path": "1"}, ["1"], None, 1.5])
def test_main_root_entry_shapes_refuse(tmp_path, monkeypatch, capsys, reader, entry):
    rc, err = _root_dispatch(tmp_path, monkeypatch, capsys, _location(entry), reader=reader)
    _assert_root_refusal(rc, err, entry)


@pytest.mark.parametrize("reader", ["fs.content_query", "fs.glob"])
def test_main_well_formed_roots_unchanged(tmp_path, monkeypatch, capsys, reader):
    location = _location("1")
    location["patterns"] = ["**/*.json"]
    rc, err = _root_dispatch(tmp_path, monkeypatch, capsys, location, reader=reader)
    assert rc == 10
    assert "legacy-surface (scope_exited)" in err
    assert "unsupported entry" not in err


@pytest.mark.parametrize("reader", ["fs.content_query", "fs.glob"])
def test_main_absent_roots_unchanged(tmp_path, monkeypatch, capsys, reader):
    location = {"path": "elsewhere", "patterns": ["**/*.json"], "query": "api_layer"}
    rc, err = _root_dispatch(tmp_path, monkeypatch, capsys, location, reader=reader)
    assert "unsupported entry" not in err
    if reader == "fs.content_query":
        assert rc == 10
        assert "location.roots must be a nonempty list" in err
    else:
        assert rc == 0, "fs.glob still uses location.path when roots is absent"


@pytest.mark.parametrize("reader", ["fs.content_query", "fs.glob"])
def test_main_unrelated_non_decayed_bad_root_unchanged(tmp_path, monkeypatch, capsys, reader):
    location = _location("1")
    location["patterns"] = ["*.py"]
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        location,
        reader=reader,
        unrelated=True,
    )
    assert rc == 0
    assert "unsupported entry" not in err


def test_unexpandable_root_refuses_with_the_member_named(tmp_path, monkeypatch) -> None:
    """A `~`-relative root whose home cannot be resolved must refuse, not raise.

    ``expanduser`` is a resolution step that can fail on its own terms: with no resolvable
    home it raises ``RuntimeError``, and before this repair that message reached a reader as
    an unhandled traceback while the ``resolve()`` immediately after it was already
    converted. An absolute root failed *inside* the refusal contract and a `~`-relative one
    failed *outside* it, for the same class of environmental fault.
    """

    real_expanduser = Path.expanduser

    def refusing_expanduser(self):
        if str(self).startswith("~"):
            raise RuntimeError("Could not determine home directory")
        return real_expanduser(self)

    monkeypatch.setattr(Path, "expanduser", refusing_expanduser)

    with pytest.raises(fv.FrameVerdictsUnavailable) as excinfo:
        fv._member_location(
            {"id": "m1", "location": {"roots": ["~/declared"], "query": "NEEDLE"}},
            epoch_dir=tmp_path,
        )

    message = str(excinfo.value)
    assert "cannot be expanded" in message
    assert "'m1'" in message
    assert "~/declared" in message
