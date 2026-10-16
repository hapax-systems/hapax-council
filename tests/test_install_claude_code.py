"""Exercise the retention install boundary with isolated, existing Claude profiles."""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "scripts/install-claude-code.sh"


def tree(root):
    return {
        str(p.relative_to(root)): (
            stat.S_IMODE(p.lstat().st_mode),
            p.readlink().as_posix() if p.is_symlink() else p.read_bytes() if p.is_file() else None,
        )
        for p in root.rglob("*")
    }


@pytest.fixture
def profiles(tmp_path):
    home = tmp_path / "home"
    settings = {
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "kept"}]}]},
        "permissions": {"allow": ["Read"], "deny": ["Bash(rm:*)"]},
        "statusLine": {"type": "command", "command": "kept-status"},
        "env": {"FIXTURE_ONLY": "unchanged"},
        "disableRemoteControl": False,
        "isolatePeerMachines": False,
        "crossSessionInbound": "accept",
        "idleCompaction": True,
        "enabledPlugins": {"hapax-system@hapax-local": True},
        "unrelated": {"integer": 9007199254740993, "unicode": "café", "null": None},
    }
    for name, mode in [(".claude", 0o644), (".claude-max-2", 0o600)]:
        profile = home / name
        profile.mkdir(parents=True)
        target = profile / "settings.json"
        target.write_text(json.dumps(settings, indent=4) + "\n")
        target.chmod(mode)
        (profile / "hooks.json").write_text('{"legacy":"preserve"}\n')
        plugins = profile / "plugins"
        (plugins / "cache/hapax-local").mkdir(parents=True)
        (plugins / "cache/hapax-local/kept").write_text("keep cache")
        (plugins / "installed_plugins.json").write_text('{"plugins":{}}\n')
    return home


def run(home, *args, path=None):
    env = {**os.environ, "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude")}
    if path is not None:
        env["PATH"] = str(path) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(INSTALLER), *map(str, args)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.parametrize("name", [".claude", ".claude-max-2"])
def test_only_retention_changes_in_explicit_profile_preserving_mode(profiles, name):
    before = tree(profiles)
    target = profiles / name / "settings.json"
    expected = json.loads(target.read_text()) | {"cleanupPeriodDays": 3650}
    result = run(profiles, "--config-dir", target.parent)
    assert result.returncode == 0, result.stderr
    assert json.loads(target.read_text()) == expected
    after = tree(profiles)
    key = str(target.relative_to(profiles))
    assert after[key][0] == before[key][0]
    assert {k: v for k, v in after.items() if k != key} == {
        k: v for k, v in before.items() if k != key
    }
    first_stat = target.stat()
    again = run(profiles, "--config-dir", target.parent)
    assert again.returncode == 0, again.stderr
    assert tree(profiles) == after
    assert target.stat().st_ino == first_stat.st_ino
    assert target.stat().st_mtime_ns == first_stat.st_mtime_ns


@pytest.mark.parametrize(
    "args",
    [[], ["--config-dir"], ["--config-dir", ""], ["--unknown"], ["--config-dir", "/missing"]],
)
def test_missing_or_invalid_explicit_directory_refuses_without_home_fallback(profiles, args):
    before = tree(profiles)
    result = run(profiles, *args)
    assert result.returncode != 0
    assert tree(profiles) == before


@pytest.mark.parametrize("body", [None, "invalid JSON", "[]", "null", "{}\n{}"])
def test_missing_or_invalid_settings_refuse_without_writes(profiles, body):
    target = profiles / ".claude-max-2/settings.json"
    if body is None:
        target.unlink()
    else:
        target.write_text(body)
    before = tree(profiles)
    result = run(profiles, "--config-dir", target.parent)
    assert result.returncode != 0
    assert tree(profiles) == before


def test_settings_symlink_refuses_without_replacing_or_following_it(profiles):
    target = profiles / ".claude-max-2/settings.json"
    target.unlink()
    target.symlink_to(profiles / ".claude/settings.json")
    before = tree(profiles)
    result = run(profiles, "--config-dir", target.parent)
    assert result.returncode != 0
    assert tree(profiles) == before


def shim(tmp_path, name, body):
    directory = tmp_path / "bin"
    directory.mkdir(exist_ok=True)
    script = directory / name
    script.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
    script.chmod(0o755)
    return directory


def test_concurrent_settings_edit_refuses_and_preserves_the_newer_bytes(profiles, tmp_path):
    target = profiles / ".claude-max-2/settings.json"
    peer = b'{"peer_edit":"must survive"}\n'
    replacement = tmp_path / "peer.json"
    replacement.write_bytes(peer)
    marker = tmp_path / "edited"
    # A second writer edits the settings after the installer has read its preimage.
    path = shim(
        tmp_path,
        "jq",
        f'{shutil.which("jq")} "$@"\n'
        f"if [[ ! -e {str(marker)!r} ]]; then\n"
        f"  cp {str(replacement)!r} {str(target)!r}\n"
        f"  touch {str(marker)!r}\n"
        "fi\n",
    )
    result = run(profiles, "--config-dir", target.parent, path=path)
    assert marker.exists(), "the concurrent writer must have run"
    assert result.returncode != 0
    assert "changed" in result.stderr.lower()
    assert target.read_bytes() == peer
    assert not list(target.parent.glob(".settings.json.*"))


def test_publication_is_one_same_directory_rename_of_validated_mode_preserving_file(
    profiles, tmp_path
):
    target = profiles / ".claude-max-2/settings.json"
    before = tmp_path / "before.json"
    before.write_bytes(target.read_bytes())
    marker = tmp_path / "renames"
    # Observe the OS publication boundary: old target intact until one rename.
    path = shim(
        tmp_path,
        "mv",
        'source_file="${@: -2:1}"\ntarget_file="${@: -1}"\n'
        f'[[ "$target_file" == {str(target)!r} ]]\n'
        '[[ "$(dirname "$source_file")" == "$(dirname "$target_file")" ]]\n'
        f'cmp -- {str(before)!r} "$target_file"\n'
        '[[ "$(stat -c %a "$source_file")" == "$(stat -c %a "$target_file")" ]]\n'
        'jq -e \'type == "object" and .cleanupPeriodDays == 3650\' "$source_file" >/dev/null\n'
        f'printf "rename\\n" >> {str(marker)!r}\n'
        f'exec {shutil.which("mv")} "$@"\n',
    )
    result = run(profiles, "--config-dir", target.parent, path=path)
    assert result.returncode == 0, result.stderr
    assert marker.read_text() == "rename\n"
    assert json.loads(target.read_text())["cleanupPeriodDays"] == 3650
    assert not list(target.parent.glob(".settings.json.*"))
