#!/usr/bin/env python3
"""Gap validation protocol — automated prior-art sweep + decision matrix.

Phase 1: automated sweep across patents, GitHub/Papers with Code,
Semantic Scholar, and ACM/IEEE trade-publication archives.
Phase 2: community probe scaffolding (forum post + cold-email templates).
Phase 3: practitioner observation guide (generated markdown).

Decision matrix: 6 signals (patents, code_search, academic_papers, trade_pubs,
forums, practitioner_observation). 4+ agreeing = high confidence the gap is novel.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import unescape
from pathlib import Path
from textwrap import dedent
from urllib.parse import urljoin

import httpx
import yaml

logger = logging.getLogger("gap-validate")

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs" / "research" / "gap-portfolio-registry.yaml"
VAULT_OUTPUT_DIR = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-gap-validation"
OBSERVATION_GUIDE_PATH = REPO_ROOT / "docs" / "research" / "gap-validation-observation-guide.md"

SWEEP_TIMEOUT = 30
HTTP_TIMEOUT = 20
GOOGLE_PATENTS_URL = "https://patents.google.com/"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
IEEE_XPLORE_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
ACM_DL_SEARCH_URL = "https://dl.acm.org/action/doSearch"
IEEE_XPLORE_API_KEY_ENV = "IEEE_XPLORE_API_KEY"
IEEE_XPLORE_PASS_PATH = "ieee/xplore-api-key"
PATENT_LINK_RE = re.compile(r'href="(?P<href>/patent/[^"#?]+)')
ACM_DOI_LINK_RE = re.compile(r'href="(?P<href>/doi/[^"#?]+)"[^>]*>(?P<title>.*?)</a>', re.S)


@dataclass
class SignalResult:
    signal: str
    vote: str  # "novel", "prior_art_exists", "inconclusive"
    confidence: float  # 0-1
    evidence: list[dict] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class SweepResult:
    gap_id: str
    title: str
    sweep_timestamp: str
    signals: list[SignalResult] = field(default_factory=list)
    decision: str = ""
    novel_votes: int = 0
    total_signals: int = 0


def load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def find_gap(registry: dict, gap_id: str) -> dict | None:
    for gap in registry.get("gaps", []):
        if gap["gap_id"] == gap_id:
            return gap
    return None


def build_search_terms(gap: dict) -> list[str]:
    title = gap["title"]
    justification = gap.get("apparatus_justification", "")
    terms = [title]
    keywords = title.lower().split()
    if len(keywords) > 3:
        terms.append(" ".join(keywords[:4]))
    domain_terms = {
        "stigmergic": "stigmergy agent coordination",
        "grounding": "multimodal grounding",
        "epistemic": "epistemic quality calibration",
        "discursive": "discursive assertion plane",
        "governance": "AI governance constitution",
        "bayesian": "bayesian claim tracking",
        "compositor": "GPU compositor pipeline",
        "axiom": "axiomatic governance enforcement",
    }
    for keyword, expanded in domain_terms.items():
        if keyword in title.lower() or keyword in justification.lower():
            terms.append(expanded)
    return terms


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(text))).strip()


def _unique_by_url(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for item in items:
        url = str(item.get("url") or item.get("doi") or item.get("source_url") or "")
        key = url or json.dumps(item, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _source_urls(items: list[dict]) -> list[str]:
    urls: list[str] = []
    for item in items:
        for field_name in ("url", "doi", "source_url"):
            value = item.get(field_name)
            if value:
                urls.append(str(value))
                break
    return urls


def _resolve_ieee_xplore_api_key() -> tuple[str | None, str | None]:
    """Resolve the IEEE Xplore key from pass, then hapax-secrets exported env."""
    try:
        result = subprocess.run(
            ["pass", "show", IEEE_XPLORE_PASS_PATH],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            key = result.stdout.strip().splitlines()[0]
            if key:
                return key, None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    env_key = os.environ.get(IEEE_XPLORE_API_KEY_ENV, "").strip()
    if env_key:
        return env_key, None

    return None, f"ieee_xplore:missing_api_key:{IEEE_XPLORE_PASS_PATH}|${IEEE_XPLORE_API_KEY_ENV}"


def sweep_github(gap: dict) -> SignalResult:
    terms = build_search_terms(gap)
    all_results: list[dict] = []
    source_urls: list[str] = []
    errors: list[str] = []

    for term in terms[:3]:
        try:
            proc = subprocess.run(
                [
                    "gh",
                    "api",
                    "search/code",
                    "-f",
                    f"q={term}",
                    "-f",
                    "per_page=5",
                    "--jq",
                    ".items[] | {repo: .repository.full_name, path: .path, score: .score}",
                ],
                capture_output=True,
                text=True,
                timeout=SWEEP_TIMEOUT,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                for line in proc.stdout.strip().split("\n"):
                    try:
                        item = json.loads(line)
                        all_results.append(item)
                        source_urls.append(
                            f"https://github.com/{item['repo']}/blob/main/{item['path']}"
                        )
                    except json.JSONDecodeError:
                        continue
            elif proc.returncode != 0:
                errors.append(f"github:{proc.stderr.strip() or f'exit_{proc.returncode}'}")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            return SignalResult(
                signal="code_search",
                vote="inconclusive",
                confidence=0.0,
                error=str(e),
            )
        time.sleep(1)

    unique_repos = {r.get("repo") for r in all_results}

    if len(unique_repos) >= 5:
        vote = "prior_art_exists"
        confidence = min(1.0, len(unique_repos) / 10)
    elif len(unique_repos) >= 2:
        vote = "inconclusive"
        confidence = 0.5
    elif errors and not unique_repos:
        vote = "inconclusive"
        confidence = 0.0
    else:
        vote = "novel"
        confidence = 0.7 if len(unique_repos) == 0 else 0.5

    return SignalResult(
        signal="code_search",
        vote=vote,
        confidence=confidence,
        evidence=all_results[:10],
        source_urls=source_urls[:10],
        error="; ".join(errors) or None,
    )


def sweep_semantic_scholar(gap: dict) -> SignalResult:
    terms = build_search_terms(gap)
    all_papers: list[dict] = []
    source_urls: list[str] = []
    errors: list[str] = []

    for term in terms[:2]:
        try:
            resp = httpx.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": term, "limit": 10, "fields": "title,year,citationCount,url"},
                timeout=HTTP_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                for paper in data.get("data", []):
                    all_papers.append(
                        {
                            "title": paper.get("title"),
                            "year": paper.get("year"),
                            "citations": paper.get("citationCount", 0),
                        }
                    )
                    if paper.get("url"):
                        source_urls.append(paper["url"])
            else:
                errors.append(f"semantic_scholar:http_{resp.status_code}")
        except httpx.HTTPError as e:
            return SignalResult(
                signal="academic_papers",
                vote="inconclusive",
                confidence=0.0,
                error=str(e),
            )
        time.sleep(1)

    highly_relevant = [p for p in all_papers if p.get("citations", 0) > 10]

    if len(highly_relevant) >= 3:
        vote = "prior_art_exists"
        confidence = min(1.0, len(highly_relevant) / 5)
    elif len(all_papers) >= 5:
        vote = "inconclusive"
        confidence = 0.4
    elif errors and not all_papers:
        vote = "inconclusive"
        confidence = 0.0
    else:
        vote = "novel"
        confidence = 0.6 if len(all_papers) == 0 else 0.4

    return SignalResult(
        signal="academic_papers",
        vote=vote,
        confidence=confidence,
        evidence=all_papers[:10],
        source_urls=source_urls[:10],
        error="; ".join(errors) or None,
    )


def sweep_patents(gap: dict) -> SignalResult:
    terms = build_search_terms(gap)
    all_patents: list[dict] = []
    errors: list[str] = []
    successful_sources = 0

    for term in terms[:2]:
        try:
            resp = httpx.get(
                GOOGLE_PATENTS_URL,
                params={"q": term, "num": 10},
                headers={"User-Agent": "hapax-gap-validate/1.0"},
                timeout=HTTP_TIMEOUT,
            )
            if resp.status_code == 200:
                successful_sources += 1
                for match in PATENT_LINK_RE.finditer(resp.text):
                    href = match.group("href")
                    patent_id = href.removeprefix("/patent/").split("/", 1)[0]
                    all_patents.append(
                        {
                            "source": "google_patents",
                            "title": patent_id,
                            "url": urljoin(GOOGLE_PATENTS_URL, href),
                        }
                    )
            else:
                errors.append(f"google_patents:http_{resp.status_code}")
        except httpx.HTTPError as e:
            errors.append(f"google_patents:{e}")
        time.sleep(0.5)

    all_patents = _unique_by_url(all_patents)
    if not all_patents:
        try:
            resp = httpx.get(
                OPENALEX_WORKS_URL,
                params={
                    "search": terms[0],
                    "filter": "type:patent|type:standard",
                    "per_page": 10,
                },
                timeout=HTTP_TIMEOUT,
            )
            if resp.status_code == 200:
                successful_sources += 1
                data = resp.json()
                for work in data.get("results", []):
                    all_patents.append(
                        {
                            "source": "openalex",
                            "title": work.get("title"),
                            "year": work.get("publication_year"),
                            "doi": work.get("doi"),
                        }
                    )
            else:
                errors.append(f"openalex:http_{resp.status_code}")
        except httpx.HTTPError as e:
            return SignalResult(
                signal="patents",
                vote="inconclusive",
                confidence=0.0,
                error="; ".join([*errors, f"openalex:{e}"]),
            )

    all_patents = _unique_by_url(all_patents)
    if len(all_patents) >= 3:
        vote = "prior_art_exists"
        confidence = min(1.0, len(all_patents) / 5)
    elif len(all_patents) >= 1:
        vote = "inconclusive"
        confidence = 0.4
    elif errors and successful_sources == 0:
        vote = "inconclusive"
        confidence = 0.0
    else:
        vote = "novel"
        confidence = 0.6

    return SignalResult(
        signal="patents",
        vote=vote,
        confidence=confidence,
        evidence=all_patents[:10],
        source_urls=_source_urls(all_patents)[:10],
        error="; ".join(errors) or None,
    )


def sweep_papers_with_code(gap: dict) -> SignalResult:
    terms = build_search_terms(gap)
    all_results: list[dict] = []
    source_urls: list[str] = []
    errors: list[str] = []

    for term in terms[:2]:
        try:
            resp = httpx.get(
                "https://paperswithcode.com/api/v1/papers/",
                params={"q": term, "items_per_page": 10},
                timeout=HTTP_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                for paper in data.get("results", []):
                    all_results.append(
                        {
                            "source": "papers_with_code",
                            "title": paper.get("title"),
                            "published": paper.get("published"),
                            "stars": paper.get("repository_stars", 0),
                            "url": paper.get("url_abs"),
                        }
                    )
                    if paper.get("url_abs"):
                        source_urls.append(paper["url_abs"])
            else:
                errors.append(f"papers_with_code:http_{resp.status_code}")
        except httpx.HTTPError as e:
            return SignalResult(
                signal="papers_with_code",
                vote="inconclusive",
                confidence=0.0,
                error=str(e),
            )
        time.sleep(1)

    with_code = [r for r in all_results if r.get("stars", 0) > 0]

    if len(with_code) >= 3:
        vote = "prior_art_exists"
        confidence = min(1.0, len(with_code) / 5)
    elif len(all_results) >= 3:
        vote = "inconclusive"
        confidence = 0.4
    elif errors and not all_results:
        vote = "inconclusive"
        confidence = 0.0
    else:
        vote = "novel"
        confidence = 0.6 if len(all_results) == 0 else 0.4

    return SignalResult(
        signal="papers_with_code",
        vote=vote,
        confidence=confidence,
        evidence=all_results[:10],
        source_urls=source_urls[:10],
        error="; ".join(errors) or None,
    )


def sweep_code_search(gap: dict) -> SignalResult:
    github = sweep_github(gap)
    papers_with_code = sweep_papers_with_code(gap)
    signals = [github, papers_with_code]
    evidence: list[dict] = []
    urls: list[str] = []

    for signal in signals:
        evidence.extend({"source_signal": signal.signal, **item} for item in signal.evidence)
        urls.extend(signal.source_urls)

    prior_art = [signal for signal in signals if signal.vote == "prior_art_exists"]
    novel = [signal for signal in signals if signal.vote == "novel"]
    if prior_art:
        vote = "prior_art_exists"
        confidence = max(signal.confidence for signal in prior_art)
    elif len(novel) == len(signals):
        vote = "novel"
        confidence = min(signal.confidence for signal in novel)
    else:
        vote = "inconclusive"
        confidence = max((signal.confidence for signal in signals), default=0.0)

    errors = "; ".join(signal.error for signal in signals if signal.error)
    return SignalResult(
        signal="code_search",
        vote=vote,
        confidence=confidence,
        evidence=evidence[:15],
        source_urls=urls[:15],
        error=errors or None,
    )


def _sweep_ieee_xplore(terms: list[str]) -> tuple[list[dict], list[str]]:
    api_key, missing_error = _resolve_ieee_xplore_api_key()
    if not api_key:
        return [], [missing_error] if missing_error else []

    results: list[dict] = []
    errors: list[str] = []
    for term in terms[:2]:
        resp = httpx.get(
            IEEE_XPLORE_URL,
            params={"querytext": term, "max_records": 10, "apikey": api_key},
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            errors.append(f"ieee_xplore:http_{resp.status_code}")
            continue
        for article in resp.json().get("articles", []):
            url = article.get("html_url") or article.get("pdf_url")
            results.append(
                {
                    "source": "ieee_xplore",
                    "title": article.get("title"),
                    "year": article.get("publication_year"),
                    "url": url,
                }
            )
        time.sleep(1)
    return results, errors


def _sweep_acm_dl(terms: list[str]) -> tuple[list[dict], list[str]]:
    results: list[dict] = []
    errors: list[str] = []
    for term in terms[:2]:
        resp = httpx.get(
            ACM_DL_SEARCH_URL,
            params={"AllField": term},
            headers={"User-Agent": "hapax-gap-validate/1.0"},
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            errors.append(f"acm_dl:http_{resp.status_code}")
            continue
        for match in ACM_DOI_LINK_RE.finditer(resp.text):
            href = match.group("href")
            results.append(
                {
                    "source": "acm_dl",
                    "title": _strip_html(match.group("title")) or href.rsplit("/", 1)[-1],
                    "url": urljoin("https://dl.acm.org", href),
                }
            )
        time.sleep(1)
    return results, errors


def sweep_trade_archive(gap: dict) -> SignalResult:
    terms = build_search_terms(gap)
    results: list[dict] = []
    errors: list[str] = []

    try:
        ieee_results, ieee_errors = _sweep_ieee_xplore(terms)
        results.extend(ieee_results)
        errors.extend(ieee_errors)
    except httpx.HTTPError as e:
        errors.append(f"ieee_xplore:{e}")
    try:
        acm_results, acm_errors = _sweep_acm_dl(terms)
        results.extend(acm_results)
        errors.extend(acm_errors)
    except httpx.HTTPError as e:
        errors.append(f"acm_dl:{e}")

    results = _unique_by_url(results)
    if len(results) >= 3:
        vote = "prior_art_exists"
        confidence = min(1.0, len(results) / 5)
    elif len(results) >= 1:
        vote = "inconclusive"
        confidence = 0.4
    elif errors:
        vote = "inconclusive"
        confidence = 0.0
    else:
        vote = "novel"
        confidence = 0.5

    return SignalResult(
        signal="trade_pubs",
        vote=vote,
        confidence=confidence,
        evidence=results[:10],
        source_urls=_source_urls(results)[:10],
        error="; ".join(errors) or None,
    )


def placeholder_signal(name: str) -> SignalResult:
    return SignalResult(
        signal=name,
        vote="inconclusive",
        confidence=0.0,
        error=f"{name} requires manual Phase 2/3 execution",
    )


def compute_decision(signals: list[SignalResult]) -> tuple[str, int, int]:
    novel_votes = sum(1 for s in signals if s.vote == "novel")
    prior_art_votes = sum(1 for s in signals if s.vote == "prior_art_exists")

    if novel_votes >= 4:
        return "high_confidence_novel", novel_votes, len(signals)
    if novel_votes >= 3:
        return "medium_confidence_novel", novel_votes, len(signals)
    if prior_art_votes >= 3:
        return "likely_not_novel", novel_votes, len(signals)
    return "low_confidence_needs_phase2", novel_votes, len(signals)


def run_sweep(gap: dict) -> SweepResult:
    logger.info("Sweeping %s: %s", gap["gap_id"], gap["title"])
    result = SweepResult(
        gap_id=gap["gap_id"],
        title=gap["title"],
        sweep_timestamp=datetime.now().isoformat(),
    )

    sweepers = [
        ("patents", sweep_patents),
        ("code_search", sweep_code_search),
        ("academic_papers", sweep_semantic_scholar),
        ("trade_pubs", sweep_trade_archive),
    ]

    for name, fn in sweepers:
        logger.info("  Running %s sweep...", name)
        signal = fn(gap)
        result.signals.append(signal)
        logger.info("    → %s (confidence=%.2f)", signal.vote, signal.confidence)

    result.signals.append(placeholder_signal("forums"))
    result.signals.append(placeholder_signal("practitioner_observation"))

    result.decision, result.novel_votes, result.total_signals = compute_decision(result.signals)
    logger.info("  Decision: %s (%d novel votes)", result.decision, result.novel_votes)
    return result


def write_sweep_results(result: SweepResult) -> Path:
    VAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = VAULT_OUTPUT_DIR / f"{result.gap_id}-sweep-results.json"
    output_path.write_text(
        json.dumps(asdict(result), indent=2, default=str),
        encoding="utf-8",
    )
    return output_path


def update_registry_status(gap_id: str, decision: str) -> None:
    status_map = {
        "high_confidence_novel": "validated_novel",
        "medium_confidence_novel": "likely_novel_needs_phase2",
        "likely_not_novel": "prior_art_detected",
        "low_confidence_needs_phase2": "needs_phase2_validation",
    }
    new_status = status_map.get(decision, "needs_phase2_validation")

    text = REGISTRY_PATH.read_text(encoding="utf-8")
    registry = yaml.safe_load(text)
    for gap in registry.get("gaps", []):
        if gap["gap_id"] == gap_id:
            gap["validation_status"] = new_status
            gap["last_reviewed"] = datetime.now().strftime("%Y-%m-%d")
            break

    REGISTRY_PATH.write_text(
        yaml.dump(registry, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def generate_forum_post(gap: dict) -> str:
    return dedent(f"""\
    # Forum Post Template — {gap["gap_id"]}: {gap["title"]}

    **Subject:** Looking for prior work on {gap["title"].lower()}

    **Body:**

    Hi all,

    I'm working on a research project involving {gap["title"].lower()} and I'm
    trying to determine whether existing solutions or prior art address this
    specific combination of requirements.

    **Context:** {gap.get("apparatus_justification", "See gap registry for details.")}

    **Specific questions:**
    1. Are you aware of any systems that combine these capabilities in a single
       architecture?
    2. Have you seen academic papers or patents that address this intersection?
    3. Is there ongoing work in your community that touches on these requirements?

    **What I've found so far:** [Insert Phase 1 sweep results summary here]

    Any pointers — papers, projects, or practitioners — would be appreciated.
    I'm happy to share what I find in return.

    Thanks,
    [Operator name]

    ---
    *Generated by gap-validate for {gap["gap_id"]}*
    *Disposition: {gap.get("disposition", "unknown")} | Uniqueness: {gap.get("uniqueness_score", "N/A")}*
    """)


def generate_cold_email(gap: dict) -> str:
    return dedent(f"""\
    # Cold Email Template — {gap["gap_id"]}: {gap["title"]}

    **To:** [Researcher name / systematic review author]
    **Subject:** Prior work inquiry: {gap["title"].lower()}

    Dear [Name],

    I read your work on [specific paper/project] with interest. I'm conducting
    a gap validation for a research project and your expertise is directly
    relevant.

    **The gap:** {gap["title"]}
    **Why it matters:** {gap.get("apparatus_justification", "See gap registry.")}

    **My specific question:** In your experience, has anyone built a system
    that addresses this specific intersection of requirements? I'm particularly
    interested in whether the combination (not individual components) has been
    attempted.

    **What I've found so far:** [Insert Phase 1 sweep summary]

    I'd be grateful for any pointers — even a brief reply pointing me to
    relevant work would save significant validation time. Happy to share
    my findings and cite your guidance in any resulting publication.

    Best regards,
    [Operator name]
    [Affiliation / project URL]

    ---
    *Generated by gap-validate for {gap["gap_id"]}*
    *Decision matrix signals collected: [N/6]*
    """)


def generate_phase2_scaffolding(gap: dict) -> Path:
    VAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = VAULT_OUTPUT_DIR / f"{gap['gap_id']}-phase2-scaffolding.md"
    content = f"# Phase 2 Community Probe Scaffolding — {gap['gap_id']}\n\n"
    content += f"Generated: {datetime.now().isoformat()}\n\n"
    content += "## Forum Post Template\n\n"
    content += generate_forum_post(gap)
    content += "\n\n## Cold Email Template\n\n"
    content += generate_cold_email(gap)
    output_path.write_text(content, encoding="utf-8")
    return output_path


OBSERVATION_GUIDE_CONTENT = """\
# Phase 3: Practitioner Observation Guide

## Purpose

Remote contextual inquiry protocol for validating research gaps that remain
ambiguous after Phase 1 (automated sweep) and Phase 2 (community probe).
Use when the decision matrix yields fewer than 4 agreeing signals.

## When to Use

- Phase 1 sweep returned "low_confidence_needs_phase2" or "medium_confidence_novel"
- Phase 2 community probes returned mixed or no responses
- The gap involves tacit knowledge that published sources may not capture

## Participant Selection

Target 3-5 domain practitioners who:
- Work in the intersection area described by the gap
- Have 5+ years domain experience
- Are NOT the gap author (avoid confirmation bias)
- Represent different organizational contexts (academic, industry, open source)

## Interview Protocol (Remote Contextual Inquiry)

Duration: 30-45 minutes, recorded with consent.

### Opening (5 min)

Explain the purpose: "I'm validating whether a specific research gap is
genuinely novel. I'll describe a capability intersection and ask whether
you've encountered anything similar."

### Core Questions (20-30 min)

1. **Current practice:** "In your work on [domain], how do you currently
   handle [core capability described by the gap]?"

2. **Combination awareness:** "Have you seen a system that combines
   [component A] with [component B] in a single architecture? If so,
   what were the results?"

3. **Barrier identification:** "What prevents practitioners in your field
   from building something like [gap description]? Is it technical
   complexity, lack of need, or something else?"

4. **Prior attempts:** "Are you aware of any projects — published or
   unpublished — that attempted this combination? What happened to them?"

5. **Tacit knowledge:** "Is there domain knowledge about why this
   combination is difficult or unnecessary that wouldn't appear in
   published literature?"

6. **Community awareness:** "If someone had solved this, where would you
   expect to find evidence? Which conferences, forums, or communities?"

7. **Validation of novelty:** "On a scale of 1-5, how surprised would
   you be to learn that no existing system combines these capabilities?
   (1 = not surprised at all, 5 = very surprised)"

### Closing (5 min)

- Ask for referrals to other practitioners
- Offer to share findings
- Confirm consent for anonymized use in publications

## Scoring

Map each interview to a signal vote:
- Surprise score 4-5 + no prior examples cited → **novel**
- Surprise score 2-3 + some partial examples → **inconclusive**
- Surprise score 1 + specific prior art cited → **prior_art_exists**

Aggregate across 3-5 participants. Majority vote becomes the
`practitioner_observation` signal in the decision matrix.

## Output

Write results to `{gap_id}-phase3-observation.json` with:
- participant_count
- anonymized responses per question
- individual votes
- aggregate vote
- referenced prior art (if any)

## Ethics

- Obtain informed consent before recording
- Anonymize all participant data in outputs
- Do not name participants in publications without explicit permission
- Offer co-authorship if contributions are substantial
"""


def generate_observation_guide() -> Path:
    OBSERVATION_GUIDE_PATH.write_text(OBSERVATION_GUIDE_CONTENT, encoding="utf-8")
    return OBSERVATION_GUIDE_PATH


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gap validation protocol — automated prior-art sweep + decision matrix"
    )
    sub = parser.add_subparsers(dest="command")

    sweep_p = sub.add_parser("sweep", help="Run Phase 1 automated sweep for a gap")
    sweep_p.add_argument("gap_id", help="Gap ID (e.g., GAP-001)")
    sweep_p.add_argument(
        "--update-registry",
        action="store_true",
        help="Update the registry validation_status field",
    )

    scaffold_p = sub.add_parser("scaffold", help="Generate Phase 2 community probe scaffolding")
    scaffold_p.add_argument("gap_id", help="Gap ID (e.g., GAP-001)")

    sub.add_parser("observation-guide", help="Generate Phase 3 practitioner observation guide")

    batch_p = sub.add_parser("batch", help="Run sweep + scaffold for multiple gaps")
    batch_p.add_argument("gap_ids", nargs="+", help="Gap IDs")
    batch_p.add_argument(
        "--update-registry",
        action="store_true",
        help="Update the registry validation_status field",
    )

    for p in [parser, sweep_p, scaffold_p, batch_p]:
        p.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if not args.command:
        parser.print_help()
        return 1

    registry = load_registry()

    if args.command == "observation-guide":
        path = generate_observation_guide()
        print(f"Observation guide written to {path}")
        return 0

    if args.command == "sweep":
        gap = find_gap(registry, args.gap_id)
        if not gap:
            logger.error("Gap %s not found in registry", args.gap_id)
            return 1
        result = run_sweep(gap)
        path = write_sweep_results(result)
        print(f"Sweep results written to {path}")
        print(
            f"Decision: {result.decision} ({result.novel_votes} novel votes / {result.total_signals} total)"
        )
        if args.update_registry:
            update_registry_status(args.gap_id, result.decision)
            print(f"Registry updated for {args.gap_id}")
        return 0

    if args.command == "scaffold":
        gap = find_gap(registry, args.gap_id)
        if not gap:
            logger.error("Gap %s not found in registry", args.gap_id)
            return 1
        path = generate_phase2_scaffolding(gap)
        print(f"Phase 2 scaffolding written to {path}")
        return 0

    if args.command == "batch":
        for gap_id in args.gap_ids:
            gap = find_gap(registry, gap_id)
            if not gap:
                logger.error("Gap %s not found, skipping", gap_id)
                continue
            result = run_sweep(gap)
            sweep_path = write_sweep_results(result)
            scaffold_path = generate_phase2_scaffolding(gap)
            print(f"{gap_id}: {result.decision} ({result.novel_votes} novel) → {sweep_path}")
            print(f"  scaffold → {scaffold_path}")
            if args.update_registry:
                update_registry_status(gap_id, result.decision)
                print("  registry updated")
            time.sleep(2)

        guide_path = generate_observation_guide()
        print(f"\nObservation guide → {guide_path}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
