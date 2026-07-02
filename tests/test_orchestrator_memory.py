"""Tests for M18 ACT-R tiered memory: WorkingMemory, ShortTermMemory, LongTermMemory."""

from __future__ import annotations

import math
import time

from shared.orchestrator.memory import (
    ACTRMemory,
    LongTermMemory,
    LongTermMemoryEntry,
    ShortTermMemory,
    WorkingMemory,
)

# ---------------------------------------------------------------------------
# FakeRedis stub
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self._store: dict[str, str] = {}
        self._fail = fail

    def set(self, name: str, value: str, ex: int | None = None) -> None:
        if self._fail:
            raise OSError("redis down")
        self._store[name] = value

    def get(self, name: str) -> bytes | None:
        if self._fail:
            raise OSError("redis down")
        v = self._store.get(name)
        return v.encode() if v else None

    def delete(self, *names: str) -> int:
        count = 0
        for n in names:
            if n in self._store:
                del self._store[n]
                count += 1
        return count


# ---------------------------------------------------------------------------
# WorkingMemory tests
# ---------------------------------------------------------------------------


class TestWorkingMemory:
    def test_put_and_get(self) -> None:
        wm = WorkingMemory()
        wm.put("regime", "BULL_TREND")
        assert wm.get("regime") == "BULL_TREND"

    def test_get_missing_returns_none(self) -> None:
        wm = WorkingMemory()
        assert wm.get("nonexistent") is None

    def test_overwrite_existing_key(self) -> None:
        wm = WorkingMemory()
        wm.put("regime", "BULL_TREND")
        wm.put("regime", "BEAR_TREND")
        assert wm.get("regime") == "BEAR_TREND"

    def test_delete_removes_entry(self) -> None:
        wm = WorkingMemory()
        wm.put("key", "value")
        wm.delete("key")
        assert wm.get("key") is None

    def test_delete_nonexistent_is_noop(self) -> None:
        wm = WorkingMemory()
        wm.delete("ghost")  # should not raise

    def test_token_count_empty(self) -> None:
        wm = WorkingMemory()
        assert wm.token_count() == 0

    def test_token_count_positive(self) -> None:
        wm = WorkingMemory()
        wm.put("k", "a" * 40)  # 40 chars → ~10 tokens
        assert wm.token_count() > 0

    def test_eviction_when_over_budget(self) -> None:
        wm = WorkingMemory(max_tokens=10)
        wm.put("old", "a" * 40)  # ~10 tokens
        wm.put("new", "b" * 40)  # ~10 more → triggers eviction of "old"
        assert wm.get("old") is None
        assert wm.get("new") is not None

    def test_keys_preserves_insertion_order(self) -> None:
        wm = WorkingMemory()
        wm.put("a", "1")
        wm.put("b", "2")
        wm.put("c", "3")
        assert wm.keys() == ["a", "b", "c"]

    def test_overwrite_refreshes_order(self) -> None:
        wm = WorkingMemory()
        wm.put("a", "1")
        wm.put("b", "2")
        wm.put("a", "updated")  # refresh a → moves to end
        assert wm.keys()[-1] == "a"

    def test_no_eviction_under_budget(self) -> None:
        wm = WorkingMemory(max_tokens=1000)
        wm.put("x", "short")
        wm.put("y", "also short")
        assert wm.get("x") is not None
        assert wm.get("y") is not None


# ---------------------------------------------------------------------------
# ShortTermMemory tests
# ---------------------------------------------------------------------------


class TestShortTermMemory:
    def test_put_get_in_memory_fallback(self) -> None:
        stm = ShortTermMemory(redis_client=None)
        stm.put("key", "value")
        assert stm.get("key") == "value"

    def test_get_missing_returns_none(self) -> None:
        stm = ShortTermMemory(redis_client=None)
        assert stm.get("missing") is None

    def test_delete_in_memory(self) -> None:
        stm = ShortTermMemory(redis_client=None)
        stm.put("x", "y")
        stm.delete("x")
        assert stm.get("x") is None

    def test_redis_path_put_get(self) -> None:
        r = _FakeRedis()
        stm = ShortTermMemory(redis_client=r)
        stm.put("signal", "RELIANCE LONG")
        assert stm.get("signal") == "RELIANCE LONG"

    def test_redis_path_delete(self) -> None:
        r = _FakeRedis()
        stm = ShortTermMemory(redis_client=r)
        stm.put("key", "val")
        stm.delete("key")
        assert stm.get("key") is None

    def test_redis_failure_falls_back_to_memory_on_put(self) -> None:
        r = _FakeRedis(fail=True)
        stm = ShortTermMemory(redis_client=r)
        stm.put("key", "fallback_value")  # Redis put fails → in-memory
        # Direct get on the failing redis won't work; test in-memory store
        assert stm._memory.get("key") == "fallback_value"

    def test_redis_failure_on_get_falls_back_to_none(self) -> None:
        r = _FakeRedis(fail=True)
        stm = ShortTermMemory(redis_client=r)
        assert stm.get("key") is None  # fails gracefully


# ---------------------------------------------------------------------------
# LongTermMemoryEntry tests
# ---------------------------------------------------------------------------


class TestLongTermMemoryEntry:
    def test_no_retrievals_returns_neg_inf(self) -> None:
        e = LongTermMemoryEntry("k", "content")
        assert e.activation_score() == float("-inf")

    def test_activation_formula(self) -> None:
        now_s = time.time()
        elapsed = 100.0
        e = LongTermMemoryEntry("k", "c", retrieved_at_seconds=[now_s - elapsed])
        expected = math.log(elapsed ** (-0.5))
        assert abs(e.activation_score(now_s=now_s) - expected) < 1e-9

    def test_two_retrievals_sum(self) -> None:
        now_s = 1000.0
        e = LongTermMemoryEntry("k", "c", retrieved_at_seconds=[900.0, 800.0])
        t1, t2 = 100.0, 200.0
        expected = math.log(t1 ** (-0.5) + t2 ** (-0.5))
        assert abs(e.activation_score(now_s=now_s) - expected) < 1e-9

    def test_record_retrieval_appends(self) -> None:
        e = LongTermMemoryEntry("k", "c")
        now_s = time.time()
        e.record_retrieval(now_s=now_s)
        assert len(e.retrieved_at_seconds) == 1
        assert e.retrieved_at_seconds[0] == now_s

    def test_record_retrieval_defaults_to_wall_time(self) -> None:
        e = LongTermMemoryEntry("k", "c")
        before = time.time()
        e.record_retrieval()
        after = time.time()
        assert before <= e.retrieved_at_seconds[0] <= after

    def test_recent_retrieval_higher_score(self) -> None:
        now_s = 1000.0
        e_recent = LongTermMemoryEntry("r", "c", retrieved_at_seconds=[999.0])  # 1s ago
        e_old = LongTermMemoryEntry("o", "c", retrieved_at_seconds=[100.0])  # 900s ago
        assert e_recent.activation_score(now_s) > e_old.activation_score(now_s)


# ---------------------------------------------------------------------------
# LongTermMemory tests
# ---------------------------------------------------------------------------


class TestLongTermMemory:
    def test_store_and_retrieve(self) -> None:
        ltm = LongTermMemory()
        ltm.store("s001", "EMA crossover")
        entry = ltm.retrieve("s001")
        assert entry is not None
        assert entry.content == "EMA crossover"

    def test_retrieve_missing_returns_none(self) -> None:
        ltm = LongTermMemory()
        assert ltm.retrieve("ghost") is None

    def test_retrieve_records_access_by_default(self) -> None:
        ltm = LongTermMemory()
        ltm.store("s002", "ORB breakout")
        ltm.retrieve("s002")
        ltm.retrieve("s002")
        entry = ltm.retrieve("s002", record_access=False)
        assert entry is not None
        assert len(entry.retrieved_at_seconds) == 2

    def test_retrieve_no_record_access(self) -> None:
        ltm = LongTermMemory()
        ltm.store("s003", "content")
        ltm.retrieve("s003", record_access=False)
        entry = ltm.retrieve("s003", record_access=False)
        assert entry is not None
        assert len(entry.retrieved_at_seconds) == 0

    def test_retrieve_top_k_ordering(self) -> None:
        now_s = time.time()
        ltm = LongTermMemory()
        ltm.store("old", "old")
        ltm._memory["old"].retrieved_at_seconds = [now_s - 86400]
        ltm.store("fresh", "fresh")
        ltm._memory["fresh"].retrieved_at_seconds = [now_s - 1]
        top = ltm.retrieve_top_k(top_k=1, now_s=now_s)
        assert len(top) == 1
        assert top[0].key == "fresh"

    def test_retrieve_top_k_empty(self) -> None:
        ltm = LongTermMemory()
        assert ltm.retrieve_top_k() == []

    def test_retrieve_top_k_respects_k(self) -> None:
        now_s = time.time()
        ltm = LongTermMemory()
        for i in range(5):
            ltm.store(f"e{i}", f"content {i}")
            ltm._memory[f"e{i}"].retrieved_at_seconds = [now_s - (i + 1)]
        top = ltm.retrieve_top_k(top_k=3, now_s=now_s)
        assert len(top) == 3

    def test_score_nightly_returns_dict(self) -> None:
        ltm = LongTermMemory()
        ltm.store("a", "content a")
        ltm.store("b", "content b")
        scores = ltm.score_nightly()
        assert "a" in scores and "b" in scores

    def test_store_overwrites_content(self) -> None:
        ltm = LongTermMemory()
        ltm.store("k", "original")
        ltm.store("k", "updated")
        entry = ltm.retrieve("k", record_access=False)
        assert entry is not None
        assert entry.content == "updated"


# ---------------------------------------------------------------------------
# ACTRMemory facade tests
# ---------------------------------------------------------------------------


class TestACTRMemory:
    def test_working_tier_remember_recall(self) -> None:
        mem = ACTRMemory()
        mem.remember("last_signal", "LONG RELIANCE", tier="working")
        assert mem.recall("last_signal", tier="working") == "LONG RELIANCE"

    def test_short_term_tier_remember_recall(self) -> None:
        mem = ACTRMemory()
        mem.remember("anomaly", "absorption detected", tier="short_term")
        assert mem.recall("anomaly", tier="short_term") == "absorption detected"

    def test_long_term_tier_remember_recall(self) -> None:
        mem = ACTRMemory()
        mem.remember("setup_ema", "EMA+RSI pattern", tier="long_term")
        assert mem.recall("setup_ema", tier="long_term") == "EMA+RSI pattern"

    def test_default_tier_is_working(self) -> None:
        mem = ACTRMemory()
        mem.remember("x", "hello")
        assert mem.recall("x") == "hello"

    def test_recall_missing_returns_none(self) -> None:
        mem = ACTRMemory()
        assert mem.recall("nonexistent", tier="working") is None

    def test_tier_isolation(self) -> None:
        mem = ACTRMemory()
        mem.remember("key", "working_value", tier="working")
        mem.remember("key", "short_term_value", tier="short_term")
        assert mem.recall("key", tier="working") == "working_value"
        assert mem.recall("key", tier="short_term") == "short_term_value"

    def test_redis_backed_short_term(self) -> None:
        r = _FakeRedis()
        mem = ACTRMemory(redis_client=r)
        mem.remember("order_flow", "institutional buy", tier="short_term")
        assert mem.recall("order_flow", tier="short_term") == "institutional buy"
