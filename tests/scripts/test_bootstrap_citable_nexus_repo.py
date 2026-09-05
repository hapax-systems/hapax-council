"""Exercise bootstrap delivery with recording fakes; never invoke real gh/git/uv."""

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
    if args == ["status", "--porcelain"]:
        print(" M index.html")
    else:
        assert args in (["add", "-A"], ["push", "origin", "main"]) or (
            len(args) == 3 and args[:2] == ["commit", "-m"]
        ), args
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
    assert [call["tool"] for call in calls] == ["uv", "gh", "git", "git", "git", "git", "gh"]
    assert calls[0]["cwd"] == str(council)
    assert calls[0]["args"] == [
        "run",
        "python",
        "scripts/build_citable_nexus.py",
        "--out",
        str(work / "render"),
        "--canonical-url",
        "https://example.invalid",
    ] + (["--cleared-inputs", str(cleared)] if "rss.xml" in rendered else [])
    assert all(call["cwd"] == str(repo) for call in calls if call["tool"] == "git")
    assert calls[4]["args"][:2] == ["commit", "-m"]
    assert str(council) not in calls[4]["args"][2]
    assert calls[5]["args"] == ["push", "origin", "main"]
    assert "https://example.invalid/refuse" not in completed.stdout
    assert "gh variable set HAPAX_CITABLE_NEXUS_CANONICAL_URL" in completed.stdout
    assert "bootstrap-only cleared-inputs list is not supplied" in completed.stdout
    assert "--commit also\n  copies, commits and pushes CNAME" in completed.stdout
    assert "Script completion alone does not establish a live site." in completed.stdout
    print(f"delivery {git_layout} {','.join(rendered)} BEFORE: {json.dumps(before)}")
    print(f"delivery {git_layout} {','.join(rendered)} AFTER: {json.dumps(after)}")
