"""The billing scanner's entry point."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import inspect
import shutil
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
# Dataclasses resolve __module__ via sys.modules.
sys.modules[_spec.name] = scanner
_spec.loader.exec_module(scanner)

KEY_LINE = 'client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])'
ALLOW = "  # billing-scan:allow"


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
    repo: Path,
    base: str,
    *,
    head: str = "HEAD",
    diff_file: Path | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = [sys.executable, str(SCRIPT), "--repo", str(repo), "--base", base]
    argv += ["--diff-file", str(diff_file)] if diff_file else ["--head", head]
    return subprocess.run(argv, env=env, capture_output=True, text=True, check=False)


# id -> (path, pre-image or None, post-image, exit, stdout has, stdout lacks)

_PROXY = 'base_url="http://127.0.0.1:4000"'
_HEADER_PRE = 'import os\nNOTE = """\nfirst\n"""\n\nvalue = 1\n'
_HEADER_POST = f'import os\nNOTE = """\nfirst\n++ b/docs/hidden.py\n"""\n\nvalue = 1\n{KEY_LINE}\n'
_CASES = {
    "ordering-key": (
        "app.py",
        None,
        "actions.sort(key=lambda pair: pair[0])\n",
        0,
        ("ordering-callable-key",),
        ("api-key-route",),
    ),
    "ordering-key-with-key-line": (
        "app.py",
        None,
        f"actions.sort(key=lambda pair: pair[0])\n{KEY_LINE}\n",
        1,
        ("api-key-route", "credential-env-read"),
        (),
    ),
    "ordering-key-with-nested-client": (
        "app.py",
        None,
        "actions.sort(key=lambda pair: client(api_key=pair[0]))\n",
        1,
        ("api-key-route",),
        (),
    ),
    "credential-route": (
        "app.py",
        None,
        f"import os\nfrom openai import OpenAI\n{KEY_LINE}\n",
        1,
        ("api-key-route", "credential-env-read"),
        (),
    ),
    "provider-url": (
        "app.py",
        None,
        'url = "HTTPS://user@API.OPENAI.COM.:443/v1?model=x"\n',
        1,
        ("provider-api-endpoint",),
        (),
    ),
    "js-env": (
        "app.js",
        None,
        'k = process.env["openai_api_key"];\n',
        1,
        ("credential-env-read",),
        (),
    ),
    "bearer-header": (
        "app.py",
        None,
        'h = {"authorization": f"BEARER {t}"}\n',
        1,
        ("api-key-route",),
        (),
    ),
    "sdk-constructor-bare": ("app.py", None, "c = OpenAI()\n", 1, ("provider-api-endpoint",), ()),
    "sdk-constructor-args": (
        "app.py",
        None,
        "c = OpenAI(timeout=3)\n",
        1,
        ("provider-api-endpoint",),
        (),
    ),
    "no-billing-surface": ("app.py", None, "import os\n\nvalue = 2\n", 0, ("OK",), ()),
    # fails closed; never echoes an unplaced key read
    "unparseable": ("app.py", None, "import os\nvalues = (\n", 1, ("unparseable-python",), ()),
    "unparseable-multiline-read": (
        "app.py",
        None,
        'v = os.getenv(default=None,\n    key="OPENAI_API_KEY")\nbroken = (\n',
        1,
        ("unparseable-python",),
        ("OPENAI_API_KEY",),
    ),
    # a header-shaped line hides no hunk
    "header-shaped-line": (
        "app.py",
        _HEADER_PRE,
        _HEADER_POST,
        1,
        ("app.py:8: api-key-route",),
        (),
    ),
    "doc-skipped": ("notes.md", None, f"{KEY_LINE}\n", 0, (), ()),
    # #4808 r2/r3: a marker speaks only for its line
    "neighbour-marker": (
        "tests/gen.py",
        None,
        f"c = OpenAI(api_key=key)\n#{ALLOW}\n",
        1,
        ("api-key-route",),
        ("allowed",),
    ),
    "marker-abroad": (
        "app.py",
        None,
        f"c = OpenAI(api_key=key){ALLOW}\n",
        1,
        ("marker", "api-key-route"),
        (),
    ),
    "proxy-exempt": (
        "app.py",
        None,
        f"OpenAI(api_key=key, {_PROXY})\n",
        0,
        ("governed-proxy-route",),
        (),
    ),
    # the exemption is per call; the env read is its own node
    "proxy-env-read": (
        "app.py",
        None,
        f'OpenAI(api_key=os.environ["OPENAI_API_KEY"], {_PROXY})\n',
        1,
        ("governed-proxy-route", "credential-env-read"),
        (),
    ),
    "dynamic-proxy": (
        "app.py",
        None,
        'h = "x"\nOpenAI(api_key=os.environ["K"], base_url=f"http://{h}:4000")\n',
        1,
        ("api-key-route",),
        (),
    ),
    # decided by the covered ADDED lines
    "marker-on-unchanged-opening-line": (
        "tests/gen.py",
        f"c = OpenAI({ALLOW}\n)\n",
        f"c = OpenAI({ALLOW}\n    api_key=key,\n)\n",
        1,
        ("api-key-route",),
        ("allowed",),
    ),
    "marker-on-own-line": (
        "tests/gen.py",
        None,
        f"c = OpenAI(api_key=key){ALLOW}\n",
        0,
        ("allowed tests/gen.py:1",),
        (),
    ),
    "marker-on-every-covered-line": (
        "tests/gen.py",
        None,
        f"c = OpenAI({ALLOW}\n    api_key=key,{ALLOW}\n){ALLOW}\n",
        0,
        ("allowed tests/gen.py:1",),
        (),
    ),
    "capacity-pool-payg": (
        "app.py",
        None,
        'c = {"capacity_pool": "api_paid_spend"}\n',
        1,
        ("capacity-pool-payg",),
        (),
    ),
    "plan-type-api": ("app.py", None, "plan_type = 'api'\n", 1, ("capacity-pool-payg",), ()),
}
# codex r10
_CASES |= {
    f"sep-{c:x}": ("app.py", None, f'x = "a{chr(c)} b"\n{KEY_LINE}\n', 1, ("app.py:2: api",), ())
    for c in (0x2028, 0x2029, 0x85, 0xC, 0x1C)
}


@pytest.mark.parametrize("case", list(_CASES), ids=list(_CASES))
def test_a_scan_case(tmp_path: Path, case: str) -> None:
    path, pre, post, code, present, absent = _CASES[case]
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    if pre is not None:
        (repo / path).write_text(pre)
        base = _commit(repo, "pre-image")
    (repo / path).write_text(post)
    _commit(repo, case)
    result = _run(repo, base)
    assert result.returncode == code, result.stdout + result.stderr
    assert all(p in result.stdout for p in present), result.stdout
    assert not any(a in result.stdout for a in absent), result.stdout


def test_an_advanced_base_keeps_the_added_line(tmp_path: Path) -> None:
    # On main's tree the hunk would land inside the string.
    repo, base, _head, _diff = _fixture(tmp_path)
    _git(repo, "checkout", "-q", base)
    _git(repo, "checkout", "-q", "-b", "pr")
    (repo / "app.py").write_text(f"import os\n{KEY_LINE}\n\nvalue = 1\n")
    _commit(repo, "pr")
    _git(repo, "checkout", "-q", base)
    (repo / "app.py").write_text('NOTE = """\ninside\n"""\nimport os\n\nvalue = 1\n')
    advanced = _commit(repo, "main advances")
    _git(repo, "checkout", "-q", "pr")
    result = _run(repo, advanced)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "app.py:2: api-key-route" in result.stdout


def test_no_text_accepting_entry() -> None:
    """muse r7."""
    entry = inspect.signature(scanner.scan_git_validated)
    assert list(entry.parameters) == ["repo", "base", "head"]
    for name, fn in vars(scanner).items():
        if inspect.isfunction(fn) and fn.__module__ == scanner.__name__:
            assert not {"diff_text", "text"} & set(inspect.signature(fn).parameters), name


_CLEAN = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -3 +3 @@\n-value = 1\n+value = 2\n"
_BINARY = "Binary files a/app.py and b/app.py differ"


@pytest.mark.parametrize(
    "shape",
    [
        lambda d, ls: d,
        lambda d, ls: "\n".join(l for l in ls if not l.startswith("diff --git")) + "\n",
        lambda d, ls: "\n".join(
            l for l in ls if not l.startswith(("diff --git", "index ", "--- "))
        ),
        lambda d, ls: "\n".join([*ls[:3], _BINARY, *ls[3:]]) + "\n",
        lambda d, ls: f"{d}{_BINARY}\n",
        lambda d, ls: "\n".join(ls[:-1]) + "\n",
        lambda d, ls: d[: len(d) // 2],
        lambda d, ls: "\n".join(ls[1:]) + "\n",
        lambda d, ls: f"{_CLEAN}+{KEY_LINE}\n",
    ],
    ids=[
        "honest-diff",
        "headerless-hunk",
        "ppp-without-diff-git",
        "binary-note-after-hunk",
        "trailing-binary-note",
        "line-truncation",
        "char-truncation",
        "header-deletion",
        "trailing-credential-after-valid-hunk",
    ],
)
def test_a_supplied_diff_file_is_refused(tmp_path: Path, shape: object) -> None:
    """#4795 r5-r7, #4808 r1-r3, muse r7."""
    repo, base, _head, diff = _fixture(tmp_path)
    case = tmp_path / "case.diff"
    case.write_text(shape(diff, diff.splitlines()), encoding="utf-8")  # type: ignore[operator]
    result = _run(repo, base, diff_file=case)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "unusable for a gate" in result.stderr and "--head" in result.stderr


@pytest.mark.parametrize("driver", ["external-diff", "textconv"])
def test_a_diff_driver_cannot_substitute_a_patch(tmp_path: Path, driver: str) -> None:
    """codex r7."""
    repo, base, _head, _diff = _fixture(tmp_path)
    tool = tmp_path / "driver.sh"
    if driver == "external-diff":
        (tmp_path / "clean.diff").write_text(_CLEAN)
        tool.write_text(f"#!/bin/sh\ncat {tmp_path / 'clean.diff'}\n")
        _git(repo, "config", "diff.external", str(tool))
    else:
        tool.write_text('#!/bin/sh\ngrep -v OpenAI "$1"\n')
        (repo / ".git" / "info").mkdir(exist_ok=True)
        (repo / ".git" / "info" / "attributes").write_text("*.py diff=clean\n")
        _git(repo, "config", "diff.clean.textconv", str(tool))
    tool.chmod(0o755)
    result = _run(repo, base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "api-key-route" in result.stdout


@pytest.mark.parametrize("worktree_at", ["base", "head"])
def test_a_head_attribute_hides_no_change(tmp_path: Path, worktree_at: str) -> None:
    """Attributes come from the base tree."""
    repo, base, _head, _diff = _fixture(tmp_path)
    (repo / ".gitattributes").write_text("*.py -diff\n")
    head = _commit(repo, "head marks python binary")
    _git(repo, "checkout", "-q", base if worktree_at == "base" else head)
    result = _run(repo, base, head=head)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "api-key-route" in result.stdout


_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x00\x00\x00\x00:~\x9bU"


@pytest.mark.parametrize(
    ("case", "code", "said"),
    [
        ("base-marks-python-binary", 1, "api-key-route"),
        ("base-marks-python-binary-abbrev-7", 1, "api-key-route"),
        ("genuine-png", 2, "an opaque change cannot be scanned. Next action: split"),
    ],
)
def test_no_opaque_change_passes_the_strict_gate(
    tmp_path: Path, case: str, code: int, said: str
) -> None:
    """codex r9."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", ".")
    _git(repo, "config", "core.abbrev", "7" if case.endswith("7") else "40")
    (repo / "app.py").write_text("import os\n\nvalue = 1\n")
    (repo / ".gitattributes").write_text("*.py -diff\n" if case.startswith("base") else "")
    base = _commit(repo, "base")
    if case.startswith("base"):
        (repo / "app.py").write_text(f"import os\nfrom openai import OpenAI\n{KEY_LINE}\n")
    else:
        (repo / "logo.png").write_bytes(_PNG)
    head = _commit(repo, "head")
    result = _run(repo, base, head=head)
    assert result.returncode == code, result.stdout + result.stderr
    assert said in result.stdout + result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["--repo", "{R}", "--head", "HEAD"],
        ["--repo", "{R}", "--base", "no-such-revision", "--head", "HEAD"],
        ["--repo", "{R}", "--base", "{B}", "--head", "no-such-head"],
        ["--repo", "{T}/plain", "--base", "abcdef0", "--head", "HEAD"],
        ["--repo", "{R}", "--base", "{B}", "--head", "{B}"],
        ["--repo", "{T}/no-such-repo", "--base", "main", "--head", "HEAD"],
    ],
    ids=[
        "missing-base",
        "unresolvable-base",
        "unresolvable-head",
        "not-a-repository",
        "empty-generated-diff",
        "nonexistent-repo",
    ],
)
def test_an_unusable_invocation_refuses(tmp_path: Path, args: list[str]) -> None:
    repo, base, _head, _diff = _fixture(tmp_path)
    (tmp_path / "plain").mkdir()
    subs = {"{R}": str(repo), "{B}": base, "{T}": str(tmp_path)}
    for key, value in subs.items():
        args = [arg.replace(key, value) for arg in args]
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "Next action" in result.stderr
    if "no-such-repo" in args[1]:
        assert "is not a directory" in result.stderr


@pytest.mark.parametrize(
    ("version", "refusal"),
    [
        ("2.39.5", "git >= 2.41 is required"),
        ("2.40.4", "git >= 2.41 is required"),
        ("unknown", "git >= 2.41"),
        (None, "git is unavailable"),
    ],
)
def test_an_unusable_git_refuses(tmp_path: Path, version: str | None, refusal: str) -> None:
    """git < 2.41 ignores GIT_ATTR_SOURCE."""
    repo, base, _head, _diff = _fixture(tmp_path)
    stub = tmp_path / "bin" / "git"
    stub.parent.mkdir()
    if version:
        real = shutil.which("git")
        stub.write_text(
            f'#!/bin/sh\n[ "$1" = --version ] && echo "git version {version}" && exit\nexec {real} "$@"\n'
        )
        stub.chmod(0o755)
    result = _run(repo, base, env={"PATH": str(stub.parent)})
    assert result.returncode == 2, result.stdout + result.stderr
    assert refusal in result.stderr and "Next action" in result.stderr


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "not a patch\n",
        "\ufffd\n",
        _CLEAN,
        # Supplied-text refusal fixtures, not spend routes.
        '+client = OpenAI(base_url="http://127.0.0.1:4000", api_key=os.environ["K"])\n',  # billing-scan:allow
        "+value = 1  # billing-scan:allow\n",
        "diff --git a/tests/fixture.py b/tests/fixture.py\n+not python (\n",
        "diff --git a/docs/guide.md b/docs/guide.md\n+documentation\n",
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +1 @@\n+value = 1\n",
    ],
)
def test_legacy_corpus_text_cannot_supply_billing_gate_evidence(tmp_path, payload):
    """#4805's former text-acceptance cases now refuse even beside valid git refs."""
    repo, base, head, _ = _fixture(tmp_path)
    case = tmp_path / "legacy.diff"
    case.write_text(payload)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--base",
            base,
            "--head",
            head,
            "--diff-file",
            str(case),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert (
        "unusable for a gate" in result.stderr
        and "--base" in result.stderr
        and "--head" in result.stderr
    )
    assert "OK:" not in result.stdout
