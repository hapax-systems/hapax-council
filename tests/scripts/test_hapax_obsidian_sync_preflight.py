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
import warnings

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
    assert verdicts["30-areas/hapax/ocr/pages-nope"] == "unmatchable"
    assert verdicts["20-projects/_dashboard"] == "ok"
    # The png is NOT excluded, because the entry naming it cannot match.
    assert report["predicted_upload"]["by_ext"]["png"]["files"] == 1


def test_wrong_prefix_is_the_real_world_shape(vault: pathlib.Path) -> None:
    """'ocr/pages' instead of '30-areas/hapax/ocr/pages' — the exact 2026-09-14
    defect. The directory exists, but not at that vault-relative path."""
    result = _run(str(vault), "--excluded-folders", "ocr/pages", "--json")
    assert result.returncode == REFUSED
    report = json.loads(result.stdout)
    assert report["findings"][0]["verdict"] == "unmatchable"
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
    assert report["findings"][0]["verdict"] == "unmatchable"
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
    finding = json.loads(result.stdout)["findings"][0]
    assert finding["verdict"] == "unmatchable"
    assert "names a file" in finding["detail"]


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


def _write_live_config(xdg: pathlib.Path, vault: pathlib.Path, **overrides: object) -> pathlib.Path:
    """Write a config.json in the schema ob ACTUALLY persists.

    This matters and is pinned deliberately. cli.js stores the live object via
    ``ys(t.vaultId, t)`` using ``ignoreFolders`` / ``allowTypes`` /
    ``allowSpecialFiles``; only the printer ``_r(t)`` renames those to
    ``excludedFolders`` / ``fileTypes`` / ``configs`` for ``sync-status --json``.
    An earlier version of this fixture used the PRINTED names, so it passed while
    the reader found nothing in a real file — a fixture that encoded the bug.
    Verified against a production config holding 17 exclusions, in which
    ``allowTypes`` was absent entirely because the default was never overridden.
    """
    state = xdg / "obsidian-headless" / "sync" / "vault-id-1"
    state.mkdir(parents=True, exist_ok=True)
    config: dict = {
        "vaultId": "vault-id-1",
        "vaultName": "personal-kept-test",
        "vaultPath": str(vault),
        "host": "sync-72.obsidian.md",
        "encryptionVersion": 3,
        "encryptionKey": "not-a-real-key",
        "encryptionSalt": "00",
        "conflictStrategy": "merge",
        "deviceName": "podium-headless",
        "ignoreFolders": ["20-projects/_dashboard", "30-areas/hapax/ocr/nope"],
    }
    config.update(overrides)
    path = state / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _run_env(vault: pathlib.Path, xdg: pathlib.Path, *args: str):
    import os as _os

    return subprocess.run(
        [sys.executable, str(SCRIPT), str(vault), *args],
        capture_output=True,
        text=True,
        check=False,
        env={**_os.environ, "XDG_CONFIG_HOME": str(xdg)},
    )


def test_from_sync_config_reads_the_persisted_key_not_the_printed_one(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """The audit must find a real list. Reading ``excludedFolders`` out of the
    FILE yields nothing, which would pass an audit of a broken list."""
    xdg = tmp_path / "xdg"
    _write_live_config(xdg, vault)
    result = _run_env(vault, xdg, "--from-sync-config", "--json")
    assert result.returncode == REFUSED, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["vault_name"] == "personal-kept-test"
    assert report["source"] == "sync-config"
    assert report["entries_total"] == 2, "persisted ignoreFolders was not read"
    assert report["entries_unmatchable"] == 1
    assert report["file_types"] == list(preflight.DEFAULT_FILE_TYPES)


def test_absent_allow_types_means_the_default_set(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """ob DELETES allowTypes when the selection is default, so absence must resolve
    to the default — the production config measured 2026-09-14 had no such key."""
    xdg = tmp_path / "xdg"
    _write_live_config(xdg, vault, ignoreFolders=["20-projects/_dashboard"])
    result = _run_env(vault, xdg, "--from-sync-config", "--json")
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["entries_total"] == 1, "persisted ignoreFolders was not read"
    assert report["file_types"] == list(preflight.DEFAULT_FILE_TYPES)
    assert "jsonl" not in report["predicted_upload"]["by_ext"]


def test_nondefault_allow_types_is_honoured(vault: pathlib.Path, tmp_path: pathlib.Path) -> None:
    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard"],
        allowTypes=["image", "audio", "pdf", "video", "unsupported"],
    )
    report = json.loads(_run_env(vault, xdg, "--from-sync-config", "--json").stdout)
    assert "unsupported" in report["file_types"]
    assert report["predicted_upload"]["by_ext"]["jsonl"]["bytes"] == 4242


def test_empty_live_exclusion_list_is_refused_not_a_clean_pass(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """An audit finding no list must not read as a clean bill of health."""
    xdg = tmp_path / "xdg"
    _write_live_config(xdg, vault, ignoreFolders=[])
    result = _run_env(vault, xdg, "--from-sync-config", "--json")
    assert result.returncode == REFUSED
    assert "configures NO exclusions" in result.stderr


def test_unrecognized_config_schema_is_an_error(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """If the required ob keys are gone the schema moved; refuse rather than
    silently report 'no exclusions'."""
    xdg = tmp_path / "xdg"
    state = xdg / "obsidian-headless" / "sync" / "vault-id-1"
    state.mkdir(parents=True)
    (state / "config.json").write_text(
        json.dumps({"vaultPath": str(vault), "somethingElse": 1}), encoding="utf-8"
    )
    result = _run_env(vault, xdg, "--from-sync-config")
    assert result.returncode == ERROR
    assert "does not look like an ob sync config" in result.stderr


@pytest.mark.parametrize("entry", ["20-projects/../20-projects", "20-projects/.", "./20-projects"])
def test_internal_dot_components_are_refused(vault: pathlib.Path, entry: str) -> None:
    """The filesystem resolves dot segments, so an existence check alone passes
    them — but ob matches raw relative paths, which never contain dot segments,
    so such an entry silently excludes nothing."""
    result = _run(str(vault), "--excluded-folders", entry, "--json")
    assert result.returncode == REFUSED, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["findings"][0]["verdict"] == "unmatchable"
    assert report["entries_effective"] == 0


def test_nfc_normalization_mismatch_is_refused(vault: pathlib.Path) -> None:
    """ob emits NFC paths (``Ne``) but matches ignoreFolders literally, so a
    decomposed on-disk name that an existence check accepts can never match. The
    entry must be refused and the data must show as still uploading."""
    nfd = "café"  # e + combining acute — what an existence check would find
    nfc = "café"
    target = vault / "30-areas" / nfd
    target.mkdir()
    (target / "private.md").write_bytes(b"p" * 77)

    refused = _run(str(vault), "--excluded-folders", f"30-areas/{nfd}", "--json")
    assert refused.returncode == REFUSED, refused.stdout + refused.stderr
    report = json.loads(refused.stdout)
    assert report["findings"][0]["verdict"] == "unmatchable"
    assert "NFC" in report["findings"][0]["detail"]
    paths = {item["path"] for item in report["largest_included_files"]}
    assert f"30-areas/{nfc}/private.md" in paths, "the file ob would upload is not shown"

    # The NFC form — the one ob actually compares — is accepted and excludes it.
    accepted = _run(str(vault), "--excluded-folders", f"30-areas/{nfc}", "--json")
    assert accepted.returncode == OK, accepted.stdout + accepted.stderr
    kept = {item["path"] for item in json.loads(accepted.stdout)["largest_included_files"]}
    assert not any("private.md" in p for p in kept)


def test_hidden_entry_is_effective_but_annotated(vault: pathlib.Path) -> None:
    """ob runs the ignoreFolders loop BEFORE the hidden check, so a dotted entry DOES
    match and must not be refused. It just cannot change anything here, which is
    reported rather than treated as an error."""
    result = _run(str(vault), "--excluded-folders", "30-areas/.venv", "--json")
    assert result.returncode == OK, result.stdout + result.stderr
    finding = json.loads(result.stdout)["findings"][0]
    assert finding["verdict"] == "ok"
    assert "nothing under it syncs" in finding["no_effect_reason"]


def test_config_dir_exclusion_is_effective_when_configs_are_enabled(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """The case the blanket dotted-refusal broke: with config syncing on, a
    `.obsidian/...` exclusion is real and must remove that file from the total."""
    obsidian = vault / ".obsidian"
    (obsidian / "snippets").mkdir(parents=True)
    (obsidian / "app.json").write_bytes(b"a" * 10)
    (obsidian / "snippets" / "x.css").write_bytes(b"d" * 30)
    xdg = tmp_path / "xdg"

    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard", "30-areas/hapax/ocr/pages"],
        allowSpecialFiles=["app", "appearance-data"],
    )
    without = json.loads(_run_env(vault, xdg, "--from-sync-config", "--json").stdout)
    assert without["config_uploads"]["bytes"] == 40

    _write_live_config(
        xdg,
        vault,
        ignoreFolders=[
            "20-projects/_dashboard",
            "30-areas/hapax/ocr/pages",
            ".obsidian/snippets",
        ],
        allowSpecialFiles=["app", "appearance-data"],
    )
    result = _run_env(vault, xdg, "--from-sync-config", "--json")
    assert result.returncode == OK, result.stdout + result.stderr
    with_excl = json.loads(result.stdout)
    assert with_excl["config_uploads"]["bytes"] == 10, "config-dir exclusion had no effect"
    findings = {f["normalized"]: f for f in with_excl["findings"]}
    assert findings[".obsidian/snippets"]["verdict"] == "ok"
    assert "no_effect_reason" not in findings[".obsidian/snippets"]


def test_empty_cli_file_types_restores_defaults(vault: pathlib.Path) -> None:
    """cli.js deletes allowTypes on an empty --file-types, restoring defaults; an
    empty SET here would under-predict every attachment that will upload."""
    result = _run(
        str(vault), "--excluded-folders", "20-projects/_dashboard", "--file-types", "", "--json"
    )
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["file_types"] == list(preflight.DEFAULT_FILE_TYPES)
    assert report["predicted_upload"]["by_ext"]["png"]["files"] == 1


def test_persisted_empty_allow_types_means_no_attachments(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """An empty persisted array is NOT absence: JS `[] || me` keeps `[]`, so ob
    syncs no attachments. Python's falsy `[]` would silently restore defaults."""
    xdg = tmp_path / "xdg"
    _write_live_config(xdg, vault, ignoreFolders=["20-projects/_dashboard"], allowTypes=[])
    result = _run_env(vault, xdg, "--from-sync-config", "--json")
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["file_types"] == []
    assert "png" not in report["predicted_upload"]["by_ext"], "attachments must be excluded"
    assert report["predicted_upload"]["by_ext"]["md"]["files"] == 3  # native still syncs


def test_unreadable_subtree_refuses_instead_of_reporting_a_floor(
    vault: pathlib.Path,
) -> None:
    """A skipped subtree makes every total a floor. Exiting 0 with a partial count
    would let an incomplete number serve as verification evidence."""
    locked = vault / "30-areas" / "locked"
    locked.mkdir()
    (locked / "secret.md").write_bytes(b"s" * 999)
    locked.chmod(0o000)
    try:
        result = _run(str(vault), "--excluded-folders", "20-projects/_dashboard", "--json")
        assert result.returncode == ERROR, result.stdout + result.stderr
        assert "FLOOR" in result.stderr
        assert json.loads(result.stdout)["traversal_errors"]
    finally:
        locked.chmod(0o755)


def test_usage_error_does_not_collide_with_refused(vault: pathlib.Path) -> None:
    """argparse exits 2 by default, which would be indistinguishable from 'the list
    would fail open' — the one status a caller must be able to branch on."""
    missing_source = _run(str(vault))
    assert missing_source.returncode == ERROR
    assert "error:" in missing_source.stderr
    assert "Next:" in missing_source.stderr, "a usage error must name the next action too"


def test_config_errors_name_a_next_action(vault: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """executive_function: errors include next actions."""
    result = _run_env(vault, tmp_path / "empty-xdg", "--from-sync-config")
    assert result.returncode == ERROR
    assert "Next:" in result.stderr


@pytest.mark.parametrize(
    ("entry", "needle"),
    [
        ("/20-projects", "not vault-relative"),
        ("20-projects//_dashboard", "doubled slash"),
        ("", "empty entry"),
    ],
)
def test_structurally_unmatchable_entries_are_refused(
    vault: pathlib.Path, entry: str, needle: str
) -> None:
    result = _run(str(vault), "--excluded-folders", entry, "--json")
    assert result.returncode == REFUSED, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["entries_effective"] == 0
    assert needle in report["findings"][0]["detail"]


def test_per_file_stat_failure_refuses(vault: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """A dangling symlink makes os.stat fail for ONE file (the directory case is
    covered separately). A partial total must still not exit 0.

    The link must point OUTSIDE the vault: an in-vault target overlaps the watched
    root, so ob skips it and there is no stat to fail — which is itself pinned by
    test_in_vault_file_alias_is_skipped.
    """
    (vault / "30-areas" / "dangling.md").symlink_to(tmp_path / "outside-gone.md")
    result = _run(str(vault), "--excluded-folders", "20-projects/_dashboard", "--json")
    assert result.returncode == ERROR, result.stdout + result.stderr
    errors = json.loads(result.stdout)["traversal_errors"]
    assert any("dangling.md" in e["path"] for e in errors)


@pytest.mark.parametrize(
    ("name", "selection", "expected_files"),
    [
        ("track.mp3", "audio", 1),
        ("track.mp3", "video", 0),
        ("clip.mp4", "video", 1),
        ("clip.mp4", "audio", 0),
        ("doc.pdf", "pdf", 1),
        ("doc.pdf", "image", 0),
    ],
)
def test_ordinary_attachment_classes_gate_on_the_selection(
    vault: pathlib.Path, name: str, selection: str, expected_files: int
) -> None:
    """The webm dual-class and native cases are pinned elsewhere; these are the
    plain audio/video/pdf branches."""
    (vault / "90-attachments").mkdir(exist_ok=True)
    (vault / "90-attachments" / name).write_bytes(b"a" * 64)
    report = json.loads(
        _run(
            str(vault),
            "--excluded-folders",
            "20-projects/_dashboard,30-areas/hapax/ocr/pages",
            "--file-types",
            selection,
            "--json",
        ).stdout
    )
    ext = name.rsplit(".", 1)[1]
    got = report["predicted_upload"]["by_ext"].get(ext, {"files": 0})["files"]
    assert got == expected_files


@pytest.mark.parametrize(
    "payload",
    [
        "[]",  # valid JSON, not an object
        '"a string"',
    ],
)
def test_non_object_config_is_skipped_with_a_named_reason(
    vault: pathlib.Path, tmp_path: pathlib.Path, payload: str
) -> None:
    """Must not raise AttributeError at data.get: that escapes as exit 1 and a
    traceback instead of the documented exit 3 with a next action."""
    xdg = tmp_path / "xdg"
    state = xdg / "obsidian-headless" / "sync" / "broken"
    state.mkdir(parents=True)
    (state / "config.json").write_text(payload, encoding="utf-8")
    result = _run_env(vault, xdg, "--from-sync-config")
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert "Unreadable config(s) skipped" in result.stderr
    assert "Next:" in result.stderr


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("allowTypes", None),
        ("allowTypes", "image"),
        ("ignoreFolders", None),
        ("ignoreFolders", "20-projects/_dashboard"),
        ("ignoreFolders", [1, 2]),
    ],
)
def test_wrong_typed_config_fields_are_refused_with_an_action(
    vault: pathlib.Path, tmp_path: pathlib.Path, key: str, value: object
) -> None:
    """allowTypes: null previously raised TypeError inside file-type resolution."""
    xdg = tmp_path / "xdg"
    _write_live_config(xdg, vault, **{key: value})
    result = _run_env(vault, xdg, "--from-sync-config")
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert f"'{key}'" in result.stderr
    assert "Next:" in result.stderr


def test_a_corrupt_other_vault_config_does_not_break_this_audit(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """A broken config belonging to a different vault must be skipped, not fatal."""
    xdg = tmp_path / "xdg"
    _write_live_config(xdg, vault, ignoreFolders=["20-projects/_dashboard"])
    other = xdg / "obsidian-headless" / "sync" / "aaa-other"
    other.mkdir(parents=True)
    (other / "config.json").write_text("{not json", encoding="utf-8")
    result = _run_env(vault, xdg, "--from-sync-config", "--json")
    assert result.returncode == OK, result.stdout + result.stderr
    assert json.loads(result.stdout)["entries_effective"] == 1


@pytest.mark.parametrize("space", [" ", " "])
def test_nonbreaking_space_exclusions_are_refused_and_the_fix_accepted(
    vault: pathlib.Path, space: str
) -> None:
    """cli.js ``Cs(s) = s.replace(/\\u00A0|\\u202F/g, " ")`` runs before NFC, so ob
    emits an ORDINARY space. An entry carrying the nonbreaking form can never match,
    and NFC alone does not catch it."""
    raw = f"private{space}files"
    target = vault / "30-areas" / raw
    target.mkdir()
    (target / "secret.md").write_bytes(b"s" * 77)

    refused = _run(str(vault), "--excluded-folders", f"30-areas/{raw}", "--json")
    assert refused.returncode == REFUSED, refused.stdout + refused.stderr
    report = json.loads(refused.stdout)
    assert report["entries_effective"] == 0
    paths = {item["path"] for item in report["largest_included_files"]}
    assert "30-areas/private files/secret.md" in paths

    ordinary = _run(str(vault), "--excluded-folders", "30-areas/private files", "--json")
    assert ordinary.returncode == OK, ordinary.stdout + ordinary.stderr
    accepted = json.loads(ordinary.stdout)
    assert accepted["entries_effective"] == 1
    # The only difference between the two runs is whether secret.md is excluded.
    delta = report["predicted_upload"]["bytes"] - accepted["predicted_upload"]["bytes"]
    assert delta == 77
    assert not any("secret.md" in item["path"] for item in accepted["largest_included_files"])


def test_internal_alias_is_skipped_like_the_client(vault: pathlib.Path) -> None:
    """cli.js ``reconcileSymbolicLinkCreation`` resolves the link and RETURNS when the
    target overlaps an already-watched resolved path. The vault root is always
    watched, so a vault-internal alias is reconciled through neither route: it is
    skipped, not counted twice. Counting both routes over-predicts."""
    target = vault / "30-areas" / "target"
    (target / "private").mkdir(parents=True)
    (target / "private" / "secret.md").write_bytes(b"s" * 77)
    (vault / "alias").symlink_to(target, target_is_directory=True)

    result = _run(str(vault), "--excluded-folders", "30-areas/hapax", "--json")
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    paths = {item["path"] for item in report["largest_included_files"]}
    # The real route is content and counts once; the alias route does not exist for ob.
    assert "30-areas/target/private/secret.md" in paths
    assert not any(p.startswith("alias/") for p in paths)
    assert report["symlinks_skipped_overlapping"] == [
        {"path": "alias", "target": str(target.resolve())}
    ]
    assert report["symlinks_escaping_vault"] == []
    # Counted exactly once: excluding the real route removes it entirely.
    excluded = json.loads(
        _run(
            str(vault), "--excluded-folders", "30-areas/hapax,30-areas/target/private", "--json"
        ).stdout
    )
    delta = report["predicted_upload"]["bytes"] - excluded["predicted_upload"]["bytes"]
    assert delta == 77, "the aliased file was counted more than once"


def test_in_vault_file_alias_is_skipped(vault: pathlib.Path) -> None:
    """The overlap rule applies before ob distinguishes a file from a directory, so a
    file alias pointing inside the vault is not uploaded — even though os.stat would
    follow it and report the target's size."""
    secret = vault / "30-areas" / "hapax" / "keep.md"  # 50 bytes, already in the tree
    (vault / "alias.md").symlink_to(secret)
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--json",
    )
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert not any(i["path"] == "alias.md" for i in report["largest_included_files"])
    assert [link["path"] for link in report["symlinks_skipped_overlapping"]] == ["alias.md"]
    assert report["predicted_upload"]["bytes"] == 161, "the aliased file was counted twice"


def test_escaping_file_link_is_followed(vault: pathlib.Path, tmp_path: pathlib.Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"o" * 33)
    (vault / "alias.md").symlink_to(outside)
    report = json.loads(
        _run(
            str(vault),
            "--excluded-folders",
            "20-projects/_dashboard,30-areas/hapax/ocr/pages",
            "--json",
        ).stdout
    )
    assert report["predicted_upload"]["bytes"] == 161 + 33
    assert [link["path"] for link in report["symlinks_escaping_vault"]] == ["alias.md"]


def test_file_link_does_not_reserve_its_target(vault: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """cli.js installs a watcher only in the isDirectory branch, so a FILE link is
    admitted without reserving its target. Reserving it would make one file link
    suppress a later legitimate upload of the same path."""
    outside = tmp_path / "shared.md"
    outside.write_bytes(b"s" * 21)
    (vault / "a-alias.md").symlink_to(outside)
    (vault / "b-alias.md").symlink_to(outside)
    report = json.loads(
        _run(
            str(vault),
            "--excluded-folders",
            "20-projects/_dashboard,30-areas/hapax/ocr/pages",
            "--json",
        ).stdout
    )
    paths = {i["path"] for i in report["largest_included_files"]}
    assert {"a-alias.md", "b-alias.md"} <= paths, "a file link reserved its target"
    assert report["predicted_upload"]["bytes"] == 161 + 21 + 21
    assert report["symlinks_skipped_overlapping"] == []


def test_two_aliases_to_one_dir_is_refused_as_scheduling_dependent(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """A directory link IS watched once admitted, but `listRecursive` pushes every
    child's scan and awaits Promise.all — so two aliases can BOTH clear the overlap
    check before either installs its watcher. Whether one or both upload depends on
    scheduling, so there is no exact total to report and the tool must refuse rather
    than pick one. (An earlier version asserted exactly one always uploads.)"""
    outside = tmp_path / "shared"
    outside.mkdir()
    (outside / "note.md").write_bytes(b"n" * 31)
    (vault / "a-link").symlink_to(outside, target_is_directory=True)
    (vault / "b-link").symlink_to(outside, target_is_directory=True)
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--json",
    )
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert "CONCURRENTLY" in result.stderr
    assert "Next:" in result.stderr
    report = json.loads(result.stdout)
    assert [link["path"] for link in report["symlinks_scheduling_dependent"]] == ["b-link"]


def test_excluding_an_alias_does_not_hide_the_race(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Scanning and admission are separate in ob: `listRecursive` reconciles links and
    installs watchers without consulting ignoreFolders, which `allowSyncFile` applies
    only afterwards. So an EXCLUDED alias still competes for the watcher, and pruning
    it before the link check would hide a race that really exists."""
    outside = tmp_path / "shared"
    outside.mkdir()
    (outside / "note.md").write_bytes(b"n" * 31)
    (vault / "a-link").symlink_to(outside, target_is_directory=True)
    (vault / "b-link").symlink_to(outside, target_is_directory=True)
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages,b-link",
        "--json",
    )
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert "an excluded alias still competes" in result.stderr
    report = json.loads(result.stdout)
    assert [link["path"] for link in report["symlinks_scheduling_dependent"]] == ["b-link"]


def test_link_beneath_an_excluded_parent_is_still_discovered(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Exclusions do not prune ob's SCAN, so a link nested inside an excluded directory
    still competes for its target's watcher. Pruning excluded subtrees hid the race
    entirely — the one case the directly-excluded-alias test could not reach."""
    outside = tmp_path / "shared"
    outside.mkdir()
    (outside / "note.md").write_bytes(b"n" * 77)
    (vault / "excluded").mkdir()
    (vault / "excluded" / "nested").symlink_to(outside, target_is_directory=True)
    (vault / "visible").symlink_to(outside, target_is_directory=True)

    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages,excluded",
        "--json",
    )
    assert result.returncode == ERROR, result.stdout + result.stderr
    report = json.loads(result.stdout)
    racy = [link["path"] for link in report["symlinks_scheduling_dependent"]]
    # Exactly one of the pair is flagged; WHICH one depends on walk order, which is an
    # artifact of this tool rather than of the client, so only detection is pinned.
    assert len(racy) == 1, f"race beneath an excluded parent went undetected: {racy}"
    admitted = [link["path"] for link in report["symlinks_escaping_vault"]]
    assert sorted(racy + admitted) == ["excluded/nested", "visible"]


def test_excluded_subtree_files_are_still_not_counted(vault: pathlib.Path) -> None:
    """Discovering links inside excluded subtrees must not start COUNTING their files."""
    (vault / "excluded" / "deep").mkdir(parents=True)
    (vault / "excluded" / "deep" / "note.md").write_bytes(b"e" * 500)
    report = json.loads(
        _run(
            str(vault),
            "--excluded-folders",
            "20-projects/_dashboard,30-areas/hapax/ocr/pages,excluded",
            "--json",
        ).stdout
    )
    assert report["predicted_upload"]["bytes"] == 161
    assert not any(p["path"].startswith("excluded/") for p in report["largest_included_files"])


def test_file_alias_then_directory_link_is_ambiguous(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """A file link installs no watcher, but a later DIRECTORY link installs one over
    its target — so whether the file alias was admitted depends on which resolved
    first. File targets must be remembered even though they never suppress a peer."""
    outside = tmp_path / "shared"
    outside.mkdir()
    (outside / "note.md").write_bytes(b"n" * 77)
    (vault / "00-inbox").mkdir(exist_ok=True)
    (vault / "a.md").symlink_to(outside / "note.md")  # sorts before 'sub'
    (vault / "sub").mkdir()
    (vault / "sub" / "dirlink").symlink_to(outside, target_is_directory=True)

    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--json",
    )
    assert result.returncode == ERROR, result.stdout + result.stderr
    racy = [link["path"] for link in json.loads(result.stdout)["symlinks_scheduling_dependent"]]
    assert racy == ["sub/dirlink"], racy


def test_two_file_aliases_to_one_file_stay_exact(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """The other order: neither file link installs a watcher, so both are admitted
    deterministically and this must NOT refuse."""
    outside = tmp_path / "shared.md"
    outside.write_bytes(b"s" * 21)
    (vault / "a-alias.md").symlink_to(outside)
    (vault / "b-alias.md").symlink_to(outside)
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--json",
    )
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["symlinks_scheduling_dependent"] == []
    assert report["predicted_upload"]["bytes"] == 161 + 21 + 21


def test_refusal_names_actions_that_actually_work(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """A plain rename leaves the target unchanged and re-triggers the refusal, so it
    must not be offered as a remedy."""
    outside = tmp_path / "shared"
    outside.mkdir()
    (outside / "note.md").write_bytes(b"n" * 31)
    (vault / "a-link").symlink_to(outside, target_is_directory=True)
    (vault / "b-link").symlink_to(outside, target_is_directory=True)
    err = _run(str(vault), "--excluded-folders", "20-projects/_dashboard").stderr
    assert "DELETE" in err
    assert "retarget" in err
    assert "A plain rename does NOT help" in err


def test_emitted_path_collision_is_refused(vault: pathlib.Path) -> None:
    """Two on-disk spellings can normalize to ONE emitted path, so they are one remote
    file and counting both double-counts. Which local copy wins is not determinable."""
    area = vault / "30-areas"
    (area / "café.md").write_bytes(b"c" * 40)  # NFC
    (area / "café.md").write_bytes(b"d" * 41)  # NFD — same emitted path
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--json",
    )
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert "ONE remote file" in result.stderr
    collisions = json.loads(result.stdout)["emitted_path_collisions"]
    assert [c["path"] for c in collisions] == ["30-areas/café.md"]


def test_nonbreaking_space_collision_is_refused(vault: pathlib.Path) -> None:
    area = vault / "30-areas"
    (area / "a b.md").write_bytes(b"c" * 40)
    (area / "a b.md").write_bytes(b"d" * 41)  # nbsp -> ordinary space when emitted
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--json",
    )
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert json.loads(result.stdout)["emitted_path_collisions"]


def test_collision_against_a_directory_is_detected(vault: pathlib.Path) -> None:
    """A DIRECTORY occupies an emitted name too. Registering only admitted files missed
    this: the directory took the name and the colliding file was never compared."""
    area = vault / "30-areas"
    nbsp = chr(0xA0)  # built from the codepoint: a literal is invisible in source
    (area / "a b.md").mkdir()  # a directory whose name ends in .md
    (area / f"a{nbsp}b.md").write_bytes(b"f" * 77)  # nbsp -> same emitted path
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--json",
    )
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert [c["path"] for c in json.loads(result.stdout)["emitted_path_collisions"]] == [
        "30-areas/a b.md"
    ]


def test_collision_against_an_excluded_file_is_detected(vault: pathlib.Path) -> None:
    """An excluded file still occupies the emitted name, so a collision with it is real
    even though the excluded one never uploads."""
    area = vault / "30-areas"
    nbsp = chr(0xA0)
    (area / "a b.md").write_bytes(b"x" * 40)  # ordinary space, will be excluded
    (area / f"a{nbsp}b.md").write_bytes(b"y" * 77)  # nbsp
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages,30-areas/a b.md",
        "--json",
    )
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert json.loads(result.stdout)["emitted_path_collisions"]


def test_collision_against_an_oversized_file_is_detected(vault: pathlib.Path) -> None:
    """Likewise a file dropped by the size limit — it is still the name's occupant."""
    area = vault / "30-areas"
    nbsp = chr(0xA0)
    (area / "a b.md").write_bytes(b"x" * 40)
    (area / f"a{nbsp}b.md").write_bytes(b"y" * 101)  # nbsp, over the limit below
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--per-file-max",
        "100",
        "--json",
    )
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert json.loads(result.stdout)["emitted_path_collisions"]


def test_backslash_in_a_name_is_emitted_as_a_separator(
    vault: pathlib.Path,
) -> None:
    """cli.js `_e` collapses runs of "/" OR "\\" to one "/", and a backslash is a legal
    Linux filename character — so `x\\y` and `x/y` are the SAME emitted path."""
    area = vault / "30-areas"
    (area / "x\\y").write_bytes(b"b" * 50)  # one file literally named 'x\y'
    (area / "x").mkdir()
    (area / "x" / "y").write_bytes(b"f" * 60)
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--json",
    )
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert [c["path"] for c in json.loads(result.stdout)["emitted_path_collisions"]] == [
        "30-areas/x/y"
    ]


def test_backslash_name_alone_is_emitted_with_a_separator(vault: pathlib.Path) -> None:
    """Without a competitor it is not a collision, but the emitted path must still
    carry the rewritten separator."""
    (vault / "30-areas" / "p\\q.md").write_bytes(b"b" * 50)
    report = json.loads(
        _run(
            str(vault),
            "--excluded-folders",
            "20-projects/_dashboard,30-areas/hapax/ocr/pages",
            "--json",
        ).stdout
    )
    paths = {item["path"] for item in report["largest_included_files"]}
    assert "30-areas/p/q.md" in paths, paths


def test_ancestor_watcher_is_deterministic_not_a_race(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """A link found BENEATH an accepted link is governed by that ancestor's watcher,
    which exists before its descendants are scanned — so the skip is deterministic and
    must not be reported as scheduling-dependent."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "note.md").write_bytes(b"n" * 77)
    (outside / "back").symlink_to(outside, target_is_directory=True)
    (vault / "linked").symlink_to(outside, target_is_directory=True)

    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--json",
    )
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["symlinks_scheduling_dependent"] == []
    assert [link["path"] for link in report["symlinks_escaping_vault"]] == ["linked"]
    assert [link["path"] for link in report["symlinks_skipped_overlapping"]] == ["linked/back"]
    assert report["predicted_upload"]["bytes"] == 161 + 77


def test_config_uploads_honour_the_per_file_limit(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """The size skip lives in the shared sync loop, so it governs config files too."""
    obsidian = vault / ".obsidian"
    obsidian.mkdir()
    (obsidian / "app.json").write_bytes(b"a" * 4096)
    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard", "30-areas/hapax/ocr/pages"],
        allowSpecialFiles=["app"],
    )
    report = json.loads(
        _run_env(vault, xdg, "--from-sync-config", "--per-file-max", "4095", "--json").stdout
    )
    assert report["config_uploads"]["bytes"] == 0, "an oversize config file was counted"
    assert [f["path"] for f in report["config_uploads"]["files_over_per_file_max"]] == [
        ".obsidian/app.json"
    ]
    assert any(f["path"] == ".obsidian/app.json" for f in report["files_over_per_file_max"]), (
        "config skips must surface in the top-level list too"
    )


@pytest.mark.parametrize("parent", ["plugins", "themes"])
def test_stray_file_in_plugins_or_themes_is_skipped_not_an_error(
    vault: pathlib.Path, tmp_path: pathlib.Path, parent: str
) -> None:
    """cli.js iterates only `.folders` there, so a stray FILE is ignored. Building
    candidates under it would stat `plugins/<file>/manifest.json` and raise ENOTDIR,
    turning a case ob ignores into a refusal."""
    obsidian = vault / ".obsidian"
    (obsidian / parent).mkdir(parents=True)
    (obsidian / parent / "README.md").write_bytes(b"r" * 5)
    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard", "30-areas/hapax/ocr/pages"],
        allowSpecialFiles=list(preflight.VALID_CONFIG_CATEGORIES),
    )
    result = _run_env(vault, xdg, "--from-sync-config", "--json")
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["traversal_errors"] == []
    assert report["config_uploads"]["files"] == 0


def test_one_alias_plus_a_root_overlap_is_still_exact(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Overlap with the VAULT ROOT is deterministic — `watch()` installs that watcher
    before `listAll()` — so an internal alias alongside an escaping link must not
    trigger the ambiguity refusal."""
    outside = tmp_path / "shared"
    outside.mkdir()
    (outside / "note.md").write_bytes(b"n" * 31)
    (vault / "escaping").symlink_to(outside, target_is_directory=True)
    (vault / "internal").symlink_to(vault / "30-areas", target_is_directory=True)
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--json",
    )
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["symlinks_scheduling_dependent"] == []
    assert [link["path"] for link in report["symlinks_escaping_vault"]] == ["escaping"]
    assert [link["path"] for link in report["symlinks_skipped_overlapping"]] == ["internal"]
    assert report["predicted_upload"]["bytes"] == 161 + 31


@pytest.mark.parametrize("config_dir", [".obsidian", ".obsidian-custom"])
def test_config_dir_setting_is_honoured(
    vault: pathlib.Path, tmp_path: pathlib.Path, config_dir: str
) -> None:
    """The configDir fallback was untested; a non-default config dir must still be
    scanned, and a wrong fallback would silently predict zero."""
    target = vault / config_dir
    target.mkdir()
    (target / "app.json").write_bytes(b"a" * 55)
    xdg = tmp_path / "xdg"
    overrides: dict = {
        "ignoreFolders": ["20-projects/_dashboard", "30-areas/hapax/ocr/pages"],
        "allowSpecialFiles": ["app"],
    }
    if config_dir != ".obsidian":
        overrides["configDir"] = config_dir
    _write_live_config(xdg, vault, **overrides)
    result = _run_env(vault, xdg, "--from-sync-config", "--json")
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["config_uploads"]["config_dir"] == config_dir
    assert report["config_uploads"]["bytes"] == 55


def test_absent_config_dir_setting_falls_back_to_dot_obsidian(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    obsidian = vault / ".obsidian"
    obsidian.mkdir()
    (obsidian / "app.json").write_bytes(b"a" * 12)
    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard", "30-areas/hapax/ocr/pages"],
        allowSpecialFiles=["app"],
    )
    report = json.loads(_run_env(vault, xdg, "--from-sync-config", "--json").stdout)
    assert report["config_uploads"]["config_dir"] == ".obsidian"
    assert report["config_uploads"]["bytes"] == 12


def test_hidden_link_does_not_suppress_a_visible_one(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Registration must happen AFTER hidden pruning. ob rejects a hidden path before
    registering its target, so a hidden link must not claim a target and make the
    visible link to the same place look like a duplicate — which would also make the
    result depend on which name the walk reached first."""
    outside = tmp_path / "shared"
    outside.mkdir()
    (outside / "note.md").write_bytes(b"n" * 44)
    # '.hidden' sorts before 'visible', so the hidden one is reached first.
    (vault / ".hidden").symlink_to(outside, target_is_directory=True)
    (vault / "visible").symlink_to(outside, target_is_directory=True)

    report = json.loads(
        _run(
            str(vault),
            "--excluded-folders",
            "20-projects/_dashboard,30-areas/hapax/ocr/pages",
            "--json",
        ).stdout
    )
    paths = {i["path"] for i in report["largest_included_files"]}
    assert "visible/note.md" in paths, "a hidden link suppressed a visible upload"
    assert not any(p.startswith(".hidden") for p in paths)
    assert report["predicted_upload"]["bytes"] == 161 + 44


def test_config_dir_symlink_is_followed(vault: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """The seed scanner reaches config files through adapter list/stat, which follow a
    link; only the watcher installer uses lstat. A plugin directory replaced by a link
    must still be counted."""
    obsidian = vault / ".obsidian"
    (obsidian / "plugins").mkdir(parents=True)
    real_plugin = tmp_path / "dataview"
    real_plugin.mkdir()
    (real_plugin / "main.js").write_bytes(b"m" * 77)
    (obsidian / "plugins" / "dataview").symlink_to(real_plugin, target_is_directory=True)

    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard", "30-areas/hapax/ocr/pages"],
        allowSpecialFiles=["community-plugin-data"],
    )
    result = _run_env(vault, xdg, "--from-sync-config", "--json")
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["config_uploads"]["bytes"] == 77, "config-dir symlink was not followed"


def test_link_to_a_vault_ancestor_is_skipped(vault: pathlib.Path) -> None:
    """A link to a directory CONTAINING the vault overlaps the other way round
    (``c.startsWith(n + sep)``) and must also be skipped — it is what stops the walk
    recursing forever."""
    (vault / "up").symlink_to(vault.parent, target_is_directory=True)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(vault),
            "--excluded-folders",
            "20-projects/_dashboard",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert [link["path"] for link in report["symlinks_skipped_overlapping"]] == ["up"]
    assert not any(
        p.startswith("up/") for p in {i["path"] for i in report["largest_included_files"]}
    )


def test_unreadable_config_directory_is_an_error_not_a_traceback(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    xdg = tmp_path / "xdg"
    root = xdg / "obsidian-headless" / "sync"
    root.mkdir(parents=True)
    root.chmod(0o000)
    try:
        result = _run_env(vault, xdg, "--from-sync-config")
        assert result.returncode == ERROR, result.stdout + result.stderr
        assert "Traceback" not in result.stderr
        assert "cannot read the ob sync state directory" in result.stderr
        assert "Next:" in result.stderr
    finally:
        root.chmod(0o755)


def test_persisted_entries_are_not_trimmed(vault: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """ob compares a PERSISTED entry byte for byte. Trimming it here certified
    ``"20-projects/_dashboard "``, which ob can never match."""
    xdg = tmp_path / "xdg"
    _write_live_config(xdg, vault, ignoreFolders=["20-projects/_dashboard "])
    result = _run_env(vault, xdg, "--from-sync-config", "--json")
    assert result.returncode == REFUSED, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["entries_effective"] == 0
    # The dashboard file ob would still upload must be visible in the prediction.
    assert any("_dashboard/huge.md" in item["path"] for item in report["largest_included_files"])


@pytest.mark.parametrize("char", ["\x1c", "\x1d", "\x1e", "\x1f", "\x85"])
def test_cli_trim_matches_js_not_python(vault: pathlib.Path, char: str) -> None:
    """Python's str.strip() removes these; JavaScript's trim() does not. Stripping
    them would certify an entry ob keeps verbatim and therefore cannot match."""
    result = _run(str(vault), "--excluded-folders", f"20-projects/_dashboard{char}", "--json")
    assert result.returncode == REFUSED, result.stdout + result.stderr
    assert json.loads(result.stdout)["entries_effective"] == 0


def test_cli_trim_removes_what_js_removes(vault: pathlib.Path) -> None:
    """The other direction: ob DOES trim these, so refusing them would be a false
    alarm. U+FEFF is the case Python's strip() misses."""
    for char in ("﻿", " ", "\t", " "):
        result = _run(
            str(vault), "--excluded-folders", f"{char}20-projects/_dashboard{char}", "--json"
        )
        assert result.returncode == OK, (char, result.stdout + result.stderr)
        assert json.loads(result.stdout)["entries_effective"] == 1


def test_enabled_config_syncing_is_counted(vault: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """With configs enabled ob uploads matching files from the config dir, which the
    main walk prunes as hidden. Omitting them under-predicts the whole directory."""
    obsidian = vault / ".obsidian"
    (obsidian / "plugins" / "dataview").mkdir(parents=True)
    (obsidian / "snippets").mkdir()
    (obsidian / "app.json").write_bytes(b"a" * 10)  # app
    (obsidian / "appearance.json").write_bytes(b"b" * 20)  # appearance
    (obsidian / "workspace.json").write_bytes(b"c" * 5000)  # never synced
    (obsidian / "snippets" / "x.css").write_bytes(b"d" * 30)  # appearance-data
    (obsidian / "plugins" / "dataview" / "main.js").write_bytes(b"e" * 40)  # community-plugin-data

    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard", "30-areas/hapax/ocr/pages"],
        allowSpecialFiles=["app", "appearance-data"],
    )
    report = json.loads(_run_env(vault, xdg, "--from-sync-config", "--json").stdout)
    uploads = report["config_uploads"]
    assert uploads["files"] == 2
    assert uploads["bytes"] == 40  # app.json 10 + snippets/x.css 30
    assert set(uploads["by_category"]) == {"app", "appearance-data"}
    # and they are folded into the headline total
    assert report["predicted_upload"]["bytes"] == 161 + 40


def test_config_syncing_disabled_counts_nothing(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "app.json").write_bytes(b"a" * 10)
    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg, vault, ignoreFolders=["20-projects/_dashboard", "30-areas/hapax/ocr/pages"]
    )
    report = json.loads(_run_env(vault, xdg, "--from-sync-config", "--json").stdout)
    assert report["config_uploads"]["files"] == 0
    assert report["predicted_upload"]["bytes"] == 161


def test_human_readable_output_reports_the_successful_case(vault: pathlib.Path) -> None:
    """Every other test reads --json, which would hide a broken default report."""
    result = _run(
        str(vault), "--excluded-folders", "20-projects/_dashboard,30-areas/hapax/ocr/pages"
    )
    assert result.returncode == OK, result.stdout + result.stderr
    out = result.stdout
    assert "exclusion entries: 2 total, 2 effective" in out
    assert "[ok  ] 20-projects/_dashboard" in out
    assert "predicted upload: 161 B" in out
    assert ".md: " in out


def test_human_readable_output_names_the_failing_entry(vault: pathlib.Path) -> None:
    result = _run(str(vault), "--excluded-folders", "nope")
    assert result.returncode == REFUSED
    assert "[FAIL] nope" in result.stdout
    assert "no such path in the vault" in result.stdout
    assert "REFUSED: 1 exclusion entry cannot match" in result.stderr


def test_validation_table_covers_every_persisted_field_read() -> None:
    """The omission class itself: round 5 added a field the reader used and the
    shape check did not cover. Adding a persisted field must require adding it here."""
    read_keys = {
        preflight.PERSISTED_EXCLUSIONS_KEY,
        preflight.PERSISTED_FILE_TYPES_KEY,
        preflight.PERSISTED_CONFIGS_KEY,
    }
    assert read_keys <= set(preflight.PERSISTED_LIST_FIELDS)


@pytest.mark.parametrize("value", [None, "app", [["app"]], [1]])
def test_malformed_allow_special_files_is_refused(
    vault: pathlib.Path, tmp_path: pathlib.Path, value: object
) -> None:
    """A bare string is the dangerous one: frozenset("app") is {'a','p'}, which
    matches no category and reports a confident zero."""
    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg, vault, ignoreFolders=["20-projects/_dashboard"], allowSpecialFiles=value
    )
    result = _run_env(vault, xdg, "--from-sync-config")
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert "allowSpecialFiles" in result.stderr
    assert "Next:" in result.stderr


def test_unknown_config_category_is_refused(vault: pathlib.Path, tmp_path: pathlib.Path) -> None:
    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard"],
        allowSpecialFiles=["app", "not-a-category"],
    )
    result = _run_env(vault, xdg, "--from-sync-config")
    assert result.returncode == ERROR
    assert "not-a-category" in result.stderr
    assert "Next:" in result.stderr


def test_unreadable_config_dir_refuses_like_the_main_walk(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """The config walk is a SECOND traversal; its failures must reach the same
    exit-3 guard, or an unreadable config dir certifies a partial total."""
    obsidian = vault / ".obsidian"
    obsidian.mkdir()
    (obsidian / "app.json").write_bytes(b"a" * 77)
    locked = obsidian / "snippets"
    locked.mkdir()
    (locked / "x.css").write_bytes(b"c" * 10)
    locked.chmod(0o000)
    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard"],
        allowSpecialFiles=["app", "appearance-data"],
    )
    try:
        result = _run_env(vault, xdg, "--from-sync-config", "--json")
        assert result.returncode == ERROR, result.stdout + result.stderr
        assert "FLOOR" in result.stderr
        errors = json.loads(result.stdout)["traversal_errors"]
        assert any("snippets" in e["path"] for e in errors)
    finally:
        locked.chmod(0o755)


@pytest.mark.parametrize(
    ("config_dir", "expected_needle"),
    [
        ("visible-config", "Invalid config directory"),
        (".bad/nested", "Invalid config directory"),
        (".bad\\nested", "Invalid config directory"),
        (42, "dotfolder name"),
    ],
)
def test_invalid_config_dir_is_refused(
    vault: pathlib.Path, tmp_path: pathlib.Path, config_dir: object, expected_needle: str
) -> None:
    """cli.js ``ws``/``Ss`` require a dotfolder NAME with no separators and THROW
    otherwise, so such a config cannot be in use. Scanning the named directory anyway
    would report a confident total for a directory ob never reads."""
    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard"],
        allowSpecialFiles=["app"],
        configDir=config_dir,
    )
    result = _run_env(vault, xdg, "--from-sync-config")
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert expected_needle in result.stderr
    assert "Next:" in result.stderr


def test_nonexistent_config_candidate_is_dropped_not_an_error(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """ob checks `exists()` and deletes the entry, so a dangling or absent candidate
    is not a traversal failure — only a real read error is."""
    obsidian = vault / ".obsidian"
    obsidian.mkdir()
    (obsidian / "app.json").symlink_to(obsidian / "gone.json")  # dangling
    (obsidian / "appearance.json").write_bytes(b"b" * 19)
    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard", "30-areas/hapax/ocr/pages"],
        allowSpecialFiles=["app", "appearance"],
    )
    result = _run_env(vault, xdg, "--from-sync-config", "--json")
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["traversal_errors"] == []
    assert report["config_uploads"]["bytes"] == 19
    assert set(report["config_uploads"]["by_category"]) == {"appearance"}


def test_config_scan_covers_each_enumerated_shape(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """The defining cases of the bounded enumeration, one per shape cli.js pushes:
    the literal `config` file, a top-level json, a theme pair, a snippet, and a plugin
    file — plus the two it explicitly refuses (workspace.json, node_modules)."""
    obsidian = vault / ".obsidian"
    (obsidian / "themes" / "moon").mkdir(parents=True)
    (obsidian / "snippets").mkdir()
    (obsidian / "plugins" / "dv").mkdir(parents=True)
    (obsidian / "plugins" / "node_modules").mkdir()
    (obsidian / "config").write_bytes(b"c" * 2)  # literal file named 'config'
    (obsidian / "app.json").write_bytes(b"a" * 3)
    (obsidian / "hotkeys.json").write_bytes(b"h" * 4)
    (obsidian / "community-plugins.json").write_bytes(b"p" * 5)
    (obsidian / "stray.json").write_bytes(b"s" * 6)  # core-plugin-data
    (obsidian / "workspace.json").write_bytes(b"w" * 900)  # never synced
    (obsidian / "themes" / "moon" / "theme.css").write_bytes(b"t" * 7)
    (obsidian / "themes" / "moon" / "manifest.json").write_bytes(b"m" * 8)
    (obsidian / "snippets" / "tweak.css").write_bytes(b"k" * 9)
    (obsidian / "plugins" / "dv" / "data.json").write_bytes(b"d" * 10)
    (obsidian / "plugins" / "node_modules" / "main.js").write_bytes(b"n" * 900)

    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard", "30-areas/hapax/ocr/pages"],
        allowSpecialFiles=list(preflight.VALID_CONFIG_CATEGORIES),
    )
    report = json.loads(_run_env(vault, xdg, "--from-sync-config", "--json").stdout)
    uploads = report["config_uploads"]
    # 3+4+5+6+7+8+9+10 = 52. Excluded: workspace.json and node_modules by name, and
    # the literal `config` file — cli.js PUSHES it into the scan queue, but that queue
    # only builds the local file index; admission still runs through allowSyncFile,
    # where `config` has no extension, so no category matches and it never uploads.
    assert uploads["bytes"] == 52
    assert uploads["by_category"] == {
        "app": {"bytes": 3, "files": 1},
        "appearance-data": {"bytes": 24, "files": 3},  # theme.css+manifest.json+snippet
        "community-plugin": {"bytes": 5, "files": 1},
        "community-plugin-data": {"bytes": 10, "files": 1},
        "core-plugin-data": {"bytes": 6, "files": 1},  # stray.json only
        "hotkey": {"bytes": 4, "files": 1},
    }


def test_config_scan_does_not_invent_depths(vault: pathlib.Path, tmp_path: pathlib.Path) -> None:
    """ob enumerates fixed shapes, so a plugin file one level too deep, a nested
    snippet, a deeper theme file and a stray json below the top level are NOT
    uploaded. A recursive walk counted all of them."""
    obsidian = vault / ".obsidian"
    (obsidian / "plugins" / "dv" / "extra").mkdir(parents=True)
    (obsidian / "snippets" / "nested").mkdir(parents=True)
    (obsidian / "themes" / "t" / "deeper").mkdir(parents=True)
    (obsidian / "plugins" / "dv" / "main.js").write_bytes(b"m" * 11)  # the only one counted
    (obsidian / "plugins" / "dv" / "extra" / "main.js").write_bytes(b"x" * 999)
    (obsidian / "snippets" / "nested" / "deep.css").write_bytes(b"y" * 999)
    (obsidian / "themes" / "t" / "deeper" / "theme.css").write_bytes(b"z" * 999)
    (obsidian / "plugins" / "dv" / "random.json").write_bytes(b"q" * 999)
    xdg = tmp_path / "xdg"
    _write_live_config(
        xdg,
        vault,
        ignoreFolders=["20-projects/_dashboard", "30-areas/hapax/ocr/pages"],
        allowSpecialFiles=list(preflight.VALID_CONFIG_CATEGORIES),
    )
    report = json.loads(_run_env(vault, xdg, "--from-sync-config", "--json").stdout)
    assert report["config_uploads"]["bytes"] == 11
    assert set(report["config_uploads"]["by_category"]) == {"community-plugin-data"}


def test_source_has_no_invalid_escape_sequences() -> None:
    """A docstring documenting backslash handling produced `SyntaxWarning: invalid
    escape sequence`, which becomes a SyntaxError in a future Python. ruff did not flag
    it, so compile with the warning promoted to an error."""
    source = SCRIPT.read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        compile(source, str(SCRIPT), "exec")


def test_script_ships_executable_with_a_working_shebang() -> None:
    """Every other test supplies the interpreter explicitly, which would hide a
    100644 mode and a documented entry point that cannot be invoked.

    The pin is the COMMITTED mode, not the local worktree bit: the committed mode
    is what a fresh checkout gets, and it is the property the docstring's usage
    lines promise. A local bit can drift per-checkout without changing what ships.
    """
    mode = subprocess.run(
        ["git", "ls-files", "-s", "--", "scripts/hapax-obsidian-sync-preflight"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    ).stdout.split()[0]
    assert mode == "100755", f"committed mode is {mode}; direct invocation would fail"

    shebang = SCRIPT.read_text(encoding="utf-8").splitlines()[0]
    assert shebang == "#!/usr/bin/env python3", shebang


def test_symlink_out_of_vault_is_followed_and_reported(
    vault: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """ob follows symlinked directories, so the prediction must too — measured
    2026-09-14, one vault symlink to a source repo put 678 files / 11.8 MiB into
    the remote that no accounting included."""
    outside = tmp_path / "outside-repo"
    outside.mkdir()
    (outside / "external.md").write_bytes(b"e" * 321)
    (vault / "20-projects" / "linked").symlink_to(outside, target_is_directory=True)

    result = _run(str(vault), "--excluded-folders", "20-projects/_dashboard", "--json")
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    paths = {item["path"] for item in report["largest_included_files"]}
    assert "20-projects/linked/external.md" in paths, "symlinked tree was not followed"
    links = report["symlinks_escaping_vault"]
    assert [link["path"] for link in links] == ["20-projects/linked"]
    assert links[0]["target"] == str(outside.resolve())
    # keep.md 100 + keep.md 50 + sibling.md 11 + p1.png 900 (ocr/pages is not
    # excluded here) + the 321-byte file behind the symlink.
    assert report["predicted_upload"]["bytes"] == 1382


def test_internal_symlink_is_not_flagged_as_escaping(vault: pathlib.Path) -> None:
    (vault / "20-projects" / "inside").symlink_to(
        vault / "30-areas" / "hapax", target_is_directory=True
    )
    report = json.loads(
        _run(str(vault), "--excluded-folders", "20-projects/_dashboard", "--json").stdout
    )
    assert report["symlinks_escaping_vault"] == []


def test_symlink_loop_terminates(vault: pathlib.Path) -> None:
    """followlinks=True has no loop guard of its own; a self-referential link must
    not hang the walk."""
    (vault / "20-projects" / "loop").symlink_to(vault, target_is_directory=True)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(vault),
            "--excluded-folders",
            "20-projects/_dashboard",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode in (OK, REFUSED)


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


@pytest.mark.parametrize("selection", ["img", ",", "image,", ",image", " ", "image,,pdf"])
def test_file_type_parsing_matches_the_client(vault: pathlib.Path, selection: str) -> None:
    """cli.js `Kr` splits on ",", trims, lowercases and throws for ANY field not in
    `us` — the empty field that "," or "image," produces included. Dropping empties
    would certify a selection ob refuses to apply. " " is not the reset either: only
    the EXACT empty string is."""
    result = _run(str(vault), "--excluded-folders", "20-projects", "--file-types", selection)
    assert result.returncode == ERROR, result.stdout + result.stderr
    assert "Invalid file type" in result.stderr
    assert "Next:" in result.stderr


def test_exact_empty_file_types_restores_defaults(vault: pathlib.Path) -> None:
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--file-types",
        "",
        "--json",
    )
    assert result.returncode == OK, result.stdout + result.stderr
    assert json.loads(result.stdout)["file_types"] == list(preflight.DEFAULT_FILE_TYPES)


def test_mixed_case_and_padded_file_types_are_accepted(vault: pathlib.Path) -> None:
    """Kr lowercases and trims each field, so these ARE appliable and must not refuse."""
    result = _run(
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
        "--file-types",
        " Image , PDF ",
        "--json",
    )
    assert result.returncode == OK, result.stdout + result.stderr
    assert json.loads(result.stdout)["file_types"] == ["image", "pdf"]


def test_files_over_per_file_max_are_not_counted(vault: pathlib.Path) -> None:
    """cli.js: `!m.folder && m.size > e.perFileMax` -> logSkip("File too large to
    sync"). A file admitted by class but over the limit never uploads, so counting it
    overstates the total — which is how "33 files >= 200 MB were never synced" was
    already true of the real vault."""
    big = vault / "90-attachments"
    big.mkdir(exist_ok=True)
    (big / "huge.pdf").write_bytes(b"p" * 2048)
    base = (
        str(vault),
        "--excluded-folders",
        "20-projects/_dashboard,30-areas/hapax/ocr/pages",
    )
    over = json.loads(_run(*base, "--per-file-max", "2047", "--json").stdout)
    assert over["predicted_upload"]["bytes"] == 161, "an oversize file was counted"
    assert [f["path"] for f in over["files_over_per_file_max"]] == ["90-attachments/huge.pdf"]
    assert over["per_file_max_bytes"] == 2047

    # Boundary: exactly AT the limit still uploads (the client compares with >).
    at = json.loads(_run(*base, "--per-file-max", "2048", "--json").stdout)
    assert at["predicted_upload"]["bytes"] == 161 + 2048
    assert at["files_over_per_file_max"] == []


def test_default_per_file_max_is_the_client_fallback(vault: pathlib.Path) -> None:
    report = json.loads(
        _run(str(vault), "--excluded-folders", "20-projects/_dashboard", "--json").stdout
    )
    assert report["per_file_max_bytes"] == 199 * 1024 * 1024
    assert report["per_file_max_bytes"] == preflight.DEFAULT_PER_FILE_MAX


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
