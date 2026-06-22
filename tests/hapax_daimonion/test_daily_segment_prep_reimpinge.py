"""Re-impinge selection: candidate seed topics are ranked by groundability + impingement salience.

Closes the impingement→recruitment break the dead-end map surfaced: topics were admitted by
LABEL with no recruitability check, and the live impingement stream never reached selection
(it fed only the compose seed). Now ``_candidate_seed_topics`` ranks a pool of seeds by a cheap
MEASURED local recruit-density plus IMPINGEMENT salience — groundable AND live seeds rank first;
abstract/un-recruitable seeds are NOT banned, they rank below (the recruiter's re-angle can still
traverse them). Dynamics, not rules. Self-contained per council test conventions.
"""

from __future__ import annotations

from agents.hapax_daimonion import daily_segment_prep as prep


def test_candidate_seeds_rank_groundable_first(monkeypatch) -> None:
    fore = [{"topic": "dense topic"}, {"topic": "sparse topic"}, {"topic": "empty topic"}]
    density = {"dense topic": 5, "sparse topic": 1, "empty topic": 0}
    monkeypatch.setattr(prep, "_seed_recruit_density", lambda s: density.get(s, 0))
    monkeypatch.setattr(prep, "_recent_vault_topics", lambda *, limit: [])
    out = prep._candidate_seed_topics(fore, limit=3)
    assert out == ["dense topic", "sparse topic", "empty topic"]  # measured-density order


def test_impingement_salience_lifts_a_resonant_groundable_seed(monkeypatch) -> None:
    fore = [{"topic": "the attribution void"}, {"topic": "quantum chromodynamics"}]
    monkeypatch.setattr(prep, "_seed_recruit_density", lambda s: 1)  # equal density
    monkeypatch.setattr(prep, "_recent_vault_topics", lambda *, limit: [])
    imps = [{"content": "thinking about attribution and licensing void today", "strength": 3.0}]
    out = prep._candidate_seed_topics(fore, limit=2, impingements=imps)
    # The seed resonant with the live impingement ranks first among equally-groundable seeds.
    assert out[0] == "the attribution void"


def test_abstract_seed_is_ranked_low_but_never_banned(monkeypatch) -> None:
    fore = [{"topic": "groundable"}, {"topic": "abstract"}]
    monkeypatch.setattr(prep, "_seed_recruit_density", lambda s: 5 if s == "groundable" else 0)
    monkeypatch.setattr(prep, "_recent_vault_topics", lambda *, limit: [])
    out = prep._candidate_seed_topics(fore, limit=2)
    assert out[0] == "groundable"
    assert set(out) == {"groundable", "abstract"}  # abstract kept, just ranked below


def test_impingement_cannot_promote_an_ungroundable_seed(monkeypatch) -> None:
    # A strongly-impinging but 0-source seed must NOT outrank a groundable one — impingement
    # boosts groundable matter, it does not manufacture grounding.
    fore = [{"topic": "groundable boring"}, {"topic": "impinging but dry"}]
    monkeypatch.setattr(
        prep, "_seed_recruit_density", lambda s: 2 if s == "groundable boring" else 0
    )
    monkeypatch.setattr(prep, "_recent_vault_topics", lambda *, limit: [])
    imps = [{"content": "impinging but dry impinging but dry", "strength": 9.0}]
    out = prep._candidate_seed_topics(fore, limit=2, impingements=imps)
    assert out[0] == "groundable boring"


def test_seed_recruit_density_fails_soft_to_zero(monkeypatch) -> None:
    import agents.programme_authors.asset_resolver as ar

    def _boom(*a, **k):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(ar, "_qdrant_search", _boom)
    assert prep._seed_recruit_density("anything") == 0


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
