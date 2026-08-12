"""Tests for ``scripts/hapax-corpus-query``.

The tool's whole justification is a retrieval property -- that a corpus question never comes
back as a single document -- so the tests are mostly about the *shape of the result set*
rather than about ranking niceties. A ranking test that pins an exact float would break on
every stopword edit and teach nobody anything; a test that pins "this cannot return one
result" fails exactly when the tool stops being worth having.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from datetime import UTC, datetime, timedelta
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-corpus-query"


def _load_module() -> ModuleType:
    loader = SourceFileLoader("hapax_corpus_query_under_test", str(SCRIPT))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    module = module_from_spec(spec)
    # @dataclass resolves sys.modules[cls.__module__] while decorating, so the module has to
    # be registered *before* exec, not after.
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture
def mod() -> ModuleType:
    return _load_module()


def _doc(mod: ModuleType, name: str, body: str, **fm: str):  # noqa: ANN202
    """Build an indexed Doc the same way build_index does, without touching disk."""
    from collections import Counter

    tokens = [t for t in mod.TOKEN_RE.findall(body.lower()) if t not in mod.STOPWORDS]
    counts = Counter(tokens)
    return mod.Doc(
        path=f"/corpus/{name}",
        name=name,
        title=fm.get("title", ""),
        status=fm.get("status", ""),
        counts=dict(counts),
        total_tokens=max(len(tokens), 1),
        size=len(body),
    )


def _write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


# --- the advertised command must be runnable ---------------------------------------


def test_the_script_is_executable() -> None:
    """The docstring and PR body both invoke it as `scripts/hapax-corpus-query ...`.

    A tool documented as a command and shipped without the executable bit is a tool the
    reader cannot run, and the failure looks like a broken instruction rather than a mode.
    """
    assert SCRIPT.stat().st_mode & stat.S_IXUSR, "owner execute bit missing"
    assert SCRIPT.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3")


# --- the central commitment: never one result --------------------------------------


def test_a_single_match_is_never_returned_alone(mod: ModuleType) -> None:
    """The headline claim, enforced rather than described.

    One document matching the terms is precisely the island the tool exists to prevent
    being mistaken for the archipelago, so the shortfall is made up from neighbours.
    """
    hit = _doc(mod, "hit.md", "quota receipt admission " * 30)
    sibling = _doc(mod, "sibling.md", "quotient receipt admission ledger " * 30)
    cousin = _doc(mod, "cousin.md", "receipt admission ledger evidence " * 30)
    docs = [hit, sibling, cousin]

    rows = [(mod.score(d, ["quota"]), d) for d in docs]
    rows = sorted((r for r in rows if r[0] > 0), key=lambda p: p[0], reverse=True)
    assert len(rows) == 1, "fixture precondition: exactly one term match"

    matched, neighbours = mod.cluster(rows, docs, limit=12)

    assert len(matched) == 1
    assert len(matched) + len(neighbours) >= mod.MIN_CLUSTER


def test_neighbours_are_distinct_from_matches_and_from_each_other(mod: ModuleType) -> None:
    hit = _doc(mod, "hit.md", "quota receipt admission ledger " * 30)
    others = [
        _doc(mod, f"other{i}.md", "receipt admission ledger evidence " * 30) for i in range(4)
    ]
    docs = [hit, *others]

    matched, neighbours = mod.cluster([(1.0, hit)], docs, limit=12)

    paths = [d.path for _, d in matched] + [d.path for _, d in neighbours]
    assert len(paths) == len(set(paths)), "a document was listed twice"
    assert hit.path not in [d.path for _, d in neighbours]


def test_zero_matches_are_not_padded_into_a_cluster(mod: ModuleType) -> None:
    """Neighbours of nothing are nothing.

    Backfilling an empty result would be the tool inventing an answer -- the failure mode
    is the opposite of the one it guards, and worse, because it looks like a real cluster.
    """
    docs = [_doc(mod, f"d{i}.md", "receipt admission ledger " * 20) for i in range(5)]

    matched, neighbours = mod.cluster([], docs, limit=12)

    assert matched == []
    assert neighbours == []


def test_a_corpus_smaller_than_the_floor_is_reported_not_padded(mod: ModuleType, capsys) -> None:  # noqa: ANN001
    """The floor is a property of the corpus, not a quota to hit by any means."""
    only = _doc(mod, "only.md", "quota receipt " * 20)

    matched, neighbours = mod.cluster([(5.0, only)], [only], limit=12)
    mod.render(matched, header="Corpus cluster for: quota", neighbours=neighbours, corpus_size=1)

    out = capsys.readouterr().out
    assert len(matched) + len(neighbours) == 1
    assert "below the 3-document floor" in out
    assert "corpus gap" in out


def test_backfilled_neighbours_are_labelled_as_not_matching_the_query(
    mod: ModuleType, capsys
) -> None:  # noqa: ANN001
    """A neighbour presented as a term match would be a quiet lie about why it is there."""
    hit = _doc(mod, "hit.md", "quota receipt admission " * 30)
    docs = [hit, *[_doc(mod, f"n{i}.md", "receipt admission ledger " * 30) for i in range(3)]]

    matched, neighbours = mod.cluster([(9.0, hit)], docs, limit=12)
    mod.render(matched, header="Corpus cluster for: quota", neighbours=neighbours)

    out = capsys.readouterr().out
    assert neighbours
    assert "not by your terms" in out
    assert "shared vocabulary" in out


# --- ranking: the short-term substring inflation -----------------------------------


def test_short_terms_do_not_match_word_interiors(mod: ModuleType) -> None:
    """ "api" inside "rapid" and "therapist" is not a mention of an API.

    Before the boundary rule, a three-letter acronym query ranked documents that never
    discuss the acronym above documents that do.
    """
    assert mod._term_matches("api", "api")
    assert mod._term_matches("api", "apis")
    assert not mod._term_matches("api", "rapid")
    assert not mod._term_matches("api", "therapist")


def test_long_terms_still_match_interiors(mod: ModuleType) -> None:
    """The rule must not cost real recall: a full word inside a compound still counts."""
    assert mod._term_matches("receipt", "receipts")
    assert mod._term_matches("quota", "subquota")
    assert mod._term_matches("admission", "readmission")


def test_a_document_that_never_mentions_a_short_term_scores_zero(mod: ModuleType) -> None:
    """The property the boundary rule exists for, at the level the caller sees."""
    decoy = _doc(mod, "decoy.md", "rapid therapist rapidly " * 30)
    real = _doc(mod, "real.md", "api api endpoint " * 30)

    assert mod.score(decoy, ["api"]) == 0.0
    assert mod.score(real, ["api"]) > 0.0


def test_density_beats_raw_count(mod: ModuleType) -> None:
    """A 50 KB survey mentioning a term five times is not more about it than a short note
    that discusses nothing else."""
    survey = _doc(mod, "survey.md", ("unrelated material " * 400) + ("quota " * 5))
    focused = _doc(mod, "focused.md", "quota quota quota governance " * 5)

    assert mod.score(focused, ["quota"]) > mod.score(survey, ["quota"])


# --- supersession must be visible ---------------------------------------------------


def test_retired_status_is_flagged_in_the_output(mod: ModuleType, capsys) -> None:  # noqa: ANN001
    """Quoting a dead position as current is the specific harm; the flag is the mitigation."""
    dead = _doc(mod, "old.md", "quota " * 20, status="superseded")
    live = _doc(mod, "new.md", "quota " * 20)

    mod.render([(9.0, dead), (8.0, live)], header="Corpus cluster for: quota")

    out = capsys.readouterr().out
    assert "** SUPERSEDED **" in out
    assert "do not quote them as current" in out


@pytest.mark.parametrize("status", ["retired", "superseded", "withdrawn", "obsolete"])
def test_every_retired_vocabulary_word_counts_as_dead(mod: ModuleType, status: str) -> None:
    assert _doc(mod, "x.md", "body", status=status).is_dead


# --- index lifecycle ----------------------------------------------------------------


def test_index_roundtrips_and_reports_when_it_was_built(mod: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    stamp = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
    docs = [_doc(mod, "a.md", "quota receipt " * 10)]

    mod.save(docs, path=path, now=stamp)
    loaded, indexed_at, _roots = mod.load(path=path)

    assert [d.name for d in loaded] == ["a.md"]
    assert indexed_at == stamp


def test_a_stale_index_says_so(mod: ModuleType) -> None:
    """Silence is the failure mode: a stale index answers confidently about a past corpus."""
    now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)

    fresh = mod.staleness_warning(now - timedelta(hours=1), now=now)
    stale = mod.staleness_warning(now - timedelta(hours=9), now=now)

    assert fresh is None
    assert stale is not None
    assert "--reindex" in stale


def test_an_index_from_an_older_schema_is_discarded_not_half_read(
    mod: ModuleType, tmp_path: Path
) -> None:
    """A shape mismatch that loads is worse than one that fails."""
    path = tmp_path / "index.json"
    path.write_text('[{"path": "/x", "name": "x.md"}]', encoding="utf-8")

    docs, indexed_at, _roots = mod.load(path=path)

    assert docs == []
    assert indexed_at is None


def test_a_corrupt_index_is_discarded(mod: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    path.write_text("{not json", encoding="utf-8")

    assert mod.load(path=path) == ([], None, [])


# --- roots are configurable ---------------------------------------------------------


def test_roots_come_from_the_flag_then_the_environment_then_the_default(
    mod: ModuleType, monkeypatch, tmp_path: Path
) -> None:  # noqa: ANN001
    """The vault path is this estate's convention, not a property of the instrument.

    Hardcoding it makes the tool untestable against a fixture corpus and unusable by anyone
    whose notes live elsewhere -- including CI.
    """
    monkeypatch.setenv("HAPAX_CORPUS_ROOTS", f"{tmp_path}/env-a{os.pathsep}{tmp_path}/env-b")

    assert mod.resolve_roots([str(tmp_path / "flag")]) == [tmp_path / "flag"]
    assert mod.resolve_roots(None) == [tmp_path / "env-a", tmp_path / "env-b"]

    monkeypatch.delenv("HAPAX_CORPUS_ROOTS")
    assert mod.resolve_roots(None) == mod.DEFAULT_ROOTS


def test_build_index_reads_a_real_directory_of_markdown(mod: ModuleType, tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "---\ntitle: Alpha\nstatus: retired\n---\n\n# Alpha\n\nquota quota\n")
    _write(tmp_path, "b.md", "# Beta\n\nreceipt receipt\n")
    (tmp_path / "lanebus").mkdir()
    _write(tmp_path / "lanebus", "noise.md", "quota quota quota\n")

    docs = mod.build_index([tmp_path])

    by_name = {d.name: d for d in docs}
    assert set(by_name) == {"a.md", "b.md"}, "lanebus/ must be skipped"
    assert by_name["a.md"].title == "Alpha"
    assert by_name["a.md"].is_dead
    assert by_name["b.md"].title == "Beta"


def test_mtime_is_a_utc_calendar_date(mod: ModuleType, tmp_path: Path) -> None:
    """A naive local timestamp renders differently depending on the reader's clock."""
    _write(tmp_path, "a.md", "# A\n\nquota\n")

    doc = mod.build_index([tmp_path])[0]

    assert datetime.strptime(doc.mtime, "%Y-%m-%d").replace(tzinfo=UTC)


# --- errors name a next action ------------------------------------------------------


def test_related_miss_offers_near_names_when_it_can(mod: ModuleType) -> None:
    docs = [
        _doc(mod, "merge-plane-is-the-mincut-2026-08-11.md", "body"),
        _doc(mod, "unrelated.md", "body"),
    ]

    message = mod._related_miss_message("merge-plane-mincut.md", docs)

    assert "merge-plane-is-the-mincut-2026-08-11.md" in message


def test_related_miss_on_an_empty_index_says_to_reindex(mod: ModuleType) -> None:
    message = mod._related_miss_message("anything.md", [])

    assert "--reindex" in message
    assert "index is empty" in message


def test_related_miss_with_no_near_name_distinguishes_the_two_causes(mod: ModuleType) -> None:
    """Typo, stale index, and outside-the-roots need different fixes; name both remaining."""
    docs = [_doc(mod, "zzz.md", "body")]

    message = mod._related_miss_message("qqqqqqqq.md", docs)

    assert "--root" in message
    assert "--reindex" in message


def test_related_lookup_failure_exits_nonzero(mod: ModuleType, tmp_path: Path, capsys) -> None:  # noqa: ANN001
    _write(tmp_path, "a.md", "# A\n\nquota\n")

    rc = mod.main(
        [
            "--related",
            "definitely-not-here.md",
            "--root",
            str(tmp_path),
            "--index",
            str(tmp_path / "index.json"),
        ]
    )

    assert rc == 2
    assert "definitely-not-here.md" in capsys.readouterr().err


# --- end-to-end through main(), against a fixture corpus ----------------------------


def test_main_answers_from_the_named_roots_and_never_touches_the_default_index(
    mod: ModuleType, tmp_path: Path, capsys
) -> None:  # noqa: ANN001
    """Hermetic by construction.

    Before --index, main() always loaded the operator's real cache, so a --root flag was
    silently ignored whenever that cache existed -- the test would pass while exercising a
    corpus it never created, and the flag was decorative.
    """
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _write(corpus, "alpha.md", "# Alpha\n\n" + "quota receipt admission " * 30)
    _write(corpus, "beta.md", "# Beta\n\n" + "receipt admission ledger " * 30)
    _write(corpus, "gamma.md", "# Gamma\n\n" + "admission ledger evidence " * 30)
    index = tmp_path / "index.json"

    rc = mod.main(["quota", "--root", str(corpus), "--index", str(index)])

    out = capsys.readouterr().out
    assert rc == 0
    assert index.is_file(), "the named index must be written, not the default"
    assert index != mod.CACHE_PATH
    assert "alpha.md" in out
    # the floor: one term match, cluster of at least MIN_CLUSTER
    assert out.count(". [") >= mod.MIN_CLUSTER


def test_main_reindexes_when_root_is_given_even_if_an_index_exists(
    mod: ModuleType, tmp_path: Path, capsys
) -> None:  # noqa: ANN001
    """An index built from another corpus cannot answer for the one --root names."""
    stale_corpus = tmp_path / "stale"
    stale_corpus.mkdir()
    _write(stale_corpus, "old.md", "# Old\n\n" + "quota " * 40)
    index = tmp_path / "index.json"
    mod.save(mod.build_index([stale_corpus]), path=index)

    fresh_corpus = tmp_path / "fresh"
    fresh_corpus.mkdir()
    _write(fresh_corpus, "new.md", "# New\n\n" + "quota " * 40)

    rc = mod.main(["quota", "--root", str(fresh_corpus), "--index", str(index)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "new.md" in out
    assert "old.md" not in out


# --- the operator's own words must be reachable -------------------------------------


def test_operator_json_records_are_indexed(mod: ModuleType, tmp_path: Path) -> None:
    """The tool existed to stop research landing on one island, and excluded the island
    holding the operator's verbatim stipulations.

    Two separate barriers, and only fixing both reaches them: `operator-corpus` was in
    SKIP_DIR_PARTS, AND the records are JSON while build_index globbed `*.md`. Measured
    2026-08-12: narrowing the skip list alone surfaces 7 markdown files, two of which are
    AGENTS.md and CLAUDE.md. The file extension was the real barrier.
    """
    records = tmp_path / "operator-corpus" / "records"
    records.mkdir(parents=True)
    (records / "pli-deadbeefdeadbeef.json").write_text(
        json.dumps(
            {
                "record_id": "pli-deadbeefdeadbeef",
                "captured_at": "2026-08-09T12:00:00Z",
                "status": "CAPTURED_INERT_SUPPORT_ONLY",
                "content": "my inflections should be systematically mapped to the system elements",
            }
        ),
        encoding="utf-8",
    )

    docs = mod.build_index([tmp_path])

    assert len(docs) == 1
    assert docs[0].doc_type == "operator-record"
    assert "inflections" in docs[0].counts
    assert mod.score(docs[0], ["inflections"]) > 0


def test_a_record_without_prose_is_skipped_not_indexed_empty(
    mod: ModuleType, tmp_path: Path
) -> None:
    """A metadata-only capture has nothing to search; indexing it as an empty document
    would pad result counts and dilute the density ranking."""
    records = tmp_path / "operator-corpus" / "records"
    records.mkdir(parents=True)
    (records / "pli-nocontent.json").write_text(
        json.dumps({"record_id": "pli-nocontent", "status": "EMPTY"}), encoding="utf-8"
    )

    assert mod.build_index([tmp_path]) == []


def test_bulk_raw_dirs_stay_excluded(mod: ModuleType) -> None:
    """prompt-histories is 12 MB of raw transcript and paste-cache 608 KB. Indexing them
    would swamp density ranking with incidental matches -- the exact failure the skip list
    exists to prevent. Only the curated records were let in."""
    assert "prompt-histories" in mod.SKIP_DIR_PARTS
    assert "paste-cache" in mod.SKIP_DIR_PARTS
    assert "operator-corpus" not in mod.SKIP_DIR_PARTS


# --- the shortfall branches the reviewers found undocumented-by-test -----------------


def test_a_match_with_no_vocabulary_neighbours_is_announced_not_padded(
    mod: ModuleType, capsys
) -> None:  # noqa: ANN001
    """The exception that made "never return one result" false, now exercised.

    related() requires shared tokens longer than four characters. A document that overlaps
    nothing has no neighbours to borrow even in a large corpus, so the floor cannot be met.
    Padding with unrelated documents would defeat the purpose — the floor exists so a reader
    sees the archipelago, and three irrelevant documents are not one.
    """
    lonely = _doc(mod, "lonely.md", "zzzq wwwx vvvy " * 20)
    others = [_doc(mod, f"o{i}.md", "receipt admission ledger evidence " * 20) for i in range(6)]
    docs = [lonely, *others]

    matched, neighbours = mod.cluster([(9.0, lonely)], docs, limit=12)
    mod.render(
        matched, header="Corpus cluster for: zzzq", neighbours=neighbours, corpus_size=len(docs)
    )

    out = capsys.readouterr().out
    assert len(matched) + len(neighbours) == 1, "no neighbour is borrowable"
    assert "below the 3-document floor" in out
    assert "shares enough distinctive vocabulary" in out, "the cause must be named"
    assert "corpus holds 7" in out


def test_the_related_source_is_never_its_own_neighbour(mod: ModuleType) -> None:
    """In --related, the source document is not in `matched` — the matches ARE its
    neighbours — so without an explicit exclusion it can backfill as a neighbour of its own
    neighbour. That consumes a floor slot a distinct document should have had."""
    source = _doc(mod, "source.md", "quota receipt admission ledger " * 30)
    near = _doc(mod, "near.md", "quota receipt admission ledger " * 30)
    docs = [source, near]

    matched, neighbours = mod.cluster([(0.9, near)], docs, limit=12, exclude={source.path})

    assert source.path not in [d.path for _, d in neighbours]


def test_json_records_under_a_skipped_directory_are_not_indexed(
    mod: ModuleType, tmp_path: Path
) -> None:
    """The skip list exists so raw dumps do not swamp density ranking. JSON indexing was
    added without consulting it, so a records/ dir under prompt-histories would have been
    ingested — the exclusion has to apply to both readers or it applies to neither."""
    buried = tmp_path / "operator-corpus" / "prompt-histories" / "records"
    buried.mkdir(parents=True)
    (buried / "pli-buried.json").write_text(
        json.dumps({"record_id": "pli-buried", "content": "quota receipt admission"}),
        encoding="utf-8",
    )

    assert mod.build_index([tmp_path]) == []
