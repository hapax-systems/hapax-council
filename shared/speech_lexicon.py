"""Pre-TTS pronunciation lexicon — canonical IPA for Hapax identity terms.

Kokoro's G2P (`misaki`) handles common English well but has no entries for
the Greek terms that recur in Hapax's self-referential speech. This module
rewrites those terms with inline phoneme overrides using the `[word](/ipa/)`
syntax that `misaki` parses verbatim, so Kokoro receives the canonical
pronunciation every time.

Entries here are the single source of truth for how Hapax pronounces its
own identity vocabulary. Adding a term: drop it in ``_LEXICON`` with the
IPA string misaki expects (stress marks ˈ ˌ, no slashes). Removing one is
a change of voice identity — do it deliberately.

Integration: ``TTSManager.synthesize`` calls :func:`apply_lexicon` after
:func:`shared.speech_safety.censor`, so the lexicon runs on the same
canonical pre-synthesis text that the safety gate emits.

Pronunciation choices (2026-04-20):

* **Hapax** — /hˈæpæks/ "HAP-aks". Matches misaki's default; pinned here
  so future dictionary drift cannot silently change the voice's own name.
* **Oudepode** — /uˈdɛpoʊdeɪ/ "oo-DEP-oh-day". Operator handle derived
  from Greek οὐδέποτε ("never"). Stress on the second syllable per the
  Greek antepenult rule; final ε realised as /eɪ/ for English register.
* **Legomenon** — /lɛˈɡɑmənɒn/ "leh-GAH-muh-non". American academic
  pronunciation of λεγόμενον; stress on the second syllable.
* **Legomena** — /lɛˈɡɑmənə/ "leh-GAH-muh-nuh". Plural of the above.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Canonical IPA pronunciations for Hapax-identity terms. Keys are lowercase
# match tokens; values are misaki-compatible IPA (no surrounding slashes —
# :func:`apply_lexicon` adds them). Ordered longest-first-by-length so the
# regex alternation prefers longer forms (matters if future entries share
# prefixes, e.g. "hapaxes" vs "hapax").
_LEXICON: dict[str, str] = {
    "hapax": "hˈæpæks",
    "oudepode": "uˈdɛpoʊdeɪ",
    "legomenon": "lɛˈɡɑmənɒn",
    "legomena": "lɛˈɡɑmənə",
}

# Word-boundary, case-insensitive, longest-alternative-first.
_LEX_PATTERN = re.compile(
    r"\b(" + "|".join(sorted((re.escape(k) for k in _LEXICON), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Matches an already-wrapped phoneme override: `[word](/ipa/)`. Used to
# skip regions that are already annotated so repeated calls are idempotent.
_OVERRIDE_SPAN = re.compile(r"\[[^\]]+\]\(/[^/]+/\)")


@dataclass(frozen=True)
class LexiconResult:
    """Outcome of one :func:`apply_lexicon` call."""

    text: str
    was_modified: bool
    hit_count: int


def apply_lexicon(text: str) -> LexiconResult:
    """Rewrite known identity terms with inline phoneme overrides.

    Operates on plain text and returns a string that Kokoro / misaki will
    parse into the canonical phoneme stream for each matched term. Casing
    of the displayed word is preserved inside the brackets (misaki keeps
    the graphemes for diagnostic logs even though the phonemes override
    synthesis). Idempotent: already-wrapped overrides are skipped.
    """
    if not text or not text.strip():
        return LexiconResult(text=text, was_modified=False, hit_count=0)

    # Find regions to preserve (existing overrides) — we won't touch
    # anything inside them.
    preserved = [m.span() for m in _OVERRIDE_SPAN.finditer(text)]

    def _in_preserved(pos: int) -> bool:
        return any(start <= pos < end for start, end in preserved)

    out: list[str] = []
    cursor = 0
    hits = 0
    for match in _LEX_PATTERN.finditer(text):
        if _in_preserved(match.start()):
            continue
        word = match.group(0)
        ipa = _LEXICON[word.lower()]
        out.append(text[cursor : match.start()])
        out.append(f"[{word}](/{ipa}/)")
        cursor = match.end()
        hits += 1
    out.append(text[cursor:])

    if hits == 0:
        return LexiconResult(text=text, was_modified=False, hit_count=0)

    result = "".join(out)
    log.debug("speech_lexicon: applied %d override(s)", hits)
    return LexiconResult(text=result, was_modified=True, hit_count=hits)


__all__ = ["LexiconResult", "apply_lexicon"]
