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


def test_dotted_component_entry_is_refused_as_unreachable(vault: pathlib.Path) -> None:
    """Hidden pruning happens before the exclusion test, so a dotted entry is
    unreachable — reporting it 'ok' would credit an exclusion that never runs."""
    result = _run(str(vault), "--excluded-folders", "30-areas/.venv", "--json")
    assert result.returncode == REFUSED
    assert "hidden" in json.loads(result.stdout)["findings"][0]["detail"]


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


def test_per_file_stat_failure_refuses(vault: pathlib.Path) -> None:
    """A dangling symlink makes os.stat fail for ONE file (the directory case is
    covered separately). A partial total must still not exit 0."""
    (vault / "30-areas" / "dangling.md").symlink_to(vault / "30-areas" / "gone.md")
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


def test_internal_link_uploads_under_both_paths(vault: pathlib.Path) -> None:
    """ob emits one relative path per route to a directory, so a vault-internal
    link means the same file uploads twice under different paths. A global inode
    dedup dropped whichever route came second, making totals order-dependent."""
    target = vault / "30-areas" / "target"
    (target / "private").mkdir(parents=True)
    (target / "private" / "secret.md").write_bytes(b"s" * 77)
    (vault / "alias").symlink_to(target, target_is_directory=True)

    # Excluding only the alias route must leave the real route admitted.
    result = _run(str(vault), "--excluded-folders", "alias/private", "--json")
    assert result.returncode == OK, result.stdout + result.stderr
    report = json.loads(result.stdout)
    paths = {item["path"] for item in report["largest_included_files"]}
    assert "30-areas/target/private/secret.md" in paths
    assert "alias/private/secret.md" not in paths

    # With neither route excluded the file is counted under BOTH, as ob uploads it.
    both = json.loads(_run(str(vault), "--excluded-folders", "30-areas/hapax", "--json").stdout)
    counted = {item["path"] for item in both["largest_included_files"]}
    assert "alias/private/secret.md" in counted
    assert "30-areas/target/private/secret.md" in counted

    # Excluding BOTH routes removes exactly one 77-byte file per route, and the
    # result must not depend on which route the walk reached first.
    neither = json.loads(
        _run(
            str(vault),
            "--excluded-folders",
            "30-areas/hapax,alias/private,30-areas/target/private",
            "--json",
        ).stdout
    )
    assert both["predicted_upload"]["bytes"] - neither["predicted_upload"]["bytes"] == 154
    assert both["predicted_upload"]["files"] - neither["predicted_upload"]["files"] == 2


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
