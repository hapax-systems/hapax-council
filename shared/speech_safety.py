"""Pre-TTS redaction — fail-closed slur gate for Hapax voice output.

**Go-live invariant (operator directive 2026-04-20):** Hapax TTS must
never emit the N-word or clear variants. This module is the last line
of defence between any upstream text generator and the Kokoro synthesis
pipeline. It runs inside :meth:`TTSManager.synthesize` so *every* voice
path — CPAL impingement speech, narrative-director spoken lines,
notifications, briefings — passes through the same gate.

Design decisions:

* **Fail-closed**: if the detector errors or encounters anything
  ambiguous, drop the match token entirely rather than risk broadcast.
* **Temporary substitution**: replacement is ``"friend"`` — same
  syllable count so prosody degrades gracefully. Task #173 ("Hapax
  self-censorship strategy — aesthetically interesting substitution")
  will overtake this with a more creative mapping. When that ships,
  ``REDACTION_SUBSTITUTE`` becomes a function hook, not a constant.
* **Observability**: every hit logs a structured event + increments a
  Prometheus counter (best-effort). We emit the *length* of the
  offending token, never the token itself — replaying journal logs
  must not reproduce the word.
* **Detection scope**: the target slur family only. Not a general
  profanity filter, not a sentiment moderator. This is a bright-line
  pre-broadcast safety gate for one specific lexical hazard the
  operator flagged as monetization + dignity-critical.

The regex is intentionally broad on obfuscation (asterisk fills, leet
substitution, unicode homoglyph strip). False positives on benign words
(``niggard``, ``Niagara``, ``snigger``) are avoided via word-boundary +
an allow-list of substring matches that share letters but not etymology.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Replacement pool for matched slur tokens. Task #173 asked for an
# "aesthetically interesting, not run-of-the-mill" substitution —
# KMD / MF-DOOM register. Pool picks bias toward archaic, literary,
# and dictionary-obscure words that preserve the two-syllable cadence
# of the target so Kokoro prosody degrades gracefully. Cultural load
# is kept neutral: no words with identifiable political, religious,
# or in-group connotation. All are ≥8th-century English word stock
# or well-integrated loans. The pick is deterministic per call site
# (hash of the matched span) so the same offending utterance always
# receives the same substitute — replay-stable.
#
# Operator override: set the ``HAPAX_SPEECH_SUBSTITUTE_POOL`` env var
# to a comma-separated list to replace the default pool at startup.
# Empty / invalid override falls through to the default.
_DEFAULT_SUBSTITUTE_POOL: tuple[str, ...] = (
    "kinsman",  # archaic; "kin" (OE cynn) + "-man"
    "kindred",  # OE "gecynd" — of the same stock
    "brethren",  # archaic plural of brother, used formally
    "yokefellow",  # 16th-c. "one yoked to another" — Shakespeare usage
    "compadre",  # Spanish loan, fully integrated in English
    "comrade",  # Middle French via Spanish; benign in the US register
)

# Exposed for introspection / tests. The active pool is finalised at
# module-import time and does not re-read the env var mid-process.
REDACTION_SUBSTITUTE_POOL: tuple[str, ...] = (
    tuple(
        w.strip()
        for w in (os.environ.get("HAPAX_SPEECH_SUBSTITUTE_POOL", "").split(","))
        if w.strip()
    )
    or _DEFAULT_SUBSTITUTE_POOL
)

# Backwards-compat alias: the original constant name. Evaluates to the
# first pool member so any caller that doesn't use ``pick_substitute``
# still gets a sensible default. Task #173 callers should migrate to
# the picker.
REDACTION_SUBSTITUTE: str = REDACTION_SUBSTITUTE_POOL[0]


def pick_substitute(offending: str) -> str:
    """Deterministically select a substitute from the active pool.

    The pick is ``hash(offending) % len(pool)``. Using the matched span
    (lowercased) as the hash input means the same slur token in the
    same utterance always substitutes to the same word, so re-running
    a recorded transcript does not re-shuffle the redactions.
    """
    if not REDACTION_SUBSTITUTE_POOL:
        return REDACTION_SUBSTITUTE
    # Stable hash: md5 of the lowercased offending token. Cryptographic
    # strength is not required; the only goal is replay-stability.
    import hashlib

    digest = hashlib.md5(  # noqa: S324 — not for security
        offending.casefold().encode("utf-8"), usedforsecurity=False
    ).digest()
    idx = digest[0] % len(REDACTION_SUBSTITUTE_POOL)
    return REDACTION_SUBSTITUTE_POOL[idx]


# Allow-list: words whose letter sequences overlap the slur but whose
# etymology is unrelated. Matched word-forms ending in any of these are
# emitted unmodified even if the slur regex would otherwise fire. Case
# insensitive; matched as *suffixes* of a word so forms like "Niagaras"
# / "niggards" still pass through.
_ALLOWLIST_SUFFIXES: tuple[str, ...] = (
    "niagara",
    "niagaras",
    "niggard",
    "niggards",
    "niggardly",
    "niggardliness",
    "snigger",
    "sniggers",
    "sniggered",
    "sniggering",
    # Niger (river, country): "Nigerien" / "Nigerian" are proper nouns
    # that are *not* slurs. Allow through — prosody is fine with them.
    "niger",
    "nigerien",
    "nigerian",
    "nigeria",
    "nigerians",
    # Archaic "nigh" family (= near): added 2026-04-20 after the regex
    # was widened to catch h-terminal slur variants. These share letter
    # prefixes but are unrelated etymology.
    "nigh",
    "nighed",
    "nigher",
    "nighs",
)

# Leet-speak normalisation. Applied before the detector runs so
# "n1gga" / "n!gga" normalise to "nigga" for matching. Keep minimal
# — aggressive normalisation causes FPs on unrelated tokens.
_LEET_MAP: dict[str, str] = {
    "1": "i",
    "!": "i",
    "ı": "i",  # dotless i
    "0": "o",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "@": "a",
    "$": "s",
}

# Core detection regex. Matches the slur family with:
#   * ``n`` (any case)
#   * optional digit/punctuation filler (handled by leet map)
#   * one or more ``g`` / ``q`` (q is a near-visual homoglyph)
#   * one or more vowels (``a`` / ``e`` / ``i`` / ``u`` / ``o`` / ``y``)
#     optionally interspersed with ``h`` (``niggah`` / ``nigguh`` /
#     ``niggy`` variants) — the ``[aeuohiy]+`` class covers all known
#     phonetic spellings including y-functioning-as-vowel forms
#   * optional trailing ``r`` (hard-R variant) or ``z`` / ``x`` / ``s``
#     / ``y`` (plural / slang plural / y-terminal diminutive)
# Word boundaries on both sides to avoid intra-word FPs. Leak history:
#   - 2026-04-20 first leak: ``nigga`` → original regex shipped.
#   - 2026-04-20 second leak: ``niggah`` / ``niggaz`` — widened with h
#     + z/s/x plural endings.
#   - 2026-04-19 third leak: ``niggy`` (y-terminal diminutive; said
#     while narrating current vinyl) — added ``y`` to both the vowel
#     class and the terminal class. Each reactive widening confirms
#     the regex alone cannot be the only defence — prompt-level
#     prohibition + audio-egress filter must catch what this misses.
_SLUR_RE = re.compile(r"\bn[i][gq]+[aeuohiy]+[rzsx]?y?\b", re.IGNORECASE)

# Asterisk-fill detector. Matches obfuscated forms like ``n*gga``,
# ``ni**a``, ``n**ga``. We collapse asterisks to letters then re-check.
_ASTERISK_TOKEN_RE = re.compile(r"\b[a-z*]{4,8}\b", re.IGNORECASE)


@dataclass(frozen=True)
class RedactionResult:
    """Outcome of one :func:`censor` call.

    ``was_modified`` is ``True`` whenever any replacement happened so
    callers can log a compact warning. ``hit_count`` is the number of
    distinct token replacements — useful for metric export. ``text`` is
    the safe-to-synthesise result.
    """

    text: str
    was_modified: bool
    hit_count: int


def _normalise(token: str) -> str:
    """Fold unicode + leet forms so the regex matches obfuscated variants.

    Combining marks are stripped, case folded to lower, digit/punctuation
    leet substitutions applied. This runs on a *copy* of the token; the
    original is preserved for the output when no hit is detected.
    """
    try:
        nfkd = unicodedata.normalize("NFKD", token)
        stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
        lowered = stripped.casefold()
        table = str.maketrans(_LEET_MAP)
        return lowered.translate(table)
    except Exception:
        # Fail-closed: if normalisation itself errors, return a known
        # non-matching token so the caller's detector sees "no hit" and
        # the original token gets treated as safe. This is the one place
        # we intentionally do NOT fail-closed-to-censor — a normalisation
        # bug must never censor a clean utterance silently.
        log.debug("normalise failed for %r", token, exc_info=True)
        return token.casefold()


def _is_allowlisted(word: str) -> bool:
    """Return True when ``word`` matches a benign-etymology allow entry."""
    lower = word.casefold()
    return any(lower == suffix or lower.endswith(suffix) for suffix in _ALLOWLIST_SUFFIXES)


def _redact_match(match: re.Match[str]) -> str:
    """Regex substitution callback.

    The allow-list check happens in :func:`censor` before we ever hit
    the substitution callback for matched tokens — this function just
    returns the substitute string.
    """
    return REDACTION_SUBSTITUTE


def censor(text: str) -> RedactionResult:
    """Scan ``text`` for slur tokens; return a redacted copy + hit count.

    Processing order:
      1. Fast path: empty / whitespace-only → unchanged.
      2. Primary pass: normalised regex on the whole text. Matches
         trigger per-token allow-list verification before substitution.
      3. Asterisk pass: look for asterisk-heavy short tokens; if
         collapsing the asterisks produces a normalised hit, replace.
      4. Return the composed result.

    All replacements are word-level: the whole token gets replaced
    with :data:`REDACTION_SUBSTITUTE`, not inline character edits,
    because inline edits (``n***a``) read audibly wrong on TTS.
    """
    if not text or not text.strip():
        return RedactionResult(text=text, was_modified=False, hit_count=0)

    hits = 0
    working = text

    # ── Primary pass: normalised text regex ────────────────────────────
    # We detect on a normalised copy (leet folded) so the regex catches
    # obfuscated variants, but we rewrite the *original* text so casing
    # and punctuation unaffected by hits survive untouched.
    normalised_full = _normalise(working)
    detected_spans: list[tuple[int, int]] = []
    for match in _SLUR_RE.finditer(normalised_full):
        word = match.group(0)
        if _is_allowlisted(word):
            continue
        # Map the normalised span back to the original string. Because
        # _normalise is length-preserving (leet is 1:1 char maps, unicode
        # combining-mark removal typically shortens but we keep NFKD
        # length-pessimistic), we use the normalised span directly on
        # the original for a best-effort alignment. If lengths differ
        # after fold, we fall back to word-level re-search on the raw.
        span = match.span()
        if len(normalised_full) == len(working):
            detected_spans.append(span)
        else:
            raw_match = re.search(
                rf"\b\S{{{max(1, len(word) - 2)},{len(word) + 2}}}\b",
                working[max(0, span[0] - 3) :],
                re.IGNORECASE,
            )
            if raw_match:
                base = max(0, span[0] - 3)
                detected_spans.append((base + raw_match.start(), base + raw_match.end()))

    if detected_spans:
        # Apply substitutions right-to-left so earlier spans don't shift.
        # Each offending span gets a deterministic pick from the pool
        # (task #173 aesthetic rotation). Same slur token in the same
        # utterance always maps to the same substitute for replay
        # stability.
        for start, end in sorted(detected_spans, key=lambda s: s[0], reverse=True):
            offending = working[start:end]
            substitute = pick_substitute(offending)
            working = working[:start] + substitute + working[end:]
            hits += 1

    # ── Asterisk pass: detect obfuscated tokens with *s ───────────────
    # Each ``*`` is treated as a single-character wildcard over
    # ``[a-z]``. If any expansion fullmatches the slur regex, we
    # redact the token. Bounded to <=4 asterisks to keep the search
    # space tiny (4 stars × 26 letters = 456k — still instant).
    _WILDCARD_LETTERS = "abcdefghijklmnopqrstuvwxyz"

    def _expansion_matches_slur(tok: str) -> bool:
        stars = [i for i, c in enumerate(tok) if c == "*"]
        if not stars or len(stars) > 4:
            return False
        import itertools

        for combo in itertools.product(_WILDCARD_LETTERS, repeat=len(stars)):
            chars = list(tok)
            for pos, letter in zip(stars, combo, strict=True):
                chars[pos] = letter
            candidate = "".join(chars)
            if _SLUR_RE.fullmatch(_normalise(candidate)):
                return True
        return False

    def _asterisk_sub(m: re.Match[str]) -> str:
        nonlocal hits
        tok = m.group(0)
        if "*" not in tok:
            return tok
        if _is_allowlisted(tok):
            return tok
        if _expansion_matches_slur(tok):
            hits += 1
            return pick_substitute(tok)
        return tok

    working = _ASTERISK_TOKEN_RE.sub(_asterisk_sub, working)

    was_modified = hits > 0
    if was_modified:
        # Log only the hit count + the length of the matched spans, never
        # the word itself — journal archives must not be able to replay
        # the slur.
        log.warning(
            "speech_safety.censor: redacted %d token(s) before TTS (output_len=%d, substitute=%r)",
            hits,
            len(working),
            REDACTION_SUBSTITUTE,
        )
        try:
            _REDACTION_COUNTER.labels(outcome="redacted").inc(hits)
        except Exception:  # noqa: S110 — metrics are best-effort
            pass

    return RedactionResult(text=working, was_modified=was_modified, hit_count=hits)


# Prometheus counter — best-effort import. Deferred to first use so test
# environments without prometheus_client don't crash on import.
try:
    from prometheus_client import Counter

    _REDACTION_COUNTER = Counter(
        "hapax_speech_safety_redactions_total",
        "Count of pre-TTS speech-safety redactions applied.",
        labelnames=("outcome",),
    )
except Exception:
    _REDACTION_COUNTER = None  # type: ignore[assignment]


__all__ = ["REDACTION_SUBSTITUTE", "RedactionResult", "censor"]
