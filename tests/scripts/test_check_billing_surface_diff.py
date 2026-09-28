"""Tests for the git-validated provider-billing surface scanner.

Two families, both through the FULL entry point (``main``, not a helper):

- the detectors, marker contract and proxy exemption ported from #4795/#4808;
- every malformed-input shape those reviews found, which must now exit NONZERO: the scanner applies
  the input with git first, so a shape git will not apply is refused instead of parsed permissively.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-billing-surface-diff.py"
_spec = importlib.util.spec_from_file_location(
    "billing_scanner_under_test",
    SCRIPT,
    loader=importlib.machinery.SourceFileLoader("billing_scanner_under_test", str(SCRIPT)),
)
assert _spec and _spec.loader
scanner = importlib.util.module_from_spec(_spec)
# Register before executing: the module's dataclasses resolve their own ``__module__`` through
# ``sys.modules``, and an unregistered module makes that lookup fail at class creation.
sys.modules[_spec.name] = scanner
_spec.loader.exec_module(scanner)

KEY_LINE = 'client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])'


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr}"
    return proc.stdout


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _fixture(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A repo with a base commit and a head that adds a credential route. Returns repo/base/head/diff."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", ".")
    (repo / "app.py").write_text("import os\n\nvalue = 1\n")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "f.txt").write_text("fixture\n")
    base = _commit(repo, "base")
    (repo / "app.py").write_text(f"import os\nfrom openai import OpenAI\n{KEY_LINE}\n")
    head = _commit(repo, "head")
    diff = _git(repo, "diff", "--find-renames", "--unified=0", f"{base}...{head}")
    return repo, base, head, diff


def _run(
    repo: Path, base: str, *, diff_text: str | None = None, diff_file: Path | None = None
) -> subprocess.CompletedProcess[str]:
    argv = [sys.executable, str(SCRIPT), "--repo", str(repo), "--base", base]
    if diff_file is not None:
        argv += ["--diff-file", str(diff_file)]
    else:
        argv += ["--head", _git(repo, "rev-parse", "HEAD").strip()]
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def _run_text(repo: Path, base: str, tmp_path: Path, text: str) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "case.diff"
    path.write_text(text, encoding="utf-8")
    return _run(repo, base, diff_file=path)


# ── detectors, marker contract, proxy exemption (ported) ─────────────


def test_a_credential_route_on_an_added_line_is_a_finding(tmp_path: Path) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    result = _run(repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "api-key-route" in result.stdout
    assert "credential-env-read" in result.stdout


def test_a_change_without_a_billing_surface_is_clean(tmp_path: Path) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "app.py").write_text("import os\n\nvalue = 2\n")
    _commit(repo, "clean")
    result = _run(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_a_doc_change_is_skipped(tmp_path: Path) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "notes.md").write_text(f"{KEY_LINE}\n")
    _commit(repo, "docs")
    result = _run(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_marker_on_the_findings_own_line_in_a_fixture_is_allowed(tmp_path: Path) -> None:
    """The marker's contract is exactly the MARKED line, so the fixture puts it there."""
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "tests" / "gen.py").write_text("client = OpenAI(api_key=key)  # billing-scan:allow\n")
    _commit(repo, "fixture")
    result = _run(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "allowed tests/gen.py:1" in result.stdout


def test_a_marker_on_a_neighbour_line_does_not_exempt_the_finding(tmp_path: Path) -> None:
    """#4808 r2/r3's leak: a marker on one line must never speak for another line's finding."""
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "tests" / "gen.py").write_text("client = OpenAI(api_key=key)\n# billing-scan:allow\n")
    _commit(repo, "neighbour marker")
    result = _run(repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "api-key-route" in result.stdout
    assert "allowed" not in result.stdout


def test_a_marker_outside_the_allowlist_is_itself_a_finding(tmp_path: Path) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "app.py").write_text("client = OpenAI(api_key=key)  # billing-scan:allow\n")
    _commit(repo, "marker abroad")
    result = _run(repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "marker" in result.stdout
    assert "api-key-route" in result.stdout


def test_a_governed_proxy_route_is_exempt_per_call(tmp_path: Path) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "app.py").write_text(
        'from openai import OpenAI\nOpenAI(api_key=key, base_url="http://127.0.0.1:4000")\n'
    )
    _commit(repo, "proxy")
    result = _run(repo, base)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "governed-proxy-route" in result.stdout


def test_an_env_read_inside_a_proxy_bound_call_is_still_its_own_site(tmp_path: Path) -> None:
    """The exemption is per call for the api-key class; the credential READ is its own node."""
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "app.py").write_text(
        "from openai import OpenAI\n"
        'OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url="http://127.0.0.1:4000")\n'
    )
    _commit(repo, "proxy with env read")
    result = _run(repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "governed-proxy-route" in result.stdout
    assert "credential-env-read" in result.stdout


def test_a_dynamic_proxy_target_is_not_a_binding(tmp_path: Path) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "app.py").write_text(
        "from openai import OpenAI\n"
        "host = '127.0.0.1'\n"
        'OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=f"http://{host}:4000")\n'
    )
    _commit(repo, "dynamic")
    result = _run(repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "api-key-route" in result.stdout


# ── malformed input: every shape must exit NONZERO ───────────────────


def test_a_truncation_at_every_line_prefix_is_refused(tmp_path: Path) -> None:
    repo, base, _head, diff = _fixture(tmp_path)
    lines = diff.splitlines()
    for cut in range(1, len(lines)):
        result = _run_text(repo, base, tmp_path, "\n".join(lines[:cut]) + "\n")
        assert result.returncode != 0, f"cut={cut} scanned clean:\n{result.stdout}"


def test_a_truncation_at_every_character_prefix_never_scans_the_key_line(
    tmp_path: Path,
) -> None:
    """Character-level truncation: nonzero, or the key-bearing line is genuinely gone."""
    repo, base, _head, diff = _fixture(tmp_path)
    for cut in range(0, len(diff), 7):
        text = diff[:cut]
        result = _run_text(repo, base, tmp_path, text)
        if result.returncode == 0:
            assert "OPENAI_API_KEY" not in text, f"cut={cut} scanned clean over the key line"


def test_a_headerless_hunk_is_never_a_clean_scan(tmp_path: Path) -> None:
    repo, base, _head, diff = _fixture(tmp_path)
    stripped = "\n".join(l for l in diff.splitlines() if not l.startswith("diff --git"))
    result = _run_text(repo, base, tmp_path, stripped + "\n")
    assert result.returncode != 0, result.stdout + result.stderr


def test_a_ppp_header_without_diff_git_is_never_a_clean_scan(tmp_path: Path) -> None:
    repo, base, _head, diff = _fixture(tmp_path)
    stripped = "\n".join(
        l for l in diff.splitlines() if not l.startswith(("diff --git", "index ", "--- "))
    )
    result = _run_text(repo, base, tmp_path, stripped + "\n")
    assert result.returncode != 0, result.stdout + result.stderr


def test_a_binary_note_after_a_hunk_is_never_a_clean_scan(tmp_path: Path) -> None:
    """#4808 r3's leak: the note made the old parser treat the credential line as binary payload."""
    repo, base, _head, diff = _fixture(tmp_path)
    lines = diff.splitlines()
    poisoned = (
        "\n".join(lines[:3])
        + "\nBinary files a/app.py and b/app.py differ\n"
        + "\n".join(lines[3:])
        + "\n"
    )
    result = _run_text(repo, base, tmp_path, poisoned)
    assert result.returncode != 0, result.stdout + result.stderr
    trailing = "\n".join(lines) + "\nBinary files a/app.py and b/app.py differ\n"
    result = _run_text(repo, base, tmp_path, trailing)
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize("drop", (1, 2, 3))
def test_deleting_a_header_line_is_never_a_clean_scan(tmp_path: Path, drop: int) -> None:
    repo, base, _head, diff = _fixture(tmp_path)
    lines = diff.splitlines()
    kept = lines[: drop - 1] + lines[drop:]
    result = _run_text(repo, base, tmp_path, "\n".join(kept) + "\n")
    assert result.returncode != 0, result.stdout + result.stderr


def test_the_fuzzed_corpus_never_scans_a_key_line_clean(tmp_path: Path) -> None:
    """The strike rule, as a test: exit 0 with an unmarked key-bearing line present is a strike."""
    repo, base, _head, diff = _fixture(tmp_path)
    lines = diff.splitlines()
    corpus: list[str] = []
    for cut in range(1, len(lines)):
        corpus.append("\n".join(lines[:cut]) + "\n")
    for drop in range(len(lines)):
        corpus.append("\n".join(lines[:drop] + lines[drop + 1 :]) + "\n")
    for stride in range(0, len(diff), 11):
        corpus.append(diff[:stride])
    for text in corpus:
        result = _run_text(repo, base, tmp_path, text)
        if result.returncode == 0:
            assert "OPENAI_API_KEY" not in text, f"scanned clean over a key line:\n{text}"


# ── diff-read errors carry next actions ─────────────────────────────


def test_a_missing_diff_file_refuses_with_a_next_action(tmp_path: Path) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    result = _run(repo, base, diff_file=tmp_path / "absent.diff")
    assert result.returncode == 2
    assert "Next action" in result.stderr


def test_a_missing_base_refuses_with_a_next_action(tmp_path: Path) -> None:
    repo, _base, _head, _diff = _fixture(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--head", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Next action" in result.stderr


def test_an_unresolvable_base_refuses_with_a_next_action(tmp_path: Path) -> None:
    repo, _base, _head, _diff = _fixture(tmp_path)
    result = _run(repo, "no-such-revision", diff_text="")
    assert result.returncode == 2
    assert "Next action" in result.stderr


# ── the marker is decided from the added lines a finding COVERS ──────


def test_a_marker_on_an_unchanged_opening_line_does_not_exempt_an_added_argument(
    tmp_path: Path,
) -> None:
    """codex's r1 critical on #4844.

    A call's opening line is a CONTEXT line when only an argument below it is added. The marker on
    that unchanged opening line must NOT exempt the newly added ``api_key=`` argument inside the
    call — the exemption belongs to the added lines the finding covers.
    """
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "tests" / "gen.py").write_text("client = OpenAI(  # billing-scan:allow\n)\n")
    marker_base = _commit(repo, "opening line carries the marker")
    (repo / "tests" / "gen.py").write_text(
        "client = OpenAI(  # billing-scan:allow\n    api_key=key,\n)\n"
    )
    head = _commit(repo, "add the credential argument")

    diff = _git(repo, "diff", "--unified=0", f"{marker_base}...{head}")
    assert "+    api_key=key," in diff
    assert "+client = OpenAI(" not in diff

    result = _run(repo, marker_base)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "api-key-route" in result.stdout
    assert "allowed" not in result.stdout


def test_a_marker_on_the_added_calls_own_line_still_exempts(tmp_path: Path) -> None:
    """The other half: the exemption still works when the ADDED lines it covers carry the marker."""
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "tests" / "gen.py").write_text("client = OpenAI(api_key=key)  # billing-scan:allow\n")
    _commit(repo, "one-line marked call")

    result = _run(repo, base)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "allowed tests/gen.py:1" in result.stdout


def test_a_multi_line_call_needs_the_marker_on_every_added_line_it_covers(
    tmp_path: Path,
) -> None:
    """The rule a reader must know: an exemption covers the ADDED lines that carry the marker, so a
    multi-line call is exempt only when every added line of it is marked — anything less would let an
    unmarked added line ride an exempted node."""
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "tests" / "gen.py").write_text(
        "client = OpenAI(  # billing-scan:allow\n"
        "    api_key=key,  # billing-scan:allow\n"
        ")  # billing-scan:allow\n"
    )
    _commit(repo, "multi-line marked call")

    result = _run(repo, base)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "allowed tests/gen.py:1" in result.stdout


# ── the remaining detector classes and error branches, at the entry point ──


def test_a_provider_endpoint_literal_is_a_provider_api_endpoint_finding(tmp_path: Path) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "app.py").write_text('ENDPOINT = "https://api.openai.com/v1/chat"\n')
    _commit(repo, "provider endpoint")
    result = _run(repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "provider-api-endpoint" in result.stdout


def test_a_bare_provider_sdk_constructor_is_a_provider_api_endpoint_finding(
    tmp_path: Path,
) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "app.py").write_text("from openai import OpenAI\n\nclient = OpenAI()\n")
    _commit(repo, "bare constructor")
    result = _run(repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "provider-api-endpoint" in result.stdout


def test_a_capacity_pool_payg_rebinding_is_a_finding(tmp_path: Path) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "app.py").write_text('config = {"capacity_pool": "api_paid_spend"}\n')
    _commit(repo, "payg rebinding")
    result = _run(repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "capacity-pool-payg" in result.stdout


def test_a_plan_type_api_rebinding_is_a_finding(tmp_path: Path) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / "app.py").write_text("plan_type = 'api'\n")
    _commit(repo, "plan type")
    result = _run(repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "capacity-pool-payg" in result.stdout


def test_an_unresolvable_head_refuses_with_a_next_action(tmp_path: Path) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--base",
            base,
            "--head",
            "no-such-head",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Next action" in result.stderr


def test_a_repo_that_is_not_a_repository_refuses_with_a_next_action(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    result = _run_text(plain, "abcdef0", plain, "not a diff at all\n")
    assert result.returncode == 2
    assert "Next action" in result.stderr


def test_an_empty_diff_file_refuses_with_a_next_action(tmp_path: Path) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    result = _run_text(repo, base, tmp_path, "")
    assert result.returncode == 2
    assert "Next action" in result.stderr
