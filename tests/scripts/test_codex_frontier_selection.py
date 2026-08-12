"""The frontier selection guard, exercised as the shell fragment both launchers source.

The defect this pins is not "a wrong default". It is that two launchers made the same
choice from two copies, coordinated by a comment reading "keep in sync", and had already
diverged: hapax-codex grew a guard on 2026-08-10 and hapax-codex-headless kept
gpt-5.5/xhigh. So the tests assert BOTH that the guard behaves, and that neither launcher
carries its own literal any more.

Self-contained per the repo testing convention (no shared conftest fixtures).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = REPO_ROOT / "scripts" / "codex-frontier-selection.sh"
LAUNCHERS = (
    REPO_ROOT / "scripts" / "hapax-codex",
    REPO_ROOT / "scripts" / "hapax-codex-headless",
)

#: The pair verified from a measured rollout head on 2026-08-10, not a launcher self-report.
FRONTIER_MODEL = "gpt-5.6-sol"
FRONTIER_EFFORT = "ultra"


def _run(env_overrides: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Source the fragment in a clean bash and echo what it resolved."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        **env_overrides,
    }
    script = f'. "{FRAGMENT}"\nprintf "%s|%s\\n" "$CODEX_MODEL" "$CODEX_EFFORT"\n'
    return subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True, check=False
    )


def test_default_selection_is_the_frontier_pair(tmp_path: Path) -> None:
    result = _run({}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{FRONTIER_MODEL}|{FRONTIER_EFFORT}"


def test_below_frontier_without_a_reason_is_refused(tmp_path: Path) -> None:
    """Refuse, do not warn. An unstated downgrade is the exact failure this prevents."""
    result = _run({"HAPAX_CODEX_EFFORT": "low"}, tmp_path)
    assert result.returncode == 6
    assert "REFUSING a below-frontier selection" in result.stderr
    assert "HAPAX_CODEX_MODEL_REASON" in result.stderr


def test_below_frontier_model_without_a_reason_is_refused(tmp_path: Path) -> None:
    result = _run({"HAPAX_CODEX_MODEL": "gpt-5.5"}, tmp_path)
    assert result.returncode == 6
    assert "REFUSING a below-frontier selection" in result.stderr


def test_below_frontier_with_a_reason_proceeds_and_is_recorded(tmp_path: Path) -> None:
    """The reason is the artifact. Permitting without recording would lose the decision."""
    result = _run(
        {
            "HAPAX_CODEX_EFFORT": "low",
            "HAPAX_CODEX_MODEL_REASON": "mechanical sweep, no reasoning demand",
            "ROLE": "cx-test",
        },
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{FRONTIER_MODEL}|low"

    log = tmp_path / "cache" / "hapax" / "routing" / "model-decisions.jsonl"
    assert log.is_file(), "a permitted downgrade must leave a record"
    entry = log.read_text(encoding="utf-8").strip()
    assert '"effort":"low"' in entry
    assert '"reason":"mechanical sweep, no reasoning demand"' in entry
    assert f'"frontier_effort":"{FRONTIER_EFFORT}"' in entry


def test_raising_the_frontier_pair_moves_the_default(tmp_path: Path) -> None:
    """The point of the fragment: the pair is a decision point, not a constant."""
    result = _run(
        {"HAPAX_CODEX_FRONTIER_MODEL": "gpt-9", "HAPAX_CODEX_FRONTIER_EFFORT": "max"},
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "gpt-9|max"


def _run_with_extra(
    extra: list[str], tmp_path: Path, env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Source the fragment with a populated CODEX_EXTRA, as both launchers do."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        **(env_overrides or {}),
    }
    quoted = " ".join(f"'{a}'" for a in extra)
    script = (
        f"CODEX_EXTRA=({quoted})\n"
        f'. "{FRAGMENT}"\n'
        'printf "%s|%s\\n" "$CODEX_MODEL" "$CODEX_EFFORT"\n'
    )
    return subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True, check=False
    )


class TestPassthroughIsPartOfTheSelection:
    """The hole the guard had: `-c model=...` in passthrough wins at runtime.

    Both launchers append `"${CODEX_EXTRA[@]}"` after their own `-c model=`, and codex
    takes the last `-c` for a key. So a caller could override a selection this fragment
    had already validated, with no reason and no record — and the registry's Spark
    launcher already uses that form. Same defect as the one the fragment exists to fix,
    one layer out: a real check whose input set excluded the deciding state.
    """

    def test_passthrough_model_downgrade_is_refused(self, tmp_path: Path) -> None:
        result = _run_with_extra(["-c", 'model="gpt-5.5"'], tmp_path)
        assert result.returncode == 6, result.stdout + result.stderr
        assert "REFUSING a below-frontier selection" in result.stderr
        assert "gpt-5.5" in result.stderr, "the refusal must name what was actually requested"

    def test_passthrough_effort_downgrade_is_refused(self, tmp_path: Path) -> None:
        result = _run_with_extra(["-c", 'model_reasoning_effort="low"'], tmp_path)
        assert result.returncode == 6, result.stdout + result.stderr
        assert "effort=low" in result.stderr

    def test_passthrough_downgrade_with_a_reason_is_recorded(self, tmp_path: Path) -> None:
        result = _run_with_extra(
            ["-c", 'model="gpt-5.5"'],
            tmp_path,
            {"HAPAX_CODEX_MODEL_REASON": "spark launcher parity"},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"gpt-5.5|{FRONTIER_EFFORT}"
        log = tmp_path / "cache" / "hapax" / "routing" / "model-decisions.jsonl"
        assert log.is_file(), "a permitted passthrough downgrade must leave a record too"
        assert '"model":"gpt-5.5"' in log.read_text(encoding="utf-8")

    def test_unquoted_and_glued_config_forms_are_seen(self, tmp_path: Path) -> None:
        """`-c k=v`, `-ck=v`, `--config k=v` and `--config=k=v` are all codex-accepted."""
        for extra in (
            ["-c", "model=gpt-5.5"],
            ["-cmodel=gpt-5.5"],
            ["--config", 'model="gpt-5.5"'],
            ["--config=model=gpt-5.5"],
        ):
            result = _run_with_extra(extra, tmp_path)
            assert result.returncode == 6, f"{extra} slipped past the guard: {result.stdout}"

    def test_the_cli_model_flag_is_seen_in_every_spelling(self, tmp_path: Path) -> None:
        """`codex --help` lists `-m, --model <MODEL>` beside `-c, --config`.

        The first revision of the scanner read only the config spellings, so `-- --model gpt-5.5`
        walked past a guard written to stop exactly that. Two ways to say one thing, one of them
        checked — the same input-set defect the fragment itself exists to fix, a layer out.
        """
        for extra in (
            ["--model", "gpt-5.5"],
            ["-m", "gpt-5.5"],
            ["--model=gpt-5.5"],
            ["-mgpt-5.5"],
            ["--model", '"gpt-5.5"'],
        ):
            result = _run_with_extra(extra, tmp_path)
            assert result.returncode == 6, f"{extra} slipped past the guard: {result.stdout}"
            assert "gpt-5.5" in result.stderr

    def test_toml_whitespace_around_the_key_does_not_bypass(self, tmp_path: Path) -> None:
        """The key is TOML, so `model = "x"` is the same assignment as `model="x"`.

        Measured against codex 0.146 with `codex doctor`, which prints the effective config and
        spends nothing:

            codex -c 'model = "spaced"' doctor   -> spaced   (honoured — so it can bypass)
            codex -c '"model" = "q"'    doctor   -> ignored  (a QUOTED key has no effect)

        Hence normalisation of whitespace, and deliberately no handling of quoted keys: a guard
        that fired on a form codex ignores would be refusing something that cannot happen.
        """
        for extra in (
            ["-c", 'model = "gpt-5.5"'],
            ["-c", "  model  =  gpt-5.5  "],
            ["-c", 'model_reasoning_effort = "low"'],
            ["--config", 'model = "gpt-5.5"'],
        ):
            result = _run_with_extra(extra, tmp_path)
            assert result.returncode == 6, f"{extra} slipped past the guard: {result.stdout}"

    def test_a_quoted_key_is_not_refused_because_codex_ignores_it(self, tmp_path: Path) -> None:
        """The measurement above, pinned as behaviour.

        If a future codex starts honouring quoted keys this test goes red, which is the signal
        to widen the scanner — rather than the silence that would follow from having guessed.
        """
        result = _run_with_extra(["-c", '"model" = "gpt-5.5"'], tmp_path)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"{FRONTIER_MODEL}|{FRONTIER_EFFORT}"

    def test_the_cli_model_flag_at_the_frontier_is_not_a_downgrade(self, tmp_path: Path) -> None:
        result = _run_with_extra(["--model", FRONTIER_MODEL], tmp_path)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"{FRONTIER_MODEL}|{FRONTIER_EFFORT}"

    def test_a_profile_is_refused_because_it_cannot_be_resolved_here(self, tmp_path: Path) -> None:
        """`-p/--profile` names a config.toml block that may set model or effort to anything.

        Resolving it would mean parsing a file outside the repo and reimplementing codex's
        precedence rules. A guard that GUESSES the effective model is worse than one that says it
        cannot see it, so a profile must state its reason — the fail-closed direction.
        """
        for extra in (["--profile", "fast"], ["-p", "fast"], ["--profile=fast"]):
            result = _run_with_extra(extra, tmp_path)
            assert result.returncode == 6, f"{extra} was not refused: {result.stdout}"
            assert "REFUSING --profile" in result.stderr
            assert "fast" in result.stderr

    def test_a_profile_with_a_stated_reason_proceeds(self, tmp_path: Path) -> None:
        result = _run_with_extra(
            ["--profile", "fast"], tmp_path, {"HAPAX_CODEX_MODEL_REASON": "operator-pinned profile"}
        )
        assert result.returncode == 0, result.stderr

    def test_passthrough_at_the_frontier_pair_is_not_refused(self, tmp_path: Path) -> None:
        """Precision: naming the frontier explicitly is not a downgrade."""
        result = _run_with_extra(["-c", f'model="{FRONTIER_MODEL}"'], tmp_path)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"{FRONTIER_MODEL}|{FRONTIER_EFFORT}"

    def test_unrelated_passthrough_config_is_ignored(self, tmp_path: Path) -> None:
        """Only the two keys that decide the selection are consumed."""
        result = _run_with_extra(["-c", 'approval_policy="never"', "--", "some prompt"], tmp_path)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"{FRONTIER_MODEL}|{FRONTIER_EFFORT}"

    def test_an_absent_codex_extra_still_works(self, tmp_path: Path) -> None:
        """The fragment is sourced by callers that never set CODEX_EXTRA at all."""
        result = _run({}, tmp_path)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"{FRONTIER_MODEL}|{FRONTIER_EFFORT}"


class TestRecordBeforeProceedIsAPredicate:
    """ "The reason is the artifact" has to mean the artifact exists.

    The first revision wrote the decision log with `2>/dev/null || true` on both the mkdir and
    the append, printed "recorded", and continued. A read-only cache or a full disk therefore
    produced an UNRECORDED downgrade that announced itself as recorded — the stated predicate
    and the behaviour disagreed, and the behaviour was the permissive one.
    """

    def test_an_unwritable_log_directory_refuses_the_downgrade(self, tmp_path: Path) -> None:
        import os

        cache = tmp_path / "cache"
        cache.mkdir()
        os.chmod(cache, 0o500)  # readable, not writable
        try:
            result = _run(
                {
                    "HAPAX_CODEX_EFFORT": "low",
                    "HAPAX_CODEX_MODEL_REASON": "mechanical sweep",
                    "XDG_CACHE_HOME": str(cache),
                },
                tmp_path,
            )
            assert result.returncode == 7, result.stdout + result.stderr
            assert "REFUSING the downgrade" in result.stderr
            assert "XDG_CACHE_HOME" in result.stderr, "the refusal must name its own remedy"
        finally:
            os.chmod(cache, 0o700)

    def test_a_writable_log_still_permits_the_downgrade(self, tmp_path: Path) -> None:
        """The other direction: this must not have become a blanket refusal."""
        result = _run(
            {"HAPAX_CODEX_EFFORT": "low", "HAPAX_CODEX_MODEL_REASON": "mechanical sweep"},
            tmp_path,
        )
        assert result.returncode == 0, result.stderr

    def test_a_reason_with_a_newline_does_not_corrupt_the_log(self, tmp_path: Path) -> None:
        """One downgrade is one JSONL record. A raw newline in the reason would split it in
        two, and the second half would not parse — corrupting the audit trail the record is
        written to protect."""
        import json

        result = _run(
            {
                "HAPAX_CODEX_EFFORT": "low",
                "HAPAX_CODEX_MODEL_REASON": 'sweep\nwith a newline and a " quote',
            },
            tmp_path,
        )
        assert result.returncode == 0, result.stderr
        log = tmp_path / "cache" / "hapax" / "routing" / "model-decisions.jsonl"
        body = log.read_text(encoding="utf-8").strip()
        assert len(body.splitlines()) == 1, "one downgrade must be exactly one record"
        assert json.loads(body)["effort"] == "low"


def test_launchers_populate_passthrough_before_sourcing_the_fragment() -> None:
    """The ordering the passthrough check depends on, pinned in both launchers.

    The fragment can only fold passthrough overrides in if CODEX_EXTRA is already populated when
    it is sourced. Nothing else would notice if an edit moved the source line above the argument
    parse — the guard would simply stop seeing overrides, silently, which is the failure mode
    this whole file exists to prevent.

    Reviewed weakness, fixed here: an earlier version matched only ``CODEX_EXTRA+=(``, so a
    launcher rewritten to assign (``CODEX_EXTRA=("$@")``) would have failed with "no longer
    populates" — an error that reads like a broken test rather than the reordering it actually
    is. Both spellings count now, and the failure message says which invariant broke.

    This is a structural check because the alternative is not better. Driving a launcher for
    real needs SIX governance preconditions stubbed — the enable flag, a worktree, an executable
    hook adapter, the `HAPAX_CODEX_EXEC_AUTH_OK` sentinel, a cc-claim, and more past that — and
    such a test would break on every preflight change while asserting almost nothing about
    selection. Measured, not assumed: each precondition above was hit in turn while attempting
    it, and one of them exits 6, the *same code* as the frontier refusal, so a naive end-to-end
    assertion on the exit status would have passed for entirely the wrong reason.
    """
    for launcher in LAUNCHERS:
        lines = launcher.read_text(encoding="utf-8").splitlines()
        populates = [
            i
            for i, ln in enumerate(lines)
            if "CODEX_EXTRA+=(" in ln or "CODEX_EXTRA=(" in ln.replace(" ", "")
        ]
        sources = [
            i
            for i, ln in enumerate(lines)
            if "codex-frontier-selection.sh" in ln and ln.lstrip().startswith(".")
        ]
        assert populates, f"{launcher.name} no longer populates CODEX_EXTRA at all"
        assert sources, f"{launcher.name} no longer sources the fragment"
        assert max(populates) < min(sources), (
            f"{launcher.name} sources the frontier fragment at line {min(sources) + 1}, before "
            f"CODEX_EXTRA is finished being populated at line {max(populates) + 1}. Passthrough "
            "overrides would bypass the guard."
        )


def test_no_launcher_carries_its_own_model_or_effort_literal() -> None:
    """The regression that actually happened: one copy moved and the other did not.

    A launcher that hardcodes the pair again silently reintroduces the divergence, and
    nothing else in the suite would notice.
    """
    for launcher in LAUNCHERS:
        text = launcher.read_text(encoding="utf-8")
        assert "codex-frontier-selection.sh" in text, f"{launcher.name} must source the fragment"
        for literal in ('model=\\"gpt-', 'model_reasoning_effort=\\"xhigh', "'model=\"gpt-"):
            assert literal not in text, f"{launcher.name} reintroduced a hardcoded pair: {literal}"
