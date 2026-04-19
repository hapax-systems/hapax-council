#!/usr/bin/env python3
"""chat-monitor.py — YouTube Live chat structural analysis for Legomena Live.

Reads chat via chat-downloader, computes structural metrics (no sentiment,
no quality judgment), periodically batches to LLM for deeper analysis.
Feeds the token ledger to drive the token pole.

Metrics (all structural, none judgmental):
  - Unique participants per window
  - Response chain depth (thread detection via embedding similarity)
  - Lexical diversity (MATTR)
  - Novel bigram rate (information density)
  - Conversation rhythm (burst detection)
  - Batch LLM structural observations (every 120s)

No individual message is ever scored as good or bad.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("chat-monitor")

# --- Config ---
POLL_INTERVAL = 2  # seconds between chat reads
BATCH_INTERVAL = 120  # seconds between LLM batch analysis
WINDOW_SIZE = 100  # messages in sliding window
EMBED_WINDOW = 20  # recent messages for embedding similarity
THREAD_SIMILARITY_THRESHOLD = 0.6

LITELLM_URL = "http://localhost:4000/v1/chat/completions"
LITELLM_KEY = ""

SHM_DIR = Path("/dev/shm/hapax-compositor")
CHAT_STATE_FILE = SHM_DIR / "chat-state.json"


def _get_litellm_key() -> str:
    global LITELLM_KEY
    if not LITELLM_KEY:
        try:
            result = subprocess.run(
                ["pass", "show", "litellm/master-key"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            LITELLM_KEY = result.stdout.strip()
        except Exception:
            pass
    return LITELLM_KEY


# --- Simple tokenizer for chat text ---
_EMOJI_RE = re.compile(
    "[\U0001f600-\U0001f64f\U0001f300-\U0001f5ff\U0001f680-\U0001f6ff"
    "\U0001f1e0-\U0001f1ff\U00002702-\U000027b0\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff\U00002600-\U000026ff\U0000fe0f]+",
    flags=re.UNICODE,
)


def tokenize_chat(text: str) -> list[str]:
    """Simple whitespace tokenizer for chat. Strips emoji, lowercases, normalizes."""
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"(.)\1{3,}", r"\1\1", text)  # collapse repeated chars (lmaooooo → lmao)
    text = text.lower().strip()
    return [w for w in text.split() if len(w) > 1]


def compute_mattr(tokens: list[str], window: int = 50) -> float:
    """Moving-Average Type-Token Ratio — length-independent lexical diversity."""
    if len(tokens) < window:
        return len(set(tokens)) / max(len(tokens), 1)
    ratios = []
    for i in range(len(tokens) - window + 1):
        w = tokens[i : i + window]
        ratios.append(len(set(w)) / window)
    return sum(ratios) / len(ratios) if ratios else 0.0


def compute_hapax_ratio(tokens: list[str]) -> float:
    """Ratio of words appearing exactly once (hapax legomena)."""
    if not tokens:
        return 0.0
    from collections import Counter

    counts = Counter(tokens)
    hapax = sum(1 for c in counts.values() if c == 1)
    return hapax / len(counts) if counts else 0.0


def compute_novel_bigrams(tokens: list[str], seen_bigrams: set) -> float:
    """Rate of bigrams not seen in the existing window."""
    if len(tokens) < 2:
        return 0.0
    bigrams = [(tokens[i], tokens[i + 1]) for i in range(len(tokens) - 1)]
    novel = sum(1 for b in bigrams if b not in seen_bigrams)
    rate = novel / len(bigrams) if bigrams else 0.0
    seen_bigrams.update(bigrams)
    return rate


def get_embedding(text: str) -> list[float] | None:
    """Get embedding from nomic-embed via Ollama on localhost."""
    try:
        body = json.dumps({"model": "nomic-embed-text", "prompt": text}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/embeddings",
            body,
            {"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=2)
        data = json.loads(resp.read())
        return data.get("embedding")
    except Exception:
        return None


def _batch_embedder(texts: list[str]) -> list[list[float]]:
    """Embed a batch of messages via nomic-embed for the structural analyzer.

    Zero-vector fallback when ``get_embedding`` fails on any single text so
    a single network hiccup doesn't nuke the whole batch.
    """
    out: list[list[float]] = []
    for text in texts:
        vec = get_embedding(text) if text else None
        out.append(vec if vec else [0.0])
    return out


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


class ChatMonitor:
    """Monitors YouTube Live chat and computes structural metrics."""

    def __init__(self, video_id: str) -> None:
        self.video_id = video_id
        self.messages: deque = deque(maxlen=WINDOW_SIZE)
        self.all_tokens: list[str] = []
        self.seen_bigrams: set = set()
        self.embeddings: deque = deque(maxlen=EMBED_WINDOW)
        self.authors: set = set()
        self.author_window: deque = deque(maxlen=WINDOW_SIZE)
        self._last_batch = 0.0
        self._running = False
        # A5: chat-reactive preset switching. Optional; logs but does not
        # raise if the compositor package isn't importable from the chat
        # monitor's sys.path (unit-tested via direct import).
        try:
            from agents.studio_compositor.chat_reactor import PresetReactor

            self._preset_reactor = PresetReactor()
            log.info("PresetReactor enabled — chat keyword → preset switch")
        except Exception:
            self._preset_reactor = None
            log.debug("PresetReactor unavailable", exc_info=True)

        # LRR Phase 9 §3.5: chat queue producer. Drain side is in the
        # daimonion during `chat` activity; this process only pushes.
        try:
            from agents.hapax_daimonion.chat_queue import ChatQueue

            self._chat_queue = ChatQueue()
            log.info("ChatQueue enabled — async-review FIFO-20 producer")
        except Exception:
            self._chat_queue = None
            log.debug("ChatQueue unavailable", exc_info=True)

        # Task #146: chat-contribution ledger powers the token-pole
        # reward mechanic (emoji cascade + #N FROM {count} marker). The
        # ledger is privacy-first (hashed authors only); cascades are
        # published to the token-pole ledger JSON so the compositor
        # source can trigger its EmojiSpewEffect without a direct import
        # of this script's ChatMonitor.
        try:
            from agents.studio_compositor.chat_contribution import (
                ChatContributionLedger,
            )

            self._contribution_ledger = ChatContributionLedger()
            log.info("ChatContributionLedger enabled (task #146)")
        except Exception:
            self._contribution_ledger = None
            log.debug("ChatContributionLedger unavailable", exc_info=True)

    def start(self) -> None:
        """Start monitoring chat."""
        self._running = True
        log.info("Chat monitor starting for video %s", self.video_id)

        # Start batch analysis thread
        threading.Thread(target=self._batch_loop, daemon=True).start()

        # Main chat reading loop
        try:
            from chat_downloader import ChatDownloader

            downloader = ChatDownloader()
            chat = downloader.get_chat(
                f"https://www.youtube.com/watch?v={self.video_id}",
                output=None,
            )
            for message in chat:
                if not self._running:
                    break
                self._process_message(message)
        except KeyboardInterrupt:
            self._running = False
        except Exception:
            log.exception("Chat downloader error")
            self._running = False

    def _process_message(self, msg: dict) -> None:
        """Process a single chat message — structural metrics only."""
        text = msg.get("message", "")
        author = msg.get("author", {}).get("name", "")
        author_id = msg.get("author", {}).get("id", "")
        timestamp = msg.get("timestamp", time.time())
        msg_type = msg.get("message_type", "text_message")
        amount = msg.get("money", {}).get("amount", 0) if msg.get("money") else 0

        # Record message
        self.messages.append(
            {
                "text": text,
                "author": author,
                "author_id": author_id,
                "timestamp": timestamp,
                "type": msg_type,
                "amount": amount,
            }
        )

        self.authors.add(author_id)
        self.author_window.append(author_id)

        # Tokenize and accumulate
        tokens = tokenize_chat(text)
        self.all_tokens.extend(tokens)
        if len(self.all_tokens) > 5000:
            self.all_tokens = self.all_tokens[-2000:]

        # Compute per-message novelty
        novel_rate = compute_novel_bigrams(tokens, self.seen_bigrams)

        # Embedding for thread detection (skip if too short)
        if len(text) > 10:
            emb = get_embedding(text)
            if emb:
                # Check thread similarity
                thread_hits = 0
                for prev_emb in self.embeddings:
                    if cosine_similarity(emb, prev_emb) > THREAD_SIMILARITY_THRESHOLD:
                        thread_hits += 1
                self.embeddings.append(emb)

        # Superchat/membership boost — recorded as direct token pole contribution
        if amount > 0:
            from token_ledger import record_spend

            # Scale superchat to token equivalent (rough: $1 = 500 tokens of "gratitude")
            token_equiv = int(amount * 500)
            record_spend("superchat", token_equiv, 0, cost=0.0)
            log.info("Superchat: %s from %s (token equiv: %d)", amount, author, token_equiv)

        if msg_type in ("membership_item", "paid_message"):
            from token_ledger import record_spend

            record_spend("membership", 1000, 0, cost=0.0)

        # LRR Phase 9 §3.5: async-review chat queue producer. Drained by
        # the daimonion director-loop during `chat` activity via the
        # Continuous-Loop §3.3 file IPC (snapshot_to_file / drain_from_file).
        # Push is best-effort; queue overflow evicts oldest via deque
        # semantics. Snapshot file is updated on every push so the
        # daimonion always reads the current FIFO-20.
        if self._chat_queue is not None and text:
            try:
                from agents.hapax_daimonion.chat_queue import (
                    QueuedMessage,
                    snapshot_to_file,
                )

                self._chat_queue.push(
                    QueuedMessage(text=text, ts=float(timestamp), author_id=author_id)
                )
                snapshot_to_file(self._chat_queue)
            except Exception:
                log.debug("ChatQueue push/snapshot failed", exc_info=True)

        # A5: chat-reactive preset switching (no per-author state retained)
        if self._preset_reactor is not None and text:
            try:
                self._preset_reactor.process_message(text)
            except Exception:
                log.debug("PresetReactor failed on message", exc_info=True)

        # Task #146: chat-contribution ledger. Feed each message, then
        # check rising-edge threshold to trigger the token-pole cascade
        # via the ledger JSON. Author name never leaves the ledger; it's
        # hashed + salted inside record_chat.
        if self._contribution_ledger is not None and text:
            try:
                now_ts = float(timestamp) if timestamp else time.time()
                self._contribution_ledger.record_chat(
                    author_name=author or author_id,
                    message_length=len(text),
                    ts=now_ts,
                )
                snapshot = self._contribution_ledger.cross_reward_threshold(now=now_ts)
                if snapshot is not None:
                    self._publish_contribution_cascade(snapshot)
            except Exception:
                log.debug("contribution ledger failed", exc_info=True)

        # Update viewer count
        unique_recent = len(set(self.author_window))
        from token_ledger import set_active_viewers

        set_active_viewers(unique_recent)

        # Write chat state for overlay
        self._write_state(unique_recent, novel_rate)

    def _publish_contribution_cascade(
        self,
        snapshot,  # ContributionSnapshot
    ) -> None:
        """Hand the cascade off to the token-pole ledger.

        Writes an ``explosions`` bump and a ``contribution_cascade``
        payload to ``/dev/shm/hapax-compositor/token-ledger.json`` so
        the token-pole CairoSource picks up the edge on its next ledger
        read and triggers its EmojiSpewEffect. The contributor count is
        the only identity-adjacent number; no names, no raw handles.
        """
        try:
            ledger_path = SHM_DIR / "token-ledger.json"
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            existing: dict = {}
            if ledger_path.exists():
                try:
                    existing = json.loads(ledger_path.read_text())
                except Exception:
                    existing = {}
            existing["explosions"] = int(existing.get("explosions", 0)) + 1
            existing["contribution_cascade"] = {
                "explosion_number": snapshot.explosion_number,
                "contributor_count": snapshot.unique_contributor_count,
                "ts": time.time(),
            }
            tmp = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
            tmp.write_text(json.dumps(existing))
            os.replace(tmp, ledger_path)
            log.info(
                "token-pole cascade #%d published (contributors=%d)",
                snapshot.explosion_number,
                snapshot.unique_contributor_count,
            )
        except Exception:
            log.debug("publish contribution cascade failed", exc_info=True)

    def _write_state(self, unique_authors: int, novel_rate: float) -> None:
        """Write current chat metrics to shm."""
        # Lexical diversity of the full window
        mattr = compute_mattr(self.all_tokens[-500:])
        hapax = compute_hapax_ratio(self.all_tokens[-200:])

        state = {
            "unique_authors": unique_authors,
            "total_messages": len(self.messages),
            "mattr": round(mattr, 3),
            "hapax_ratio": round(hapax, 3),
            "novel_rate": round(novel_rate, 3),
            "updated": time.time(),
        }
        try:
            SHM_DIR.mkdir(parents=True, exist_ok=True)
            CHAT_STATE_FILE.write_text(json.dumps(state))
            # Write recent messages for reactor (last 5, author + text only)
            recent = [{"author": m["author"], "text": m["text"]} for m in list(self.messages)[-5:]]
            (SHM_DIR / "chat-recent.json").write_text(json.dumps(recent))
        except OSError:
            pass

        from token_ledger import record_chat_metrics

        record_chat_metrics(unique_authors, mattr, novel_rate)

    def _batch_loop(self) -> None:
        """Periodic LLM batch analysis of chat structure."""
        while self._running:
            time.sleep(BATCH_INTERVAL)
            if len(self.messages) < 5:
                continue
            self._run_batch_analysis()
            # LRR Phase 9 §3.1: publish compact structural signals to
            # /dev/shm/hapax-chat-signals.json on the same cadence so
            # stimmung / director-loop / attention-bid downstream readers
            # can consume without re-running embeddings.
            try:
                self._publish_structural_signals()
            except Exception:
                log.debug("structural-signals publish failed", exc_info=True)

    def _publish_structural_signals(self) -> None:
        """Compute the Phase 9 §3.1 structural signals and publish them."""
        try:
            from agents.chat_monitor.sink import publish
            from agents.chat_monitor.structural_analyzer import ChatMessage, analyze
        except ImportError:
            # Module not yet on sys.path (dev worktree mismatch) — silently skip.
            log.debug("agents.chat_monitor not importable; skipping signals publish")
            return

        window = list(self.messages)[-50:]
        if not window:
            return

        chat_messages = [
            ChatMessage(
                author_id=m.get("author_id") or "",
                text=m.get("text") or "",
                ts=float(m.get("timestamp") or 0.0),
            )
            for m in window
        ]

        signals = analyze(chat_messages, embedder=_batch_embedder)
        publish(signals)

    def _run_batch_analysis(self) -> None:
        """Send recent chat window to LLM for structural analysis."""
        key = _get_litellm_key()
        if not key:
            return

        # Format recent messages (anonymized — no names)
        recent = list(self.messages)[-50:]
        chat_text = "\n".join(f"[{m['type']}] {m['text']}" for m in recent if m["text"])

        body = json.dumps(
            {
                "model": "fast",
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Analyze the STRUCTURE of this live chat excerpt. "
                            "Do NOT judge quality or sentiment. Describe:\n"
                            "1. How many distinct conversation threads are active?\n"
                            "2. Are participants building on each other's ideas or talking past each other?\n"
                            "3. Is the conversation deepening (follow-ups, elaboration) or surface-level?\n"
                            "4. Describe the rhythm: sustained dialogue, sporadic bursts, or monologue?\n\n"
                            f"Chat:\n{chat_text}\n\n"
                            'Return JSON: {"thread_count": int, "threading_ratio": float, '
                            '"depth_signal": float, "novelty_rate": float, '
                            '"rhythm": string}'
                        ),
                    }
                ],
            }
        ).encode()

        try:
            req = urllib.request.Request(
                LITELLM_URL,
                body,
                {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            )
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read())

            # Record the token spend — THIS drives the pole
            usage = data.get("usage", {})
            prompt_tok = usage.get("prompt_tokens", 0)
            completion_tok = usage.get("completion_tokens", 0)

            from token_ledger import record_spend

            record_spend("chat_analysis", prompt_tok, completion_tok)

            content = data["choices"][0]["message"]["content"]
            log.info("Batch analysis (%d+%d tokens): %s", prompt_tok, completion_tok, content[:200])

        except Exception:
            log.warning("Batch analysis failed", exc_info=True)


def _read_video_id() -> str:
    """Resolve a YouTube video ID from env var or shm file. Returns empty
    string when neither source has it."""
    env_id = os.environ.get("YOUTUBE_VIDEO_ID", "").strip()
    if env_id:
        return env_id
    vid_path = SHM_DIR / "youtube-video-id.txt"
    if vid_path.exists():
        return vid_path.read_text().strip()
    return ""


# LRR Phase 0 item 1: chat-monitor must NOT crash when no video ID is set.
# The service should sit idle in a polling loop until an ID appears, then
# start monitoring. Crash-loop behavior (sys.exit(1)) caused 660+ restart
# counter and journal spam between 2026-04-13 and 2026-04-14. Fix shape =
# wait-loop with a 30 s poll cadence + 5 min log throttle so the journal
# doesn't fill up while idle.
_WAIT_POLL_INTERVAL_S = 30.0
_WAIT_LOG_INTERVAL_S = 300.0


def _wait_for_video_id() -> str:
    """Block until a video ID becomes available. Returns the resolved ID.

    Polls every ``_WAIT_POLL_INTERVAL_S`` seconds. Logs a warning every
    ``_WAIT_LOG_INTERVAL_S`` seconds (not every poll) so the journal stays
    quiet while the service is idle. Exits cleanly on SIGTERM via the
    standard interpreter shutdown path; the sleep is short enough that
    systemd's stop signal is honored within the poll window.
    """
    log.info("chat-monitor: starting; waiting for video ID")
    # Initialize to -inf so the first warning fires immediately, then the
    # throttle takes over for subsequent polls within _WAIT_LOG_INTERVAL_S.
    last_log_at = float("-inf")
    while True:
        video_id = _read_video_id()
        if video_id:
            log.info("chat-monitor: video ID resolved: %s", video_id)
            return video_id
        now = time.monotonic()
        if now - last_log_at >= _WAIT_LOG_INTERVAL_S:
            log.warning(
                "chat-monitor: no video ID. Set YOUTUBE_VIDEO_ID or write to %s. "
                "Polling every %.0fs; this warning repeats every %.0fs.",
                SHM_DIR / "youtube-video-id.txt",
                _WAIT_POLL_INTERVAL_S,
                _WAIT_LOG_INTERVAL_S,
            )
            last_log_at = now
        time.sleep(_WAIT_POLL_INTERVAL_S)


def main() -> None:
    video_id = _read_video_id()
    if not video_id:
        video_id = _wait_for_video_id()

    monitor = ChatMonitor(video_id)
    monitor.start()


if __name__ == "__main__":
    main()
