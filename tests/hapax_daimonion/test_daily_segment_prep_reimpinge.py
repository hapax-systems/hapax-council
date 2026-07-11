"""Re-impinge selection: candidate seed topics are ranked by groundability + impingement salience.

Closes the impingement→recruitment break the dead-end map surfaced: topics were admitted by
LABEL with no recruitability check, and the live impingement stream never reached selection
(it fed only the compose seed). Now ``_candidate_seed_topics`` ranks a pool of seeds by a cheap
MEASURED local recruit-density plus IMPINGEMENT salience — groundable AND live seeds rank first;
abstract/un-recruitable seeds are NOT banned, they rank below (the recruiter's re-angle can still
traverse them). Dynamics, not rules. Self-contained per council test conventions.

The recruit-density probe is batched (``_seed_recruit_densities``): one ``embed_batch`` for the
whole pool, not a per-seed embed — the perception bottleneck under load (py-spy 2026-06-22).
"""

from __future__ import annotations

from agents.hapax_daimonion import daily_segment_prep as prep


def test_candidate_seeds_rank_groundable_first(monkeypatch) -> None:
    fore = [{"topic": "dense topic"}, {"topic": "sparse topic"}, {"topic": "empty topic"}]
    density = {"dense topic": 5, "sparse topic": 1, "empty topic": 0}
    monkeypatch.setattr(
        prep, "_seed_recruit_densities", lambda seeds: {s: density.get(s, 0) for s in seeds}
    )
    monkeypatch.setattr(prep, "_recent_vault_topics", lambda *, limit: [])
    out = prep._candidate_seed_topics(fore, limit=3)
    assert out == ["dense topic", "sparse topic", "empty topic"]  # measured-density order


def test_impingement_salience_lifts_a_resonant_groundable_seed(monkeypatch) -> None:
    fore = [{"topic": "the attribution void"}, {"topic": "quantum chromodynamics"}]
    monkeypatch.setattr(prep, "_seed_recruit_densities", lambda seeds: {s: 1 for s in seeds})
    monkeypatch.setattr(prep, "_recent_vault_topics", lambda *, limit: [])
    imps = [{"content": "thinking about attribution and licensing void today", "strength": 3.0}]
    out = prep._candidate_seed_topics(fore, limit=2, impingements=imps)
    # The seed resonant with the live impingement ranks first among equally-groundable seeds.
    assert out[0] == "the attribution void"


def test_abstract_seed_is_ranked_low_but_never_banned(monkeypatch) -> None:
    fore = [{"topic": "groundable"}, {"topic": "abstract"}]
    monkeypatch.setattr(
        prep,
        "_seed_recruit_densities",
        lambda seeds: {s: (5 if s == "groundable" else 0) for s in seeds},
    )
    monkeypatch.setattr(prep, "_recent_vault_topics", lambda *, limit: [])
    out = prep._candidate_seed_topics(fore, limit=2)
    assert out[0] == "groundable"
    assert set(out) == {"groundable", "abstract"}  # abstract kept, just ranked below


def test_impingement_cannot_promote_an_ungroundable_seed(monkeypatch) -> None:
    # A strongly-impinging but 0-source seed must NOT outrank a groundable one — impingement
    # boosts groundable matter, it does not manufacture grounding.
    fore = [{"topic": "groundable boring"}, {"topic": "impinging but dry"}]
    monkeypatch.setattr(
        prep,
        "_seed_recruit_densities",
        lambda seeds: {s: (2 if s == "groundable boring" else 0) for s in seeds},
    )
    monkeypatch.setattr(prep, "_recent_vault_topics", lambda *, limit: [])
    imps = [{"content": "impinging but dry impinging but dry", "strength": 9.0}]
    out = prep._candidate_seed_topics(fore, limit=2, impingements=imps)
    assert out[0] == "groundable boring"


def test_seed_recruit_densities_fails_soft_to_zero(monkeypatch) -> None:
    # Batch embed failure (Ollama down / embed raises) -> every seed fail-soft to 0 density,
    # never raises (an un-probable seed ranks as if dry).
    def _boom(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr("shared.config.embed_batch", _boom)
    assert prep._seed_recruit_densities(["a", "b"]) == {"a": 0, "b": 0}


def test_seed_recruit_densities_fails_soft_on_misaligned_embed(monkeypatch) -> None:
    # A partial embed failure that RETURNS without raising (fewer vectors than seeds)
    # must fail-soft the whole batch to 0 — never raise a ValueError out of the zip.
    # Regression guard for the strict=True-without-len-guard bug class.

    def _short_embed_batch(texts, model=None, prefix=None):
        # Returns one fewer vector than texts — a misaligned, non-raising failure.
        return [[0.0] * 768 for _ in list(texts)[1:]]

    monkeypatch.setattr("shared.config.embed_batch", _short_embed_batch)
    assert prep._seed_recruit_densities(["a", "b", "c"]) == {"a": 0, "b": 0, "c": 0}


def test_seed_recruit_densities_embeds_pool_once_not_per_seed(monkeypatch) -> None:
    # The batch probe must call embed_batch ONCE for the whole pool, not once per seed
    # (was: N per-seed embeds — the perception bottleneck under load).
    calls = {"n": 0, "texts": None}

    def _fake_embed_batch(texts, model=None, prefix=None):
        calls["n"] += 1
        calls["texts"] = list(texts)
        return [[0.0] * 768 for _ in texts]

    monkeypatch.setattr("shared.config.embed_batch", _fake_embed_batch)
    monkeypatch.setattr(
        "agents.programme_authors.asset_resolver._qdrant_search_by_vector",
        lambda collection, vector, *, limit=3: [],
    )
    prep._seed_recruit_densities(["a", "b", "c", "d"])
    assert calls["n"] == 1  # one embed_batch for all 4 seeds
    assert calls["texts"] == ["a", "b", "c", "d"]


def test_impingement_salience_is_overlap_weighted_by_strength() -> None:
    seed = "the attribution metadata void"
    imps = [
        {"content": "attribution metadata is impinging", "strength": 2.0},
        {"content": "completely unrelated weather report", "strength": 9.0},
    ]
    assert prep._impingement_salience(seed, imps) > 0  # resonant impingement contributes
    assert prep._impingement_salience(seed, None) == 0.0
    assert prep._impingement_salience(seed, []) == 0.0
    assert prep._impingement_salience("", imps) == 0.0
