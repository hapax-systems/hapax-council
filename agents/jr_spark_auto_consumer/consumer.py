"""Auto-consumption runner for unrouted Jr/Spark packets.

This agent is deliberately narrow:

* classify pending ``ready_for_senior_review`` packets against PR / cc-task /
  commit artefacts;
* call the existing ``hapax-gemini-jr-team`` state-machine for packet status
  transitions;
* create an offered cc-task only when a packet is actionable and unmatched.

It never edits already-existing cc-task notes. Matched or duplicate tasks are
linked via packet frontmatter only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_PACKET_ROOT = Path.home() / ".cache/hapax/gemini-jr-team/packets"
DEFAULT_STATE_ROOT = Path.home() / ".cache/hapax/jr-spark-auto-consumer"
DEFAULT_VAULT_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"
JR_SPARK_AUTO_CONSUMER = "jr-spark-auto"

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_DATE_RE = re.compile(r"^(?:20[0-9]{2}|[0-9]{6,8}|[0-9]+)$")
_PREFIXES = (
    "test-gaps-",
    "review-",
    "currentness-scout-",
    "aesthetic-scout-",
    "large-context-",
    "extract-from-",
    "extract-",
    "agents-",
    "agent-",
    "jr-",
    "spark-",
)
_SUFFIXES = (
    "-design",
    "-deep-read",
    "-deep",
    "-architecture-summary",
    "-architecture",
    "-summary",
    "-inventory",
    "-aesthetic-options",
    "-aesthetic",
    "-research",
    "-current",
    "-recent",
    "-best",
)
_STOP_TERMS = {
    "aesthetic",
    "agent",
    "agents",
    "api",
    "architecture",
    "audit",
    "auto",
    "best",
    "changes",
    "context",
    "current",
    "currentness",
    "deep",
    "design",
    "extract",
    "extractor",
    "feature",
    "features",
    "final",
    "follow",
    "followup",
    "from",
    "gap",
    "gaps",
    "jr",
    "large",
    "merged",
    "options",
    "packet",
    "packets",
    "practice",
    "practices",
    "recent",
    "research",
    "review",
    "reviewer",
    "scout",
    "spark",
    "status",
    "summary",
    "test",
    "tests",
}


@dataclass(frozen=True)
class Packet:
    """A pending Jr/Spark packet."""

    path: Path
    frontmatter: Mapping[str, str]
    body: str

    @property
    def jr_role(self) -> str:
        return self.frontmatter.get("jr_role", "")

    @property
    def task_id(self) -> str:
        return self.frontmatter.get("task_id", self.path.stem)

    @property
    def title(self) -> str:
        return _decode_scalar(self.frontmatter.get("title", self.task_id))

    @property
    def search_text(self) -> str:
        return " ".join((self.path.name, self.task_id, self.title, self.body[:4000]))


@dataclass(frozen=True)
class Artefact:
    """A senior-owned artefact the packet may already have fed."""

    kind: str
    ref: str
    text: str
    status: str = ""
    assigned_to: str = ""
    source_path: Path | None = None


@dataclass(frozen=True)
class Match:
    """Best senior artefact match for a packet."""

    artefact: Artefact
    score: float
    reason: str
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class Classification:
    """Classifier decision before side effects are applied."""

    action: str
    reason: str
    artefact: str | None = None
    matched_terms: tuple[str, ...] = ()
    task_id: str | None = None
    score: float = 0.0


@dataclass(frozen=True)
class AutoConsumerConfig:
    """Runtime inputs for one auto-consumer pass."""

    packet_root: Path
    vault_root: Path
    repo_root: Path
    jr_team_bin: Path
    state_root: Path = DEFAULT_STATE_ROOT
    max_packets: int = 25
    older_than_minutes: int = 0
    enable_gh: bool = True
    gh_cache_ttl_seconds: int = 300
    git_log_limit: int = 200
    dry_run: bool = False


@dataclass(frozen=True)
class AppliedAction:
    """A packet decision after the runner applied or dry-ran it."""

    packet: str
    action: str
    reason: str
    artefact: str | None = None
    task_id: str | None = None
    matched_terms: tuple[str, ...] = ()
    score: float = 0.0


class StateMachineClient:
    """Protocol-like base for packet state transitions."""

    def consume(self, packet: Path, artefact: str, *, note: str | None = None) -> None:
        raise NotImplementedError

    def supersede(self, packet: Path, reason: str) -> None:
        raise NotImplementedError


class SubprocessStateMachineClient(StateMachineClient):
    """Invoke ``hapax-gemini-jr-team`` for packet status transitions."""

    def __init__(self, command: Path) -> None:
        self._command = command

    def consume(self, packet: Path, artefact: str, *, note: str | None = None) -> None:
        cmd = [
            str(self._command),
            "consume",
            str(packet),
            "--by",
            JR_SPARK_AUTO_CONSUMER,
            "--artefact",
            artefact,
        ]
        if note:
            cmd.extend(("--note", note))
        _run_checked(cmd, timeout=30)

    def supersede(self, packet: Path, reason: str) -> None:
        _run_checked(
            [
                str(self._command),
                "supersede",
                str(packet),
                "--by",
                JR_SPARK_AUTO_CONSUMER,
                "--reason",
                reason,
            ],
            timeout=30,
        )


class RecordingStateMachineClient(StateMachineClient):
    """Test/dry-run client that records intended state-machine calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def consume(self, packet: Path, artefact: str, *, note: str | None = None) -> None:
        self.calls.append(
            ("consume", str(packet), artefact if note is None else f"{artefact} | {note}")
        )

    def supersede(self, packet: Path, reason: str) -> None:
        self.calls.append(("supersede", str(packet), reason))


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_checked(cmd: Sequence[str], *, timeout: int) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{cmd[0]} failed with {result.returncode}: {detail}")
    return result.stdout


def _safe_slug(value: str) -> str:
    slug = "-".join(_TOKEN_RE.findall(value.lower()))
    return slug[:100].strip("-") or "jr-spark-packet"


def _decode_scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value.strip('"')
        return str(decoded)
    return value


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("missing opening frontmatter delimiter")
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        raise ValueError("missing closing frontmatter delimiter")
    fm_text = rest[:end]
    body = rest[end + 5 :]
    data: dict[str, str] = {}
    for line in fm_text.splitlines():
        if not line or line.startswith(" ") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip()
    return data, body


def _read_packet(path: Path) -> Packet | None:
    try:
        fm, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return Packet(path=path, frontmatter=fm, body=body)


def _ts_from_filename(name: str) -> datetime | None:
    if len(name) < 16:
        return None
    try:
        return datetime.strptime(name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _is_pending(packet: Packet, *, older_than_minutes: int) -> bool:
    if packet.frontmatter.get("status") != "ready_for_senior_review":
        return False
    if packet.frontmatter.get("senior_review_required", "").lower() == "false":
        return False
    if older_than_minutes <= 0:
        return True
    ts = _ts_from_filename(packet.path.name)
    if ts is None:
        return True
    return ts <= _now() - timedelta(minutes=older_than_minutes)


def iter_pending_packets(
    packet_root: Path,
    *,
    older_than_minutes: int = 0,
    max_packets: int | None = None,
) -> list[Packet]:
    packets: list[Packet] = []
    for path in sorted(packet_root.glob("*.md")):
        packet = _read_packet(path)
        if packet is None or not _is_pending(packet, older_than_minutes=older_than_minutes):
            continue
        packets.append(packet)
        if max_packets is not None and len(packets) >= max_packets:
            break
    return packets


def _normalize_slug(value: str) -> str:
    return _safe_slug(value)


def _strip_packet_slug(value: str) -> str:
    slug = _normalize_slug(value)
    changed = True
    while changed:
        changed = False
        for prefix in _PREFIXES:
            if slug.startswith(prefix):
                slug = slug[len(prefix) :]
                changed = True
        for suffix in _SUFFIXES:
            if slug.endswith(suffix):
                slug = slug[: -len(suffix)]
                changed = True
    return slug.strip("-")


def _terms(value: str) -> set[str]:
    out: set[str] = set()
    for token in _TOKEN_RE.findall(value.lower()):
        if len(token) < 3 or token in _STOP_TERMS or _DATE_RE.match(token):
            continue
        out.add(token)
    return out


def _packet_terms(packet: Packet) -> set[str]:
    stripped = _strip_packet_slug(packet.task_id)
    return _terms(" ".join((packet.task_id, stripped, packet.title)))


def _contains_slug(text: str, slug: str) -> bool:
    if not slug or len(slug) < 5:
        return False
    return f"-{slug}-" in f"-{_normalize_slug(text)}-"


def _score(packet: Packet, artefact: Artefact) -> Match | None:
    packet_slug = _normalize_slug(packet.task_id)
    stripped = _strip_packet_slug(packet.task_id)
    text = " ".join((artefact.ref, artefact.text))
    if _contains_slug(text, packet_slug):
        return Match(artefact, 1.0, "task-id-match", (packet_slug,))
    if stripped != packet_slug and _contains_slug(text, stripped):
        return Match(artefact, 0.92, "stripped-prefix-match", (stripped,))

    p_terms = _packet_terms(packet)
    if not p_terms:
        return None
    matched = tuple(sorted(p_terms & _terms(text)))
    if len(matched) < 2:
        return None

    ratio = len(matched) / max(len(p_terms), 1)
    score = min(0.88, 0.52 + (0.07 * len(matched)) + (0.20 * ratio))
    if score < 0.66:
        return None
    return Match(artefact, score, "multi-keyword", matched)


def _best_match(packet: Packet, artefacts: Iterable[Artefact]) -> Match | None:
    matches = [match for artefact in artefacts if (match := _score(packet, artefact))]
    if not matches:
        return None
    return max(matches, key=lambda match: (match.score, match.artefact.kind == "cc-task"))


def _noop_pattern(packet: Packet) -> str | None:
    task_text = " ".join((packet.jr_role, packet.task_id, packet.title)).lower()
    if packet.jr_role == "jr-currentness-scout":
        return "currentness scout"
    if packet.jr_role == "jr-aesthetic-scout":
        return "aesthetic scout"
    if packet.jr_role == "jr-large-context":
        return "large-context"
    if packet.jr_role == "jr-extractor" and "telemetry" in task_text:
        return "extractor-telemetry"
    if packet.jr_role == "jr-reviewer" and ("post-merge" in task_text or "merged" in task_text):
        return "post-merge-review"
    return None


def classify_packet(packet: Packet, artefacts: Iterable[Artefact]) -> Classification:
    match = _best_match(packet, artefacts)
    if match is not None:
        return Classification(
            action="consume",
            reason=match.reason,
            artefact=match.artefact.ref,
            matched_terms=match.matched_terms,
            score=match.score,
        )

    pattern = _noop_pattern(packet)
    if pattern is not None:
        return Classification(
            action="supersede",
            reason=f"auto-classified pattern: {pattern}",
            score=0.0,
        )

    task_id = _safe_slug(packet.task_id)
    return Classification(
        action="create_task",
        reason="actionable unmatched packet",
        artefact=f"cc-task/{task_id}",
        task_id=task_id,
        score=0.0,
    )


def _iter_task_dirs(vault_root: Path) -> list[Path]:
    return [
        vault_root / name
        for name in ("active", "closed", "refused", "grants")
        if (vault_root / name).is_dir()
    ]


def _load_cc_task(path: Path) -> Artefact | None:
    try:
        fm, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if fm.get("type") != "cc-task":
        return None
    task_id = _decode_scalar(fm.get("task_id", path.stem))
    title = _decode_scalar(fm.get("title", task_id))
    status = _decode_scalar(fm.get("status", ""))
    assigned_to = _decode_scalar(fm.get("assigned_to", ""))
    text = " ".join((path.name, task_id, title, body[:5000]))
    return Artefact(
        kind="cc-task",
        ref=f"cc-task/{task_id}",
        text=text,
        status=status,
        assigned_to=assigned_to,
        source_path=path,
    )


def load_cc_task_artefacts(vault_root: Path) -> list[Artefact]:
    artefacts: list[Artefact] = []
    for task_dir in _iter_task_dirs(vault_root):
        for path in sorted(task_dir.glob("*.md")):
            artefact = _load_cc_task(path)
            if artefact is not None:
                artefacts.append(artefact)
    return artefacts


def _load_commit_artefacts(repo_root: Path, *, limit: int) -> list[Artefact]:
    if limit <= 0:
        return []
    try:
        out = _run_checked(
            ["git", "-C", str(repo_root), "log", f"--max-count={limit}", "--format=%H%x00%s"],
            timeout=10,
        )
    except (RuntimeError, subprocess.TimeoutExpired):
        return []
    artefacts: list[Artefact] = []
    for line in out.splitlines():
        sha, sep, subject = line.partition("\0")
        if not sep or not sha:
            continue
        artefacts.append(Artefact(kind="commit", ref=f"commit/{sha[:12]}", text=subject))
    return artefacts


def _gh_cache_path(state_root: Path) -> Path:
    return state_root / "gh-pr-list.json"


def _read_json_cache(path: Path, *, ttl_seconds: int) -> list[dict[str, object]] | None:
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl_seconds:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list):
        return None
    return [item for item in payload if isinstance(item, dict)]


def _load_gh_prs(state_root: Path, *, ttl_seconds: int) -> list[dict[str, object]]:
    cache_path = _gh_cache_path(state_root)
    cached = _read_json_cache(cache_path, ttl_seconds=ttl_seconds)
    if cached is not None:
        return cached

    cmd = [
        "gh",
        "pr",
        "list",
        "--state",
        "all",
        "--limit",
        "100",
        "--json",
        "number,title,body,headRefName",
    ]
    try:
        payload = _run_checked(cmd, timeout=20)
        parsed = json.loads(payload)
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError):
        fallback = _read_json_cache(cache_path, ttl_seconds=60 * 60 * 24)
        return fallback or []

    if not isinstance(parsed, list):
        return []
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(parsed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return [item for item in parsed if isinstance(item, dict)]


def _load_pr_artefacts(state_root: Path, *, ttl_seconds: int) -> list[Artefact]:
    artefacts: list[Artefact] = []
    for item in _load_gh_prs(state_root, ttl_seconds=ttl_seconds):
        number = item.get("number")
        if not isinstance(number, int):
            continue
        text = " ".join(str(item.get(key) or "") for key in ("title", "body", "headRefName"))
        artefacts.append(Artefact(kind="pr", ref=f"pr/{number}", text=text))
    return artefacts


def load_runtime_artefacts(config: AutoConsumerConfig) -> list[Artefact]:
    artefacts = load_cc_task_artefacts(config.vault_root)
    artefacts.extend(_load_commit_artefacts(config.repo_root, limit=config.git_log_limit))
    if config.enable_gh:
        artefacts.extend(
            _load_pr_artefacts(config.state_root, ttl_seconds=config.gh_cache_ttl_seconds)
        )
    return artefacts


def _existing_task_ids(vault_root: Path) -> set[str]:
    ids: set[str] = set()
    for artefact in load_cc_task_artefacts(vault_root):
        ids.add(artefact.ref.removeprefix("cc-task/"))
    return ids


def _unique_task_id(base: str, existing_ids: set[str]) -> str:
    candidate = base
    counter = 2
    while candidate in existing_ids:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _write_offered_task(packet: Packet, vault_root: Path, *, task_id: str) -> Path:
    active_dir = vault_root / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    path = active_dir / f"{task_id}.md"
    title = packet.title if packet.title else packet.task_id
    body = "\n".join(
        [
            "---",
            "type: cc-task",
            f"task_id: {task_id}",
            f"title: {json.dumps(title)}",
            "status: offered",
            "assigned_to: unassigned",
            "priority: p3",
            "wsjf: 3",
            "audit_origin: jr-spark-auto-consumer",
            f"source_packet: {packet.path.name}",
            f"source_packet_path: {json.dumps(str(packet.path))}",
            f"created_at: {_iso()}",
            "tags:",
            "  - cc-task",
            "  - jr-spark",
            "  - auto-created",
            "---",
            "",
            f"# {title}",
            "",
            "## Intent",
            "",
            "Jr/Spark auto-consumption found this packet actionable but unmatched to an",
            "existing senior-owned PR, cc-task, or commit. A senior lane should inspect",
            "the source packet and either implement, merge into another task, or supersede.",
            "",
            "## Source Packet",
            "",
            f"- Packet: `{packet.path}`",
            f"- Jr role: `{packet.jr_role}`",
            f"- Packet task_id: `{packet.task_id}`",
            "",
            "## Acceptance",
            "",
            "- Senior lane verifies packet evidence before acting.",
            "- Useful findings are converted into a normal branch/PR or folded into an existing cc-task.",
            "- If no-op, senior lane records the rationale in this task before closure.",
            "",
        ]
    )
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)
    return path


def _apply_classification(
    packet: Packet,
    classification: Classification,
    *,
    config: AutoConsumerConfig,
    client: StateMachineClient,
    existing_task_ids: set[str],
) -> AppliedAction:
    if classification.action == "consume" and classification.artefact:
        if not config.dry_run:
            client.consume(packet.path, classification.artefact)
        return AppliedAction(
            packet=str(packet.path),
            action="consume",
            reason=classification.reason,
            artefact=classification.artefact,
            matched_terms=classification.matched_terms,
            score=classification.score,
        )

    if classification.action == "supersede":
        if not config.dry_run:
            client.supersede(packet.path, classification.reason)
        return AppliedAction(
            packet=str(packet.path),
            action="supersede",
            reason=classification.reason,
            matched_terms=classification.matched_terms,
            score=classification.score,
        )

    if classification.action != "create_task" or not classification.task_id:
        raise RuntimeError(f"unknown classification action: {classification.action}")

    task_id = _unique_task_id(classification.task_id, existing_task_ids)
    artefact = f"cc-task/{task_id}"
    if not config.dry_run:
        _write_offered_task(packet, config.vault_root, task_id=task_id)
        existing_task_ids.add(task_id)
        client.consume(
            packet.path,
            artefact,
            note="auto-created offered cc-task for actionable unmatched Jr/Spark packet",
        )
    return AppliedAction(
        packet=str(packet.path),
        action="create_task",
        reason=classification.reason,
        artefact=artefact,
        task_id=task_id,
        matched_terms=classification.matched_terms,
        score=classification.score,
    )


def run_once(
    config: AutoConsumerConfig,
    *,
    client: StateMachineClient | None = None,
    artefacts: Sequence[Artefact] | None = None,
) -> list[AppliedAction]:
    packets = iter_pending_packets(
        config.packet_root,
        older_than_minutes=config.older_than_minutes,
        max_packets=config.max_packets,
    )
    if not packets:
        return []

    runtime_artefacts = list(artefacts) if artefacts is not None else load_runtime_artefacts(config)
    state_client = client or SubprocessStateMachineClient(config.jr_team_bin)
    existing_task_ids = _existing_task_ids(config.vault_root)

    actions: list[AppliedAction] = []
    for packet in packets:
        classification = classify_packet(packet, runtime_artefacts)
        action = _apply_classification(
            packet,
            classification,
            config=config,
            client=state_client,
            existing_task_ids=existing_task_ids,
        )
        actions.append(action)
        if action.action == "create_task":
            runtime_artefacts.append(
                Artefact(
                    kind="cc-task",
                    ref=action.artefact or "",
                    text=" ".join((action.task_id or "", packet.title, packet.body[:1000])),
                    status="offered",
                    assigned_to="unassigned",
                    source_path=config.vault_root / "active" / f"{action.task_id}.md",
                )
            )
    return actions


def _default_config(args: argparse.Namespace) -> AutoConsumerConfig:
    repo_root = Path(args.repo_root).expanduser().resolve()
    jr_root = os.environ.get("HAPAX_GEMINI_JR_ROOT")
    packet_root = Path(
        args.packet_root
        or os.environ.get("HAPAX_GEMINI_JR_PACKET_DIR")
        or os.environ.get("HAPAX_GEMINI_JR_PACKETS")
        or (str(Path(jr_root).expanduser() / "packets") if jr_root else None)
        or DEFAULT_PACKET_ROOT
    ).expanduser()
    vault_root = Path(
        args.vault_root or os.environ.get("HAPAX_CC_TASK_ROOT") or DEFAULT_VAULT_ROOT
    ).expanduser()
    state_root = Path(
        args.state_root
        or os.environ.get("HAPAX_JR_SPARK_AUTO_CONSUMER_STATE_ROOT")
        or DEFAULT_STATE_ROOT
    ).expanduser()
    jr_team_bin = Path(args.jr_team_bin or repo_root / "scripts" / "hapax-gemini-jr-team")
    return AutoConsumerConfig(
        packet_root=packet_root,
        vault_root=vault_root,
        repo_root=repo_root,
        jr_team_bin=jr_team_bin,
        state_root=state_root,
        max_packets=args.max_packets,
        older_than_minutes=args.older_than_minutes,
        enable_gh=not args.no_gh,
        gh_cache_ttl_seconds=args.gh_cache_ttl_seconds,
        git_log_limit=args.git_log_limit,
        dry_run=args.dry_run,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auto-consume ready Jr/Spark packets into senior-owned artefacts."
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Repo root for git-log artefact matching.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run one auto-consumption pass.")
    run.add_argument("--packet-root", default=None)
    run.add_argument("--vault-root", default=None)
    run.add_argument("--state-root", default=None)
    run.add_argument("--jr-team-bin", default=None)
    run.add_argument("--max-packets", type=int, default=25)
    run.add_argument("--older-than-minutes", type=int, default=0)
    run.add_argument("--no-gh", action="store_true", help="Skip gh PR matching.")
    run.add_argument("--gh-cache-ttl-seconds", type=int, default=300)
    run.add_argument("--git-log-limit", type=int, default=200)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--json", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        config = _default_config(args)
        actions = run_once(config)
        payload = [
            {
                "packet": action.packet,
                "action": action.action,
                "reason": action.reason,
                "artefact": action.artefact,
                "task_id": action.task_id,
                "matched_terms": list(action.matched_terms),
                "score": action.score,
            }
            for action in actions
        ]
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            if not actions:
                print("(no pending Jr/Spark packets)")
            for action in actions:
                target = action.artefact or action.reason
                print(f"{action.action}: {action.packet} -> {target}")
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2
