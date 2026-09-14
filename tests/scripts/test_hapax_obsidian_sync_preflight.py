"""Pins for scripts/hapax-obsidian-sync-preflight.

The defect being pinned is SILENT ADMISSION: ``ob sync-config --excluded-folders``
accepts an entry that matches nothing, so the data that entry was meant to exclude
uploads with no error anywhere. Measured three times on one hand-carried list
(2026-09-14, task obsidian-sync-freshvault-headless-20260914). Every test below
therefore asserts on the REFUSAL and on the effective-entry set, not merely on the
human text.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-obsidian-sync-preflight"

OK = 0
REFUSED = 2
ERROR = 3


def _load_module():
    spec = importlib.util.spec_from_loader(
        "hapax_obsidian_sync_preflight",
        importlib.machinery.SourceFileLoader("hapax_obsidian_sync_preflight", str(SCRIPT)),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = _load_module()


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def vault(tmp_path: pathlib.Path) -> pathlib.Path:
    """A vault shaped like the real one: a deep kept tree, an excludable subtree,
    a nested dot-folder, and one unsupported-class file."""
    root = tmp_path / "vault"
    (root / "20-projects" / "notes").mkdir(parents=True)
    (root / "20-projects" / "notes" / "keep.md").write_bytes(b"k" * 100)
    (root / "20-projects" / "_dashboard").mkdir()
    (root / "20-projects" / "_dashboard" / "huge.md").write_bytes(b"d" * 5000)
    # Name-prefix sibling: excluding '_dashboard' must NOT take '_dashboard-keep'.
    (root / "20-projects" / "_dashboard-keep").mkdir()
    (root / "20-projects" / "_dashboard-keep" / "sibling.md").write_bytes(b"s" * 11)
    (root / "30-areas" / "hapax" / "ocr" / "pages").mkdir(parents=True)
    (root / "30-areas" / "hapax" / "ocr" / "pages" / "p1.png").write_bytes(b"p" * 900)
    (root / "30-areas" / "hapax" / "keep.md").write_bytes(b"h" * 50)
    # hidden at depth: ob's Is() rejects any path with a dotted component
    (root / "30-areas" / ".venv" / "lib").mkdir(parents=True)
    (root / "30-areas" / ".venv" / "lib" / "buried.md").write_bytes(b"x" * 7777)
    (root / "data.jsonl").write_bytes(b"u" * 4242)  # unsupported class
    return root


def test_missing_entry_is_refused_and_excludes_nothing(vault: pathlib.Path) -> None:
    """The measured defect: a path that does not exist must REFUSE, and must not
    be counted as an effective exclusion."""
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages-nope",
        "--json",
    )
    assert result.returncode == REFUSED, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["entries_unmatchable"] == 1
    assert report["entries_effective"] == 1
    verdicts = {f["normalized"]: f["verdict"] for f in report["findings"]}
    assert verdicts["30-areas/hapax/ocr/pages-nope"] == "missing"
    assert verdicts["20-projects/_dashboard"] == "ok"
    # The png is NOT excluded, because the entry naming it cannot match.
    assert report["predicted_upload"]["by_ext"]["png"]["files"] == 1


def test_wrong_prefix_is_the_real_world_shape(vault: pathlib.Path) -> None:
    """'ocr/pages' instead of '30-areas/hapax/ocr/pages' — the exact 2026-09-14
    defect. The directory exists, but not at that vault-relative path."""
    result = _run(str(vault), "--excluded-folders", "ocr/pages", "--json")
    assert result.returncode == REFUSED
    report = json.loads(result.stdout)
    assert report["findings"][0]["verdict"] == "missing"
    assert report["predicted_upload"]["by_ext"]["png"]["files"] == 1


def test_valid_list_passes_and_prunes_the_named_subtrees(vault: pathlib.Path) -> None:
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--json",
    )
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["entries_unmatchable"] == 0
    upload = report["predicted_upload"]
    # keep.md (100) + keep.md (50) + sibling.md (11); the 5000-byte and 900-byte
    # files are excluded, the 7777-byte file is hidden, the .jsonl is unsupported.
    assert upload["files"] == 3
    assert upload["bytes"] == 161
    assert "png" not in upload["by_ext"]


def test_trailing_slash_can_never_match(vault: pathlib.Path) -> None:
    """ob compares the raw string, so 'x/' probes 'x//' and matches nothing."""
    result = _run(str(vault), "--excluded-folders", "20-projects/_dashboard/", "--json")
    assert result.returncode == REFUSED
    report = json.loads(result.stdout)
    assert report["findings"][0]["verdict"] == "malformed"
    assert report["entries_effective"] == 0
    # Proof it truly failed open: the 5000-byte dashboard file is in the upload,
    # alongside the keep.md files (150), sibling.md (11) and the 900-byte png.
    assert report["predicted_upload"]["bytes"] == 6061


def test_exclusion_respects_the_path_boundary(vault: pathlib.Path) -> None:
    """ob's test is ``e === r || e.startsWith(r + "/")`` — the trailing slash is
    what stops '_dashboard' from swallowing the sibling '_dashboard-keep'. A bare
    ``startswith(r)`` would silently drop files the operator never excluded."""
    result = _run(str(vault), "--excluded-folders", "20-projects/_dashboard", "--json")
    assert result.returncode == OK
    report = json.loads(result.stdout)
    paths = {item["path"] for item in report["largest_included_files"]}
    assert "20-projects/_dashboard-keep/sibling.md" in paths
    assert not any("_dashboard/" in p for p in paths)


def test_file_entry_excludes_nothing(vault: pathlib.Path) -> None:
    result = _run(str(vault), "--excluded-folders", "20-projects/_dashboard/huge.md", "--json")
    assert result.returncode == REFUSED
    assert json.loads(result.stdout)["findings"][0]["verdict"] == "file_not_folder"


def test_hidden_components_pruned_at_any_depth(vault: pathlib.Path) -> None:
    """A dot-folder below the root is pruned with no exclusion entry for it."""
    result = _run(str(vault), "--excluded-folders", "20-projects/_dashboard", "--json")
    report = json.loads(result.stdout)
    paths = [item["path"] for item in report["largest_included_files"]]
    assert not any(".venv" in p for p in paths)
    assert report["after_pruning_all_classes"]["files"] == 5  # 3 md + png + jsonl


def test_unsupported_class_is_off_by_default_and_opt_in(vault: pathlib.Path) -> None:
    base = (str(vault), "--excluded-folders", "20-projects/_dashboard")
    default = json.loads(_run(*base, "--json").stdout)
    assert "jsonl" not in default["predicted_upload"]["by_ext"]

    opted = json.loads(
        _run(*base, "--file-types", "image,audio,pdf,video,unsupported", "--json").stdout
    )
    assert opted["predicted_upload"]["by_ext"]["jsonl"]["bytes"] == 4242


def test_redundant_entry_reported_but_not_refused(vault: pathlib.Path) -> None:
    result = _run(
        str(vault),
        "--excluded-folders",
        "30-areas/hapax,30-areas/hapax/ocr/pages",
        "--json",
    )
    assert result.returncode == OK
    findings = {f["normalized"]: f for f in json.loads(result.stdout)["findings"]}
    assert findings["30-areas/hapax/ocr/pages"]["redundant_under"] == ["30-areas/hapax"]


def test_allow_missing_downgrades_refusal_to_report(vault: pathlib.Path) -> None:
    result = _run(str(vault), "--excluded-folders", "nope", "--allow-missing", "--json")
    assert result.returncode == OK
    assert json.loads(result.stdout)["entries_unmatchable"] == 1


def test_from_sync_config_audits_the_live_list(
    vault: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The post-apply audit path: read what ob actually holds, including its
    fileTypes, rather than trusting the string someone meant to apply."""
    xdg = tmp_path / "xdg"
    state = xdg / "obsidian-headless" / "sync" / "vault-id-1"
    state.mkdir(parents=True)
    (state / "config.json").write_text(
        json.dumps(
            {
                "vaultId": "vault-id-1",
                "vaultName": "personal-kept-test",
                "vaultPath": str(vault),
                "fileTypes": ["image", "audio", "pdf", "video"],
                "excludedFolders": ["20-projects/_dashboard", "30-areas/hapax/ocr/nope"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(vault), "--from-sync-config", "--json"],
        capture_output=True,
        text=True,
        check=False,
        env={**__import__("os").environ, "XDG_CONFIG_HOME": str(xdg)},
    )
    assert result.returncode == REFUSED, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["vault_name"] == "personal-kept-test"
    assert report["source"] == "sync-config"
    assert report["entries_unmatchable"] == 1


def test_no_sync_config_is_an_error_not_a_silent_pass(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(vault), "--from-sync-config"],
        capture_output=True,
        text=True,
        check=False,
        env={**__import__("os").environ, "XDG_CONFIG_HOME": str(tmp_path / "empty")},
    )
    assert result.returncode == ERROR
    assert "no ob sync" in result.stderr


def test_invalid_file_type_refuses(vault: pathlib.Path) -> None:
    result = _run(str(vault), "--excluded-folders", "20-projects", "--file-types", "img")
    assert result.returncode == ERROR
    assert "invalid file type" in result.stderr


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("note.md", "md"),
        ("IMAGE.PNG", "png"),
        (".hidden", ""),  # leading dot is not an extension (cli.js `$`)
        ("trailing.", ""),
        ("no-extension", ""),
        ("two.dots.canvas", "canvas"),
    ],
)
def test_extension_parsing_matches_client(name: str, expected: str) -> None:
    assert preflight._extension(name) == expected


def test_webm_counts_as_audio_or_video() -> None:
    assert preflight._classify("webm") == "audio_or_video"
    assert preflight._admitted("audio_or_video", frozenset({"video"}))
    assert preflight._admitted("audio_or_video", frozenset({"audio"}))
    assert not preflight._admitted("audio_or_video", frozenset({"pdf"}))


def test_native_classes_ignore_file_types() -> None:
    """md/canvas/base sync regardless of --file-types, per cli.js."""
    for ext in ("md", "canvas", "base"):
        assert preflight._admitted(preflight._classify(ext), frozenset())
