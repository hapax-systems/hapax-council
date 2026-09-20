"""Red/green witness for the K0 ratified-pin check unit (R0.4).

``hapax-k0-kernel-pin-check.service`` is a one-line guard: import the pinned K0
generation and refuse if the computed drift pin has moved away from the ratified
one. Its whole value is the FAILURE branch, and until this module existed that
branch was evidenced only by a one-off ``systemctl --user start`` transcript in a
PR body — the success path was witnessed and the failure path was asserted. Two
reviewers said so independently (PR #4571, ``exit-predicate-adequacy``).

So these tests build a miniature estate under a temp ``HOME``, place a
fabricated ``k0`` at the unit's OWN ``WorkingDirectory``, and run the unit's OWN
``ExecStart`` under the unit's OWN ``Environment=`` block. Nothing about the
invocation is retyped, so the unit cannot drift away from what is tested here.

Four regressions are pinned, each of which previously shipped:

1. **A stripped assertion.** The original ExecStart spelled the check
   ``assert k0.K0_DRIFT_PIN == k0.RATIFIED_PIN``. Under ``-O`` that statement is
   removed and a drifted kernel exits 0 — the check false-greens exactly when it
   matters. The fix was an explicit ``SystemExit``, and
   ``test_exit_predicate_is_independent_of_pythonoptimize`` is what keeps it
   explicit.

   An earlier revision instead set ``Environment=PYTHONOPTIMIZE=0``, on the
   belief that CPython reads any non-empty value as ``-O``. That is the pre-3.8
   ``add_flag()`` behaviour and is not what this interpreter does — measured on
   CPython 3.14.4, ``PYTHONOPTIMIZE=0`` leaves ``sys.flags.optimize`` at 0. The
   line was dropped because it guards nothing, not because it misbehaved. An env
   var is a hope; the ``-O`` runs below are a witness, and they hold whatever the
   caller's environment says.

2. **A shadowed import.** A revision of this unit dropped
   ``Environment=PYTHONPATH=`` on the claim that ``python -c`` always puts the
   working directory first on ``sys.path``. It does not: **any non-empty
   ``PYTHONSAFEPATH`` — including the string ``"0"`` — removes the working
   directory**, after which an inherited ``PYTHONPATH`` decides which ``k0`` is
   imported and the pin check silently validates the wrong tree. Measured on
   CPython 3.14.4. The unit therefore names the pinned tree explicitly, and
   ``test_pinned_tree_wins_over_inherited_pythonpath`` runs the hostile
   environment rather than reasoning about it.

3. **A specifier systemd ate.** ``%s`` is a systemd specifier (user shell), so
   the failure message's ``%s`` placeholders had to be written ``%%s``. Getting
   that wrong corrupts the message only on the branch nobody exercises.

4. **A silent success.** The success line must name ``k0.__file__``, or a green
   journal proves only that *some* kernel matched itself.

Recheck::

    uv run pytest tests/systemd/test_k0_kernel_pin_check_unit.py -q

Mutation-check (each must turn this module red): put ``assert`` back in the
ExecStart; single one of the ``%%s``; delete the ``Environment=PYTHONPATH=``
line.
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
SHADOW_PIN = "f" * 64


# ─────────────────── read the unit, do not retype it ───────────────────


def _values(section: str, key: str) -> list[str]:
    """Values of ``key`` in ``section``, comments excluded."""
    in_section = False
    out: list[str] = []
    for line in UNIT.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_section = s == f"[{section}]"
            continue
        if not in_section or not s or s.startswith(("#", ";")) or "=" not in s:
            continue
        k, _, v = s.partition("=")
        if k.strip() == key:
            out.append(v.strip())
    return out


def _raw_execstart() -> str:
    values = _values("Service", "ExecStart")
    assert len(values) == 1, f"expected exactly one ExecStart, got {len(values)}"
    return values[0]


def _argv() -> list[str]:
    """The ExecStart as systemd hands it to ``execve``.

    systemd expands ``%%`` to a literal ``%`` and then splits on whitespace with
    quote grouping. Doing both here is what makes the tests exercise the shipped
    command rather than a copy of it that could drift.
    """
    return shlex.split(_raw_execstart().replace("%%", "%"))


def _program() -> str:
    argv = _argv()
    assert argv[1] == "-c", f"expected `python3 -c <program>`, got {argv[:2]}"
    return argv[2]


def _working_directory(home: Path) -> Path:
    values = _values("Service", "WorkingDirectory")
    assert len(values) == 1, f"expected exactly one WorkingDirectory, got {values}"
    return Path(values[0].replace("%h", str(home)))


def _unit_environment(home: Path) -> dict[str, str]:
    """The unit's own ``Environment=`` assignments, with ``%h`` resolved.

    Applying these rather than hand-writing an environment is what lets the
    tests witness the unit's configuration. The unit pins ``PYTHONPATH``
    precisely so an inherited value cannot decide which ``k0`` is imported; a
    harness that ignored the line could not tell whether that works.
    """
    env: dict[str, str] = {}
    for assignment in _values("Service", "Environment"):
        name, _, value = assignment.partition("=")
        env[name.strip()] = value.strip().replace("%h", str(home))
    return env


# ─────────────────── build the estate the unit expects ───────────────────


def _estate(home: Path, drift_pin: str, ratified_pin: str) -> Path:
    """Create a stand-in pinned generation at the unit's own WorkingDirectory."""
    return _k0_at(_working_directory(home), drift_pin, ratified_pin)


def _k0_at(parent: Path, drift_pin: str, ratified_pin: str) -> Path:
    pkg = parent / "k0"
    pkg.mkdir(parents=True, exist_ok=True)
    # AssertPathExists= names manifest.py, so the modelled tree carries one too.
    pkg.joinpath("manifest.py").write_text("", encoding="utf-8")
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
    home: Path, *, inherited: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the shipped ExecStart the way systemd does.

    ``inherited`` is the ambient environment the user manager might hand down;
    the unit's own ``Environment=`` lines are layered ON TOP, exactly as systemd
    orders them. A hostile inherited value is therefore only defeated if the
    unit actually overrides it.
    """
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    env.update(inherited or {})
    env.update(_unit_environment(home))
    return subprocess.run(
        _argv(),
        cwd=str(_working_directory(home)),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ─────────────────── the command is runnable as written ───────────────────


def test_execstart_interpreter_exists() -> None:
    """The unit hard-codes an interpreter path; if it is wrong the unit cannot
    run at all, and every behavioural test below would be vacuous."""
    interp = Path(_argv()[0])
    assert interp.is_file(), f"ExecStart interpreter {interp} does not exist"


def test_assert_path_exists_names_the_working_directory_tree(tmp_path: Path) -> None:
    """``AssertPathExists=`` must guard the tree the unit actually imports from,
    or systemd would admit a run whose import target is missing."""
    _estate(tmp_path, RATIFIED, RATIFIED)
    guarded = [v.replace("%h", str(tmp_path)) for v in _values("Unit", "AssertPathExists")]
    assert guarded, "unit declares no AssertPathExists"
    for path in guarded:
        assert Path(path).exists(), f"AssertPathExists names {path}, absent from the imported tree"
        assert path.startswith(str(_working_directory(tmp_path))), (
            f"AssertPathExists guards {path}, which is not under WorkingDirectory"
        )


# ─────────────────── green: pins agree ───────────────────


def test_matching_pins_exit_zero_and_name_the_imported_file(tmp_path: Path) -> None:
    init = _estate(tmp_path, RATIFIED, RATIFIED)

    r = _run(tmp_path)

    assert r.returncode == 0, f"agreeing pins must exit 0; stderr={r.stderr}"
    assert r.stdout.startswith("k0-pin-ok "), r.stdout
    # the journal line has to prove WHICH tree was imported, not just that one was
    assert str(init) in r.stdout, r.stdout
    assert RATIFIED in r.stdout
    assert " 6 " in r.stdout, f"member count missing from success line: {r.stdout}"


# ─────────────────── red: pins disagree ───────────────────


def test_drifted_pins_exit_nonzero(tmp_path: Path) -> None:
    _estate(tmp_path, DRIFTED, RATIFIED)

    r = _run(tmp_path)

    assert r.returncode != 0, (
        "a drifted kernel MUST fail the unit; this exiting 0 is the false-green "
        f"the check exists to prevent. stdout={r.stdout}"
    )


def test_drift_message_names_both_pins_the_file_and_the_next_action(tmp_path: Path) -> None:
    """An operator reading `systemctl status` must be able to act without
    re-deriving anything: which pin was computed, which was ratified, which tree
    it came from, and what to do (executive_function axiom)."""
    init = _estate(tmp_path, DRIFTED, RATIFIED)

    r = _run(tmp_path)

    assert DRIFTED in r.stderr, f"computed pin missing: {r.stderr}"
    assert RATIFIED in r.stderr, f"ratified pin missing: {r.stderr}"
    assert str(init) in r.stderr, f"imported file missing: {r.stderr}"
    assert "re-derive the kernel" in r.stderr and "exclusion-ledger" in r.stderr, (
        f"failure text names no next action: {r.stderr}"
    )
    # and the drift is visible on stdout too, so a journal tail shows it
    assert r.stdout.startswith("k0-pin-drift "), r.stdout


@pytest.mark.parametrize("optimize", ["", "0", "1", "2"])
def test_exit_predicate_is_independent_of_pythonoptimize(tmp_path: Path, optimize: str) -> None:
    """``PYTHONOPTIMIZE=1`` deletes ``assert`` statements, and the original
    ExecStart used one — so under ``-O`` a drifted kernel exited 0. Green stays
    green and red stays red at every level, so no inherited value can change the
    verdict in either direction."""
    ok_home = tmp_path / "ok"
    _estate(ok_home, RATIFIED, RATIFIED)
    assert _run(ok_home, inherited={"PYTHONOPTIMIZE": optimize}).returncode == 0

    drift_home = tmp_path / "drift"
    _estate(drift_home, DRIFTED, RATIFIED)
    drift = _run(drift_home, inherited={"PYTHONOPTIMIZE": optimize})
    assert drift.returncode != 0, (
        f"drift exited 0 at PYTHONOPTIMIZE={optimize!r}: the exit predicate "
        "depends on assertions again"
    )
    assert DRIFTED in drift.stderr and RATIFIED in drift.stderr, drift.stderr


# ─────────────────── which tree gets imported ───────────────────


@pytest.mark.parametrize("safepath", ["", "0", "1"])
def test_pinned_tree_wins_over_inherited_pythonpath(tmp_path: Path, safepath: str) -> None:
    """The unit must import the ratified generation whatever the environment says.

    ``python -c`` normally puts the working directory first on ``sys.path``, but
    any NON-EMPTY ``PYTHONSAFEPATH`` — ``"0"`` included — drops it, and an
    inherited ``PYTHONPATH`` then wins. Measured on CPython 3.14.4. The decoy's
    pins DISAGREE with each other, so a shadowed import shows up twice over: as a
    non-zero exit and as the wrong path on stdout. One signal would leave the
    other free to rot.
    """
    init = _estate(tmp_path, RATIFIED, RATIFIED)
    shadow = tmp_path / "shadow"
    shadow_init = _k0_at(shadow, SHADOW_PIN, RATIFIED)

    r = _run(tmp_path, inherited={"PYTHONPATH": str(shadow), "PYTHONSAFEPATH": safepath})

    assert r.returncode == 0, (
        f"PYTHONSAFEPATH={safepath!r} let an inherited PYTHONPATH shadow the "
        f"pinned generation — the pin check validated the wrong tree. stderr={r.stderr}"
    )
    assert str(init) in r.stdout, f"imported the wrong tree: {r.stdout}"
    assert str(shadow_init) not in r.stdout, f"imported the decoy: {r.stdout}"


def test_unit_pins_pythonpath_to_the_deploy_root() -> None:
    """The behavioural test above passes only because this line exists. Pin it
    directly too, so deleting it fails with a reason rather than a symptom."""
    env = _unit_environment(Path("/HOME"))
    assert env.get("PYTHONPATH") == "/HOME/.local/share/reins/current/api", (
        "unit must name the pinned tree on PYTHONPATH; without it a non-empty "
        f"PYTHONSAFEPATH lets an inherited value choose the kernel. got: {env.get('PYTHONPATH')}"
    )
    assert "PYTHONOPTIMIZE" not in env, (
        "the exit predicate is proven under -O; pinning the level guards nothing"
    )


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


def test_unit_pins_the_deploy_root_not_a_developer_checkout() -> None:
    """The point of the unit is checking the PINNED generation. If it ran from a
    working tree it would report whatever the operator happens to have edited."""
    text = UNIT.read_text(encoding="utf-8")
    assert _values("Service", "WorkingDirectory") == ["%h/.local/share/reins/current/api"]
    assert "AssertPathExists=%h/.local/share/reins/current/api/k0/manifest.py" in text
    assert "OnFailure=notify-failure@%n.service" in text


def test_unit_documents_no_unverifiable_vault_path() -> None:
    """A ``Documentation=`` pointing into the operator's home vault is not
    resolvable by anyone reading the unit, and drifts silently when the note
    moves. #4571 dropped it; keep it dropped."""
    assert "Documentation=" not in UNIT.read_text(encoding="utf-8")
