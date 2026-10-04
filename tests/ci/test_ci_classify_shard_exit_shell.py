from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ci_classify_shard_exit.sh"

# The specimen: CI run 36369340992, ``test-full-shard (3/4)``, 2026-09-28 (job
# 108762193345), read from the job's own log with its timestamps stripped — the
# real progress lines, the real post-session unraisable traceback, and the
# selector error the merge group was actually shown. Every test that reported
# had passed; the wrapper then killed the shard.
#
# The measured marker count for this fixture is 648. The regex that used to
# live inline in the workflow ("the line starts with a progress character")
# counts 672 here — it invents 24 tests out of the
# traceback continuation, the ``Enable tracemalloc`` line and the
# ``....Could not write`` line. On the full job log that error is 227 invented
# tests (10739 against 10512).
SPECIMEN_OUTPUT = """\
........................................................................ [ 94%]
........................................................................ [ 95%]
........................................................................ [ 95%]
........................................................................ [ 96%]
........................................................................ [ 97%]
........................................................................ [ 97%]
........................................................................ [ 98%]
........................................................................ [ 99%]
........................................................................ [ 99%]
....................venv/lib/python3.12/site-packages/_pytest/unraisableexception.py:67: PytestUnraisableExceptionWarning: Exception ignored in: <function BaseEventLoop.__del__ at 0x7f9b5f777060>
Traceback (most recent call last):
  File "/usr/lib/python3.12/asyncio/base_events.py", line 728, in __del__
    self.close()
  File "/usr/lib/python3.12/asyncio/unix_events.py", line 68, in close
    super().close()
  File "/usr/lib/python3.12/asyncio/selector_events.py", line 104, in close
    self._close_self_pipe()
  File "/usr/lib/python3.12/asyncio/selector_events.py", line 111, in _close_self_pipe
    self._remove_reader(self._ssock.fileno())
  File "/usr/lib/python3.12/asyncio/selector_events.py", line 298, in _remove_reader
    key = self._selector.get_key(fd)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/selectors.py", line 190, in get_key
    return mapping[fileobj]
           ~~~~~~~^^^^^^^^^
  File "/usr/lib/python3.12/selectors.py", line 71, in __getitem__
    fd = self._selector._fileobj_lookup(fileobj)
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/selectors.py", line 225, in _fileobj_lookup
    return _fileobj_to_fd(fileobj)
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/selectors.py", line 42, in _fileobj_to_fd
    raise ValueError("Invalid file descriptor: {}".format(fd))
ValueError: Invalid file descriptor: -1

Enable tracemalloc to get traceback where the object was allocated.
See https://docs.pytest.org/en/stable/how-to/capture-warnings.html#resource-warnings for more info.
  warnings.warn(pytest.PytestUnraisableExceptionWarning(msg))
ci_select_pytest_shard.py: error: no pytest duration lines were found
....Could not write pytest node duration artifact (exit 2)
"""


def _run(
    pytest_exit: str, artifact_exit: str, output: str, tmp_path: Path
) -> subprocess.CompletedProcess[str]:
    output_file = tmp_path / "pytest-output.txt"
    output_file.write_text(output, encoding="utf-8")
    stdout = tmp_path / "stdout.txt"
    stderr = tmp_path / "stderr.txt"
    with stdout.open("w", encoding="utf-8") as out, stderr.open("w", encoding="utf-8") as err:
        completed = subprocess.run(
            ["bash", str(SCRIPT), pytest_exit, artifact_exit, str(output_file)],
            check=False,
            stdout=out,
            stderr=err,
        )
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        stdout.read_text(encoding="utf-8"),
        stderr.read_text(encoding="utf-8"),
    )


def test_specimen_kill_is_reported_as_a_kill_not_a_test_failure(tmp_path: Path) -> None:
    result = _run("137", "0", SPECIMEN_OUTPUT, tmp_path)

    assert result.returncode == 1
    assert "648 progress markers (lower bound" in result.stdout
    assert "SIGKILL (137)" in result.stdout
    assert "NOT a test failure" not in result.stdout
    assert "unknown" in result.stdout
    # The in-flight window is the tail of the killed output, not a fabricated list.
    assert "PytestUnraisableExceptionWarning(msg)" in result.stdout
    assert "Tests failed" not in result.stdout


def test_completed_markers_exclude_lines_that_only_begin_with_marker_characters(
    tmp_path: Path,
) -> None:
    """glm's hazard: a traceback line that starts with a marker character."""
    output = (
        "........................................................................ [ 50%]\n"
        "...................PytestUnraisableExceptionWarning: Exception ignored in: <function BaseEventLoop.__del__>\n"
        "Enable tracemalloc to get traceback where the object was allocated.\n"
        "....Could not write pytest node duration artifact (exit 2)\n"
    )

    result = _run("137", "0", output, tmp_path)

    # Exactly the one complete progress line: 72, not 72 + 19 + 1 + 4.
    assert "72 progress markers (lower bound" in result.stdout
    assert "after 96 tests" not in result.stdout


def test_exit_124_is_classified_as_a_kill(tmp_path: Path) -> None:
    result = _run("124", "0", SPECIMEN_OUTPUT, tmp_path)

    assert "timeout exit 124" in result.stdout
    assert "Tests failed" not in result.stdout


def test_artifact_failure_is_tolerated_only_when_the_shard_was_killed(
    tmp_path: Path,
) -> None:
    # A synthetic killed run here rather than the specimen: the specimen's
    # in-flight tail contains the ``....Could not write`` line verbatim, which
    # would make the assertion below ambiguous about who said it.
    killed = _run(
        "137",
        "2",
        "........................................................................ [ 50%]\n",
        tmp_path,
    )
    assert killed.returncode == 1
    assert "SIGKILL (137)" in killed.stdout
    assert "secondary" in killed.stdout
    assert "Could not write pytest node duration artifact" not in killed.stdout
    assert "Could not write pytest node duration artifact" not in killed.stderr

    passed = _run("0", "2", "5 passed in 1.0s\n", tmp_path)
    assert passed.returncode == 1
    assert "Could not write pytest node duration artifact (exit 2)" in passed.stdout


def test_passing_suite_exits_zero(tmp_path: Path) -> None:
    result = _run("0", "0", "1234 passed in 300.00s\n", tmp_path)

    assert result.returncode == 0
    assert "All tests passed (pytest exit 0)" in result.stdout


def test_a_success_without_a_summary_is_not_reported_as_a_pass(tmp_path: Path) -> None:
    result = _run("0", "0", "collected 10 items\n", tmp_path)

    assert result.returncode == 1
    assert "No test summary found" in result.stdout


def test_missing_output_file_is_a_usage_error(tmp_path: Path) -> None:
    completed = subprocess.run(
        ["bash", str(SCRIPT), "137", "0", str(tmp_path / "absent.txt")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "no such pytest output file" in completed.stderr


def test_mixed_failure_markers_and_kill_are_separate_facts(tmp_path):
    result = _run("137", "2", "..F.E... [ 20%]\n", tmp_path)
    assert "Observed F/E progress marker" in result.stdout
    assert "SIGKILL (137)" in result.stdout
    assert "NOT a test failure" not in result.stdout
    assert "no test result was withheld or lost" not in result.stdout


def test_tee_failure_cannot_certify_passing_pytest(tmp_path, monkeypatch):
    monkeypatch.setenv("HAPAX_CI_PIPELINE_EXIT", "1")
    result = _run("0", "0", "1 passed in 0.1s\n", tmp_path)
    assert result.returncode == 1
    assert "Output pipeline failed" in result.stdout
