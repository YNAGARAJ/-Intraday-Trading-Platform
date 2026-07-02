"""M18 VERIFY harness — 20 scenarios for the Agent Orchestrator.

Run:
    python -m shared.orchestrator
"""

from __future__ import annotations

import math
import time

import structlog

from shared.orchestrator.graph import OrchestratorGraph
from shared.orchestrator.memory import (
    ACTRMemory,
    LongTermMemory,
    LongTermMemoryEntry,
    ShortTermMemory,
    WorkingMemory,
)
from shared.orchestrator.state import (
    make_initial_state,
    state_from_json,
    state_to_json,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check(label: str, condition: bool) -> bool:
    if condition:
        logger.info("VERIFY_PASS", scenario=label)
    else:
        logger.error("VERIFY_FAIL", scenario=label)
    return condition


# ---------------------------------------------------------------------------
# Fake Redis stubs
# ---------------------------------------------------------------------------


class _FakeRedis:
    """In-memory Redis stub for VERIFY scenarios."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = {}

    def set(self, name: str, value: str, ex: int | None = None) -> None:
        self._store[name] = value

    def get(self, name: str) -> bytes | None:
        v = self._store.get(name)
        return v.encode() if v else None

    def delete(self, *names: str) -> int:
        count = 0
        for n in names:
            if n in self._store:
                del self._store[n]
                count += 1
        return count

    def xadd(
        self,
        name: str,
        fields: dict[str, str],
        id: str = "*",
        maxlen: int | None = None,
    ) -> bytes:
        entry_id = f"{int(time.time() * 1000)}-0"
        self._streams.setdefault(name, []).append((entry_id, fields))
        return entry_id.encode()

    def xrevrange(
        self,
        name: str,
        max: str = "+",
        min: str = "-",
        count: int | None = None,
    ) -> list[tuple[bytes, dict[bytes, bytes]]]:
        entries = self._streams.get(name, [])
        result = [
            (eid.encode(), {k.encode(): v.encode() for k, v in fields.items()})
            for eid, fields in reversed(entries)
        ]
        if count is not None:
            result = result[:count]
        return result


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def run_verify() -> bool:
    results: list[bool] = []

    # --- S01: make_initial_state returns required fields ---
    state = make_initial_state("2026-07-02")
    results.append(
        _check(
            "S01: make_initial_state populates all required fields",
            state["market_date"] == "2026-07-02"
            and state["kill_switch_active"] is False
            and state["pending_hitl_approval"] is None
            and state["signals_today"] == 0,
        )
    )

    # --- S02: state_to_json / state_from_json roundtrip ---
    state2 = make_initial_state("2026-07-02")
    state2["signals_today"] = 7
    state2["market_regime"] = "BULL_TREND"
    raw = state_to_json(state2)
    restored = state_from_json(raw)
    results.append(
        _check(
            "S02: state serialisation roundtrip preserves all fields",
            restored["signals_today"] == 7
            and restored["market_regime"] == "BULL_TREND",
        )
    )

    # --- S03: WorkingMemory put/get ---
    wm = WorkingMemory(max_tokens=500)
    wm.put("snapshot", "RELIANCE: 2500, INFY: 1800")
    results.append(
        _check(
            "S03: WorkingMemory.get() returns stored value",
            wm.get("snapshot") == "RELIANCE: 2500, INFY: 1800",
        )
    )

    # --- S04: WorkingMemory prunes old entries when over budget ---
    wm4 = WorkingMemory(max_tokens=10)
    wm4.put("k1", "a" * 40)  # ~10 tokens
    wm4.put("k2", "b" * 40)  # ~10 tokens → prunes k1
    results.append(
        _check(
            "S04: WorkingMemory evicts oldest entry when over token budget",
            wm4.get("k1") is None and wm4.get("k2") is not None,
        )
    )

    # --- S05: WorkingMemory delete removes entry ---
    wm5 = WorkingMemory()
    wm5.put("regime", "BULL_TREND")
    wm5.delete("regime")
    results.append(
        _check(
            "S05: WorkingMemory.delete() removes the entry",
            wm5.get("regime") is None,
        )
    )

    # --- S06: ShortTermMemory put/get in-memory fallback ---
    stm = ShortTermMemory(redis_client=None)
    stm.put("signal_flow", "RELIANCE LONG")
    results.append(
        _check(
            "S06: ShortTermMemory stores and retrieves in-memory fallback",
            stm.get("signal_flow") == "RELIANCE LONG",
        )
    )

    # --- S07: ShortTermMemory Redis path ---
    redis7 = _FakeRedis()
    stm7 = ShortTermMemory(redis_client=redis7)
    stm7.put("order_flow", "absorption detected")
    results.append(
        _check(
            "S07: ShortTermMemory uses Redis when available",
            stm7.get("order_flow") == "absorption detected",
        )
    )

    # --- S08: ACT-R activation score formula ---
    now_s = time.time()
    entry = LongTermMemoryEntry("test", "content", retrieved_at_seconds=[now_s - 100])
    score = entry.activation_score(now_s=now_s)
    expected = math.log(100 ** (-0.5))
    results.append(
        _check(
            "S08: ACT-R activation score matches ln(Σ t_i^(-0.5))",
            abs(score - expected) < 1e-9,
        )
    )

    # --- S09: ACT-R activation score — no retrievals returns -inf ---
    entry9 = LongTermMemoryEntry("empty", "no retrievals yet")
    results.append(
        _check(
            "S09: ACT-R activation score is -inf when no retrievals",
            entry9.activation_score() == float("-inf"),
        )
    )

    # --- S10: LongTermMemory store/retrieve ---
    ltm = LongTermMemory()
    ltm.store("setup_001", "EMA crossover on RELIANCE with volume surge")
    entry10 = ltm.retrieve("setup_001")
    results.append(
        _check(
            "S10: LongTermMemory stores and retrieves entries",
            entry10 is not None
            and entry10.content == "EMA crossover on RELIANCE with volume surge",
        )
    )

    # --- S11: LongTermMemory retrieve records access history ---
    ltm11 = LongTermMemory()
    ltm11.store("setup_002", "ORB breakout on INFY")
    ltm11.retrieve("setup_002", record_access=True)
    ltm11.retrieve("setup_002", record_access=True)
    e11 = ltm11.retrieve("setup_002", record_access=False)
    results.append(
        _check(
            "S11: LongTermMemory.retrieve() tracks ACT-R access history",
            e11 is not None and len(e11.retrieved_at_seconds) == 2,
        )
    )

    # --- S12: LongTermMemory.retrieve_top_k ranking ---
    ltm12 = LongTermMemory()
    now_s12 = time.time()
    ltm12.store("old", "old memory")
    ltm12._memory["old"].retrieved_at_seconds = [now_s12 - 86400]  # 1 day ago
    ltm12.store("fresh", "fresh memory")
    ltm12._memory["fresh"].retrieved_at_seconds = [now_s12 - 60]  # 1 min ago
    top = ltm12.retrieve_top_k(top_k=1, now_s=now_s12)
    results.append(
        _check(
            "S12: retrieve_top_k returns most recently accessed entry first",
            len(top) == 1 and top[0].key == "fresh",
        )
    )

    # --- S13: ACTRMemory facade remember/recall ---
    mem13 = ACTRMemory()
    mem13.remember("last_signal", "LONG RELIANCE 2500", tier="working")
    mem13.remember("anomaly", "absorption at 2510", tier="short_term")
    mem13.remember("setup_classic", "EMA+RSI pattern", tier="long_term")
    results.append(
        _check(
            "S13: ACTRMemory facade routes to correct tier",
            mem13.recall("last_signal", "working") == "LONG RELIANCE 2500"
            and mem13.recall("anomaly", "short_term") == "absorption at 2510"
            and mem13.recall("setup_classic", "long_term")
            == "EMA+RSI pattern",
        )
    )

    # --- S14: OrchestratorGraph compiles and runs a clean cycle ---
    orch14 = OrchestratorGraph(enable_hitl=False)
    init14 = make_initial_state("2026-07-02")
    result14 = orch14.run_cycle(init14)
    results.append(
        _check(
            "S14: OrchestratorGraph clean cycle returns state without errors",
            result14 is not None and not result14["kill_switch_active"],
        )
    )

    # --- S15: Circuit breaker activates at -2% P&L ---
    orch15 = OrchestratorGraph(enable_hitl=False)
    init15 = make_initial_state("2026-07-02")
    init15["pnl_today_pct"] = -0.025  # −2.5%
    result15 = orch15.run_cycle(init15)
    results.append(
        _check(
            "S15: circuit_breaker_active=True at -2.5% daily P&L",
            result15 is not None and result15["circuit_breaker_active"],
        )
    )

    # --- S16: HIGH_VOL_CHAOS blocks signal consumption ---
    redis16 = _FakeRedis()
    redis16.xadd("signals:generated", {"symbol": "RELIANCE", "exchange": "NSE"})
    orch16 = OrchestratorGraph(redis_client=redis16, enable_hitl=False)
    init16 = make_initial_state("2026-07-02")
    init16["market_regime"] = "HIGH_VOL_CHAOS"
    result16 = orch16.run_cycle(init16)
    results.append(
        _check(
            "S16: HIGH_VOL_CHAOS regime blocks signal consumption (RULE 2)",
            result16 is not None and result16["signals_today"] == 0,
        )
    )

    # --- S17: BULL_TREND regime signal consumed normally ---
    redis17 = _FakeRedis()
    redis17.xadd("signals:generated", {"symbol": "RELIANCE", "exchange": "NSE"})
    redis17.xadd("regime:changes", {"regime": "BULL_TREND", "confidence": "0.85"})
    orch17 = OrchestratorGraph(redis_client=redis17, enable_hitl=False)
    init17 = make_initial_state("2026-07-02")
    result17 = orch17.run_cycle(init17)
    results.append(
        _check(
            "S17: BULL_TREND regime allows signal consumption",
            result17 is not None and result17["signals_today"] == 1,
        )
    )

    # --- S18: Reconciliation block prevents signal on affected symbol ---
    def _is_blocked(symbol: str, exchange: str) -> bool:
        return symbol == "RELIANCE" and exchange == "NSE"

    redis18 = _FakeRedis()
    redis18.xadd("signals:generated", {"symbol": "RELIANCE", "exchange": "NSE"})
    orch18 = OrchestratorGraph(
        redis_client=redis18,
        reconciliation_blocked_fn=_is_blocked,
        enable_hitl=False,
    )
    init18 = make_initial_state("2026-07-02")
    result18 = orch18.run_cycle(init18)
    results.append(
        _check(
            "S18: reconciliation block prevents signal on blocked symbol",
            result18 is not None and result18["signals_today"] == 0,
        )
    )

    # --- S19: HITL interrupt fires for large position (> 5% capital) ---
    orch19 = OrchestratorGraph(starting_capital=100_000.0, enable_hitl=True)
    init19 = make_initial_state("2026-07-02")
    init19["open_positions"] = {
        "RELIANCE": {"quantity": 30, "avg_price": 2500.0}
    }  # 75 000 / 100 000 = 75% — way over 5%
    result19 = orch19.run_cycle(init19)
    # Should be interrupted (returns None)
    checkpoint19 = orch19._app.get_state(orch19._thread_config)
    results.append(
        _check(
            "S19: HITL interrupt fires for position > 5% of capital",
            result19 is None
            and checkpoint19.values.get("pending_hitl_approval") is not None,
        )
    )

    # --- S20: Kill switch preempts pending HITL (RULE 8) ---
    # Graph is still interrupted from S19; trigger kill switch
    orch19.trigger_kill_switch(reason="test_kill")
    final20 = orch19.get_state()
    results.append(
        _check(
            "S20: kill switch preempts pending HITL — pending_hitl_approval cleared",
            final20["kill_switch_active"] is True
            and final20["pending_hitl_approval"] is None,
        )
    )

    total = len(results)
    passed = sum(results)
    logger.info("VERIFY_SUMMARY", passed=passed, total=total)
    return passed == total
