"""Red/green witness for the K0 ratified-pin check unit (R0.4).

``hapax-k0-kernel-pin-check.service`` is a one-line guard: import the pinned K0
generation and refuse if the computed drift pin has moved away from the ratified
one. Its whole value is the FAILURE branch, and until this module existed that
branch was evidenced only by a one-off ``systemctl --user start`` transcript in a
PR body — the success path was witnessed and the failure path was asserted. Two
reviewers said so independently (PR #4571, ``exit-predicate-adequacy``).

So these tests run the command the unit actually ships, extracted from the unit
file rather than retyped, against a fabricated ``k0`` package whose two pins are
made to agree (green) and to disagree (red).

Three specific regressions are pinned, each of which previously shipped:

1. **A stripped assertion.** The original ExecStart spelled the check
   ``assert k0.K0_DRIFT_PIN == k0.RATIFIED_PIN``. Under ``-O`` that statement is
   removed and a drifted kernel exits 0 — the check false-greens exactly when it
   matters. The fix was an explicit ``SystemExit``; ``test_drift_still_fails``
   ``_under_optimize`` is what keeps it explicit, by running the red case with
   ``PYTHONOPTIMIZE=1`` (measured: ``__debug__`` False, ``sys.flags.optimize`` 1).

   An earlier revision instead set ``Environment=PYTHONOPTIMIZE=0``, on the
   belief that CPython reads any non-empty value as ``-O``. That is the pre-3.8
   ``add_flag()`` behaviour and is not what this interpreter does — measured on
   CPython 3.14.4, ``PYTHONOPTIMIZE=0`` leaves ``sys.flags.optimize`` at 0. The
   line was dropped because it guards nothing (nothing on this path asserts),
   not because it misbehaved. An env var is a hope; the ``-O`` run below is a
   witness, and it holds whatever the caller's environment says.

2. **A specifier systemd ate.** ``%s`` is a systemd specifier (user shell), so
   the failure message's ``%s`` placeholders had to be written ``%%s``. Getting
   that wrong corrupts the message only on the branch nobody exercises.

3. **A shadowed import.** The unit sets no ``PYTHONPATH`` and relies on
   ``python -c`` putting the working directory first on ``sys.path``. That is a
   claim about the interpreter, so it is measured rather than trusted.

Recheck::

    uv run pytest tests/systemd/test_k0_kernel_pin_check_unit.py -q

Mutation-check (each must turn this module red): put ``assert`` back in the
ExecStart; single one of the ``%%s``; add ``Environment=PYTHONPATH=`` back.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-k0-kernel-pin-check.service"

RATIFIED = "b604b52bfdd9e267b7a5b68f42d020f233065f3c6d77eeb9f244de2d78ee6d59"
DRIFTED = "0" * 64


def _service_values(text: str, key: str) -> list[str]:
    """Values of ``key`` in the ``[Service]`` section, comments excluded."""
    in_service = False
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_service = s == "[Service]"
            continue
        if not in_service or not s or s.startswith(("#", ";")) or "=" not in s:
            continue
        k, _, v = s.partition("=")
        if k.strip() == key:
            out.append(v.strip())
    return out


def _raw_execstart() -> str:
    values = _service_values(UNIT.read_text(encoding="utf-8"), "ExecStart")
    assert len(values) == 1, f"expected exactly one ExecStart, got {len(values)}"
    return values[0]


def _argv() -> list[str]:
    """The ExecStart as systemd hands it to ``execve``.

    systemd expands ``%%`` to a literal ``%`` and then splits on whitespace with
    quote grouping. Doing both here is what makes the tests below exercise the
    shipped command rather than a copy of it that could drift.
    """
    return shlex.split(_raw_execstart().replace("%%", "%"))


def _program() -> str:
    argv = _argv()
    assert argv[1] == "-c", f"expected `python3 -c <program>`, got {argv[:2]}"
    return argv[2]


def _write_k0(root: Path, drift_pin: str, ratified_pin: str) -> Path:
    """A stand-in ``k0`` package exposing only what the ExecStart touches."""
    pkg = root / "k0"
    pkg.mkdir(parents=True)
    init = pkg / "__init__.py"
    init.write_text(
        f'K0_DRIFT_PIN = "{drift_pin}"\n'
        f'RATIFIED_PIN = "{ratified_pin}"\n'
        "\n\n"
        "class K0:\n"
        "    members = (1, 2, 3, 4, 5, 6)\n",
        encoding="utf-8",
    )
    return init


def _run(
    workdir: Path, *, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the shipped ExecStart the way the unit does: from WorkingDirectory,
    in an environment systemd would supply (clean, plus ``HOME``)."""
    env = {"HOME": str(workdir), "PATH": "/usr/bin:/bin"}
    env.update(env_extra or {})
    return subprocess.run(
        _argv(), cwd=str(workdir), env=env, capture_output=True, text=True, timeout=30
    )


# ─────────────────── the command is runnable as written ───────────────────


def test_execstart_interpreter_exists() -> None:
    """The unit hard-codes an interpreter path; if it is wrong the unit cannot
    run at all, and every behavioural test below would be vacuous."""
    interp = Path(_argv()[0])
    assert interp.is_file(), f"ExecStart interpreter {interp} does not exist"


# ─────────────────── green: pins agree ───────────────────


def test_matching_pins_exit_zero_and_name_the_imported_file(tmp_path: Path) -> None:
    init = _write_k0(tmp_path, RATIFIED, RATIFIED)

    r = _run(tmp_path)

    assert r.returncode == 0, f"agreeing pins must exit 0; stderr={r.stderr}"
    assert r.stdout.startswith("k0-pin-ok "), r.stdout
    # the journal line has to prove WHICH tree was imported, not just that one was
    assert str(init) in r.stdout, r.stdout
    assert RATIFIED in r.stdout
    assert " 6 " in r.stdout, f"member count missing from success line: {r.stdout}"


# ─────────────────── red: pins disagree ───────────────────


def test_drifted_pins_exit_nonzero(tmp_path: Path) -> None:
    _write_k0(tmp_path, DRIFTED, RATIFIED)

    r = _run(tmp_path)

    assert r.returncode != 0, (
        "a drifted kernel MUST fail the unit; this exiting 0 is the false-green "
        f"the check exists to prevent. stdout={r.stdout}"
    )


def test_drift_message_names_both_pins_the_file_and_the_next_action(tmp_path: Path) -> None:
    """An operator reading `systemctl status` must be able to act without
    re-deriving anything: which pin was computed, which was ratified, which tree
    it came from, and what to do (executive_function axiom)."""
    init = _write_k0(tmp_path, DRIFTED, RATIFIED)

    r = _run(tmp_path)

    assert DRIFTED in r.stderr, f"computed pin missing: {r.stderr}"
    assert RATIFIED in r.stderr, f"ratified pin missing: {r.stderr}"
    assert str(init) in r.stderr, f"imported file missing: {r.stderr}"
    assert "re-derive the kernel" in r.stderr and "exclusion-ledger" in r.stderr, (
        f"failure text names no next action: {r.stderr}"
    )
    # and the drift is visible on stdout too, so a journal tail shows it
    assert r.stdout.startswith("k0-pin-drift "), r.stdout


def test_drift_still_fails_under_optimize(tmp_path: Path) -> None:
    """The regression that motivated the whole unit rewrite.

    ``PYTHONOPTIMIZE=1`` strips ``assert`` statements. The original ExecStart
    used one, so under ``-O`` a drifted kernel exited 0. This test is the reason
    the unit needs no ``Environment=PYTHONOPTIMIZE`` line: the predicate is
    proven to hold under optimization instead of being kept away from it.
    """
    _write_k0(tmp_path, DRIFTED, RATIFIED)

    r = _run(tmp_path, env_extra={"PYTHONOPTIMIZE": "1"})

    assert r.returncode != 0, (
        "drift exited 0 under -O: the exit predicate depends on assertions again"
    )
    assert DRIFTED in r.stderr and RATIFIED in r.stderr, r.stderr


@pytest.mark.parametrize("optimize", ["", "0", "1", "2"])
def test_exit_predicate_is_independent_of_pythonoptimize(tmp_path: Path, optimize: str) -> None:
    """Green stays green and red stays red at every optimization level, so an
    inherited value cannot change the verdict in either direction."""
    ok_dir = tmp_path / "ok"
    ok_dir.mkdir()
    _write_k0(ok_dir, RATIFIED, RATIFIED)
    assert _run(ok_dir, env_extra={"PYTHONOPTIMIZE": optimize}).returncode == 0

    drift_dir = tmp_path / "drift"
    drift_dir.mkdir()
    _write_k0(drift_dir, DRIFTED, RATIFIED)
    assert _run(drift_dir, env_extra={"PYTHONOPTIMIZE": optimize}).returncode != 0


# ─────────────────── the unit's own comments, measured ───────────────────


def test_no_assert_in_the_shipped_program() -> None:
    """Structural guard behind the behavioural ones: the check must not be
    expressed as an assertion, which ``-O`` deletes."""
    assert not re.search(r"\bassert\b", _program()), (
        "ExecStart uses `assert`; -O removes it and the check false-greens"
    )


def test_percent_specifiers_are_escaped_in_execstart() -> None:
    """``%s`` is a systemd specifier. Every ``%`` meant for Python must be
    doubled or systemd consumes it before Python sees the format string —
    corrupting the message on the branch nobody exercises by hand."""
    leftover = _raw_execstart().replace("%%", "")
    assert "%" not in leftover, (
        "unescaped `%` in ExecStart: systemd will expand it as a specifier. "
        f"Write `%%`. Offending remainder: {leftover!r}"
    )


def test_working_directory_wins_over_inherited_pythonpath(tmp_path: Path) -> None:
    """The unit dropped ``Environment=PYTHONPATH=`` on the claim that ``python
    -c`` puts the working directory first on ``sys.path``, so an inherited
    PYTHONPATH cannot shadow the pinned generation. Measured, not assumed."""
    pinned = tmp_path / "pinned"
    pinned.mkdir()
    init = _write_k0(pinned, RATIFIED, RATIFIED)

    shadow = tmp_path / "shadow"
    shadow.mkdir()
    _write_k0(shadow, DRIFTED, DRIFTED)

    r = _run(pinned, env_extra={"PYTHONPATH": str(shadow)})

    assert r.returncode == 0, r.stderr
    assert str(init) in r.stdout, (
        f"an inherited PYTHONPATH shadowed the working directory: {r.stdout}"
    )


def test_unit_declares_no_pythonpath_and_no_pythonoptimize() -> None:
    """Both were removed deliberately: PYTHONPATH because WorkingDirectory
    already wins (test above), PYTHONOPTIMIZE because nothing on this path
    asserts (tests above). Re-adding either would reintroduce a claim no test
    backs."""
    env = _service_values(UNIT.read_text(encoding="utf-8"), "Environment")
    names = {e.partition("=")[0] for e in env}
    assert "PYTHONPATH" not in names, "WorkingDirectory already wins; see the test above"
    assert "PYTHONOPTIMIZE" not in names, (
        "the exit predicate is proven under -O; pinning the level guards nothing"
    )


def test_unit_pins_the_deploy_root_not_a_developer_checkout() -> None:
    """The point of the unit is checking the PINNED generation. If it ran from a
    working tree it would report whatever the operator happens to have edited."""
    text = UNIT.read_text(encoding="utf-8")
    assert _service_values(text, "WorkingDirectory") == ["%h/.local/share/reins/current/api"]
    assert "AssertPathExists=%h/.local/share/reins/current/api/k0/manifest.py" in text
    assert "OnFailure=notify-failure@%n.service" in text


def test_unit_documents_no_unverifiable_vault_path() -> None:
    """A ``Documentation=`` pointing into the operator's home vault is not
    resolvable by anyone reading the unit, and drifts silently when the note
    moves. #4571 dropped it; keep it dropped."""
    assert "Documentation=" not in UNIT.read_text(encoding="utf-8")
