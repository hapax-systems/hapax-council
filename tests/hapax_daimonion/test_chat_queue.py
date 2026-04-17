"""Tests for LRR Phase 9 §3.5 — async-first chat queue."""

from __future__ import annotations

import threading

import pytest


def _msg(text: str, ts: float = 0.0, author_id: str = ""):
    from agents.hapax_daimonion.chat_queue import QueuedMessage

    return QueuedMessage(text=text, ts=ts, author_id=author_id)


class TestChatQueueBasic:
    def test_default_max_size_20(self):
        from agents.hapax_daimonion.chat_queue import DEFAULT_MAX_SIZE, ChatQueue

        q = ChatQueue()
        assert q.max_size == DEFAULT_MAX_SIZE == 20

    def test_positive_only_max_size(self):
        from agents.hapax_daimonion.chat_queue import ChatQueue

        with pytest.raises(ValueError):
            ChatQueue(max_size=0)
        with pytest.raises(ValueError):
            ChatQueue(max_size=-1)

    def test_empty_initial_state(self):
        from agents.hapax_daimonion.chat_queue import ChatQueue

        q = ChatQueue()
        assert len(q) == 0
        assert q.peek_oldest() is None
        assert q.peek_newest() is None
        assert q.snapshot() == []
        assert q.total_seen == 0

    def test_push_and_peek(self):
        from agents.hapax_daimonion.chat_queue import ChatQueue

        q = ChatQueue()
        q.push(_msg("first", 1.0))
        q.push(_msg("second", 2.0))

        assert len(q) == 2
        assert q.peek_oldest().text == "first"
        assert q.peek_newest().text == "second"


class TestFifoEvictionAt20:
    def test_evicts_oldest_past_max_size(self):
        from agents.hapax_daimonion.chat_queue import ChatQueue

        q = ChatQueue(max_size=3)
        q.push(_msg("m1"))
        q.push(_msg("m2"))
        q.push(_msg("m3"))
        q.push(_msg("m4"))  # evicts m1

        snapshot = q.snapshot()
        assert [m.text for m in snapshot] == ["m2", "m3", "m4"]
        assert len(q) == 3
        # Lifetime counter reflects all 4 pushes
        assert q.total_seen == 4


class TestDrain:
    def test_drain_returns_and_clears(self):
        from agents.hapax_daimonion.chat_queue import ChatQueue

        q = ChatQueue()
        q.push(_msg("a"))
        q.push(_msg("b"))

        drained = q.drain()
        assert [m.text for m in drained] == ["a", "b"]
        assert len(q) == 0

    def test_drain_empty_returns_empty_list(self):
        from agents.hapax_daimonion.chat_queue import ChatQueue

        assert ChatQueue().drain() == []

    def test_snapshot_does_not_drain(self):
        from agents.hapax_daimonion.chat_queue import ChatQueue

        q = ChatQueue()
        q.push(_msg("x"))
        q.snapshot()
        q.snapshot()
        assert len(q) == 1


class TestThreadSafety:
    def test_concurrent_push_all_recorded(self):
        from agents.hapax_daimonion.chat_queue import ChatQueue

        q = ChatQueue(max_size=500)
        n_threads = 5
        per_thread = 100

        def push_many(start: int):
            for i in range(per_thread):
                q.push(_msg(f"m{start}-{i}"))

        threads = [threading.Thread(target=push_many, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert q.total_seen == n_threads * per_thread
        assert len(q) == n_threads * per_thread

    def test_push_during_drain_is_safe(self):
        from agents.hapax_daimonion.chat_queue import ChatQueue

        q = ChatQueue(max_size=1000)
        for i in range(500):
            q.push(_msg(f"pre-{i}"))

        drain_result: list = []
        done = threading.Event()

        def do_drain():
            drain_result.extend(q.drain())
            done.set()

        def continue_pushing():
            for i in range(500):
                q.push(_msg(f"post-{i}"))

        t1 = threading.Thread(target=do_drain)
        t2 = threading.Thread(target=continue_pushing)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Either: the drain caught all 500 pre-messages and none of the
        # post-messages (fully interleaved), OR it caught some post-messages
        # too (partially interleaved). Never: drain raises / leaves the
        # queue in an inconsistent state.
        assert done.is_set()
        assert len(drain_result) >= 500  # at minimum the 500 pre-messages
        # All remaining messages in the queue must be "post-*" (pre have
        # all been drained).
        for m in q.snapshot():
            assert m.text.startswith("post-"), f"leaked pre-message in queue: {m.text!r}"
