"""Exercise bootstrap delivery with fake remote tools and isolated local Git."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/bootstrap_citable_nexus_repo.sh"
GENERATED = (
    "index.html",
    "cite/index.html",
    "404.html",
    "manifesto/index.html",
    "refusal-brief/index.html",
    "deposits/index.html",
    "citation-graph/index.html",
    "refuse/index.html",
    "surfaces/index.html",
    "rss.xml",
    "CNAME",
    ".github/workflows/deploy.yml",
)

FAKE_TOOL = r"""
import json
import os
import sys
from pathlib import Path

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
with Path(os.environ["FAKE_LOG"]).open("a") as log:
    log.write(json.dumps({"tool": tool, "args": args, "cwd": os.getcwd()}) + "\n")
if tool == "uv":
    assert args[:4] == ["run", "python", "scripts/build_citable_nexus.py", "--out"], args
    assert args[5:7] == ["--canonical-url", "https://example.invalid"], args
    output = Path(args[4])
    for relative in json.loads(os.environ["FAKE_RENDER_FILES"]):
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("current " + relative + "\n")
elif tool == "gh":
    assert args == ["repo", "view", "hapax-systems/example-site"] or args == [
        "api", "-X", "POST", "-H", "Accept: application/vnd.github+json",
        "/repos/hapax-systems/example-site/pages", "-f", "source[branch]=main",
        "-f", "source[path]=/"
    ], args
elif tool == "git":
    status = args == ["status", "--porcelain"] or args == [
        "--no-optional-locks", "-c", "core.quotePath=true", "status",
        "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none", "--no-renames"
    ]
    push = args == ["push", "origin", "main"]
    assert status or push or args == ["add", "-A"] or (
        len(args) == 3 and args[:2] == ["commit", "-m"]
    ), args
    if os.environ.get("REAL_GIT") and not push:
        os.execv(os.environ["REAL_GIT"], [os.environ["REAL_GIT"], *args])
    elif status:
        print(" M index.html")
else:
    raise AssertionError(tool)
"""


@pytest.mark.parametrize("git_layout", ["directory", "file"])
@pytest.mark.parametrize(
    "rendered",
    [
        ("index.html", "cite/index.html", "404.html", "CNAME"),
        ("index.html", "cite/index.html", "404.html", "CNAME", "manifesto/index.html", "rss.xml"),
        ("cite/index.html",),  # Also pin removal of absent core generated files.
    ],
    ids=["no-cleared-inputs", "cleared-inputs", "sparse-render"],
)
def test_delivery_reconciles_only_known_generated_files(tmp_path, rendered, git_layout):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("gh", "git", "uv"):
        fake = bin_dir / tool
        fake.write_text(f"#!{sys.executable}\n" + FAKE_TOOL)
        fake.chmod(0o755)
    # PATH contains only the three fakes and an explicit set of local filesystem
    # utilities. No real network-capable tool can be resolved by the script.
    for utility in ("mkdir", "find", "wc", "cp", "dirname", "rm", "cat"):
        executable = shutil.which(utility)
        assert executable, utility
        (bin_dir / utility).symlink_to(executable)
    bash = shutil.which("bash")
    assert bash
    council = tmp_path / "council source"
    template = council / "docs/citable-nexus/github-actions-deploy.yml.template"
    template.parent.mkdir(parents=True)
    template.write_text("# synthetic workflow template; never executed\n")
    work = tmp_path / "publishing work"
    repo = work / "example-site"
    preserved = {
        "unrelated.txt": b"unrelated file\n",
        "src/source.py": b"# preserved source\n",
        "manifesto/notes.txt": b"unrelated file inside a generated route\n",
        ".github/workflows/unrelated.yml": b"# preserved workflow\n",
    }
    if git_layout == "directory":
        preserved.update({".git/HEAD": b"synthetic HEAD\n", ".git/objects/history": b"history\n"})
    else:
        preserved[".git"] = b"synthetic worktree git pointer\n"
    for relative, content in preserved.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for relative in GENERATED:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stale " + relative + "\n")
    before = sorted(str(path.relative_to(repo)) for path in repo.rglob("*") if path.is_file())
    original_stats = {name: (repo / name).stat() for name in preserved}
    log = tmp_path / "tool-calls.jsonl"
    cleared = tmp_path / "cleared inputs.txt"
    cleared.write_text("synthetic fixture input\n")
    env = {
        "PATH": str(bin_dir),
        "HOME": str(tmp_path),
        "HAPAX_NEXUS_DOMAIN": "example.invalid",
        "HAPAX_NEXUS_REPO_NAME": "example-site",
        "HAPAX_NEXUS_WORK_DIR": str(work),
        "HAPAX_COUNCIL_REPO": str(council),
        "FAKE_LOG": str(log),
        "FAKE_RENDER_FILES": json.dumps(rendered),
    }
    if "rss.xml" in rendered:
        env["HAPAX_NEXUS_CLEARED_INPUTS"] = str(cleared)
    completed = subprocess.run(
        [bash, str(SCRIPT), "--commit"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    current = {*rendered, ".github/workflows/deploy.yml"}
    after = sorted(str(path.relative_to(repo)) for path in repo.rglob("*") if path.is_file())
    assert before == sorted({*GENERATED, *preserved})
    assert after == sorted(current | preserved.keys())
    for relative in current:
        expected = (
            template.read_text()
            if relative == ".github/workflows/deploy.yml"
            else "current " + relative + "\n"
        )
        assert (repo / relative).read_text() == expected
    for relative, content in preserved.items():
        assert (repo / relative).read_bytes() == content
        stat = (repo / relative).stat()
        assert (stat.st_ino, stat.st_mtime_ns) == (
            original_stats[relative].st_ino,
            original_stats[relative].st_mtime_ns,
        )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [call["tool"] for call in calls] == [
        "git",
        "uv",
        "gh",
        "git",
        "git",
        "git",
        "git",
        "git",
        "gh",
    ]
    assert calls[1]["cwd"] == str(council)
    assert calls[1]["args"] == [
        "run",
        "python",
        "scripts/build_citable_nexus.py",
        "--out",
        str(work / "render"),
        "--canonical-url",
        "https://example.invalid",
    ] + (["--cleared-inputs", str(cleared)] if "rss.xml" in rendered else [])
    assert all(call["cwd"] == str(repo) for call in calls if call["tool"] == "git")
    assert calls[6]["args"][:2] == ["commit", "-m"]
    assert str(council) not in calls[6]["args"][2]
    assert calls[7]["args"] == ["push", "origin", "main"]
    assert "https://example.invalid/refuse" not in completed.stdout
    assert "gh variable set HAPAX_CITABLE_NEXUS_CANONICAL_URL" in completed.stdout
    assert "bootstrap-only cleared-inputs list is not supplied" in completed.stdout
    assert "--commit also\n  copies, commits and pushes CNAME" in completed.stdout
    assert "Script completion alone does not establish a live site." in completed.stdout
    print(f"delivery {git_layout} {','.join(rendered)} BEFORE: {json.dumps(before)}")
    print(f"delivery {git_layout} {','.join(rendered)} AFTER: {json.dumps(after)}")


@pytest.mark.parametrize("pending", ["unstaged", "staged", "generated-only", "clean"])
def test_real_git_commit_boundary(tmp_path, pending):
    real_git = shutil.which("git")
    bash = shutil.which("bash")
    assert real_git and bash
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("gh", "git", "uv"):
        fake = bin_dir / tool
        fake.write_text(f"#!{sys.executable}\n" + FAKE_TOOL)
        fake.chmod(0o755)
    for utility in ("mkdir", "find", "wc", "cp", "dirname", "rm", "cat"):
        executable = shutil.which(utility)
        assert executable, utility
        (bin_dir / utility).symlink_to(executable)
    council = tmp_path / "council source"
    template = council / "docs/citable-nexus/github-actions-deploy.yml.template"
    template.parent.mkdir(parents=True)
    template.write_text("# synthetic workflow template; never executed\n")
    work = tmp_path / "publishing work"
    repo = work / "example-site"
    repo.mkdir(parents=True)
    log = tmp_path / "tool-calls.jsonl"
    rendered = ("index.html", "cite/index.html", "404.html", "CNAME")
    env = {
        "PATH": str(bin_dir),
        "HAPAX_NEXUS_DOMAIN": "example.invalid",
        "HAPAX_NEXUS_REPO_NAME": "example-site",
        "HAPAX_NEXUS_WORK_DIR": str(work),
        "HAPAX_COUNCIL_REPO": str(council),
        "FAKE_LOG": str(log),
        "FAKE_RENDER_FILES": json.dumps(rendered),
        # The wrapper delegates only local status/add/commit to real Git; push
        # is recorded by the fake. No real remote or credential tools run.
        "REAL_GIT": real_git,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }

    def git(*args):
        return subprocess.run(
            [real_git, *args], cwd=repo, env=env, capture_output=True, check=True, timeout=20
        ).stdout

    def files():
        return {
            path.relative_to(repo).as_posix(): path.read_bytes()
            for path in repo.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(repo).parts
        }

    git("init", "-b", "main")
    git("config", "core.hooksPath", "/dev/null")
    git("config", "commit.gpgSign", "false")
    for relative in GENERATED:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stale " + relative + "\n")
    tracked = repo / "notes.txt"
    tracked.write_bytes(b"unrelated committed content\n")
    git("add", "-A")
    git("commit", "-m", "Seed synthetic publishing checkout")
    initial_head = git("rev-parse", "HEAD")
    refused = pending in ("unstaged", "staged")
    if refused:
        tracked.write_bytes(b"unrelated pending tracked content\n\x00retained bytes\n")
        # Exercise enumeration within a generated route and quoted porcelain
        # paths: this embedded newline must still count as just one path.
        (repo / "manifesto/notes draft\nlocal.txt").write_bytes(
            b"unrelated pending untracked content\n\x00retained bytes\n"
        )
        if pending == "staged":
            git("add", "--", "notes.txt")
    elif pending == "generated-only":
        (repo / "index.html").write_text("pending generated home\n")
        git("add", "--", "index.html")
    before = files()
    before_stats = {
        name: ((repo / name).stat().st_ino, (repo / name).stat().st_mtime_ns) for name in before
    }
    status_args = ("status", "--porcelain=v1", "--untracked-files=all", "--no-renames", "-z")
    status_before = git(*status_args)
    index_before = (repo / ".git/index").read_bytes()
    completed = subprocess.run(
        [bash, str(SCRIPT), "--commit"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )
    after = files()
    status_after = git(*status_args)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    if refused:
        assert completed.returncode == 2, completed.stdout + completed.stderr
        assert "Refusing delivery: 2 unrelated changed path(s)." in completed.stderr
        assert "Next action: resolve those pending changes separately" in completed.stderr
        assert after == before
        assert status_after == status_before
        assert (repo / ".git/index").read_bytes() == index_before
        assert git("rev-parse", "HEAD") == initial_head
        assert git("rev-list", "--count", "HEAD") == b"1\n"
        assert not (work / "render").exists()
        assert len(calls) == 1 and calls[0]["tool"] == "git"
        for name, stat in before_stats.items():
            assert ((repo / name).stat().st_ino, (repo / name).stat().st_mtime_ns) == stat
        print(completed.stderr.strip())
    else:
        assert completed.returncode == 0, completed.stdout + completed.stderr
        expected = {relative: ("current " + relative + "\n").encode() for relative in rendered}
        expected[".github/workflows/deploy.yml"] = template.read_bytes()
        expected["notes.txt"] = before["notes.txt"]
        assert after == expected
        assert status_after == b""
        assert git("rev-list", "--count", "HEAD") == b"2\n"
        assert set(
            git("diff", "--name-only", initial_head.decode().strip(), "HEAD").decode().splitlines()
        ) == set(GENERATED)
        assert sum(call["args"] == ["push", "origin", "main"] for call in calls) == 1
        delivered_head = git("rev-parse", "HEAD")
        repeated = subprocess.run(
            [bash, str(SCRIPT), "--commit"],
            cwd=tmp_path,
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert repeated.returncode == 0, repeated.stdout + repeated.stderr
        assert "no commit needed" in repeated.stderr
        assert git("rev-parse", "HEAD") == delivered_head
        assert git(*status_args) == b""
        assert files() == after
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        assert sum(call["args"] == ["push", "origin", "main"] for call in calls) == 1
    print(f"real-git {pending} BEFORE: {json.dumps(sorted(before))}; status={status_before!r}")
    print(f"real-git {pending} AFTER: {json.dumps(sorted(after))}; status={status_after!r}")
    print(
        f"real-git {pending} exit={completed.returncode}; files={len(before)}->{len(after)}; "
        f"commits=1->{git('rev-list', '--count', 'HEAD').decode().strip()}; "
        f"fake_pushes={sum(call['args'] == ['push', 'origin', 'main'] for call in calls)}"
    )
