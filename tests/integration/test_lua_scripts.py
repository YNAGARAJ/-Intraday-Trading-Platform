"""Atomicity and correctness tests for the 5 Redis Lua scripts (RULE 3).

Requires a real Redis server -- see tests/integration/conftest.py. Run with, e.g.:

    docker run --rm -d --name trading-test-redis -p 6379:6379 redis:7.2.4-alpine
    pytest tests/integration/test_lua_scripts.py -v
    docker stop trading-test-redis
"""

import threading
from collections.abc import Callable

import redis as redis_lib


def test_sl_linkage_success(
    redis_client: redis_lib.Redis,
    load_lua: Callable[[str], redis_lib.commands.core.Script],
) -> None:
    script = load_lua("sl_linkage.lua")
    redis_client.set("portfolio:margin:available", "10000")

    result = script(keys=["RELIANCE"], args=["order-1", "2000", "2450.50", "STRAT001"])

    assert result == [1, "SUCCESS"]
    assert redis_client.get("portfolio:margin:available") == "8000"
    position = redis_client.hgetall("position:RELIANCE")
    assert position == {
        "order_id": "order-1",
        "sl_price": "2450.50",
        "strategy_id": "STRAT001",
        "status": "OPEN",
    }
    assert redis_client.sismember("portfolio:active_positions", "RELIANCE")


def test_sl_linkage_insufficient_margin_rejected(
    redis_client: redis_lib.Redis,
    load_lua: Callable[[str], redis_lib.commands.core.Script],
) -> None:
    script = load_lua("sl_linkage.lua")
    redis_client.set("portfolio:margin:available", "1000")

    result = script(keys=["RELIANCE"], args=["order-1", "2000", "2450.50", "STRAT001"])

    assert result == [0, "INSUFFICIENT_MARGIN"]
    assert redis_client.get("portfolio:margin:available") == "1000"
    assert not redis_client.exists("position:RELIANCE")
    assert not redis_client.sismember("portfolio:active_positions", "RELIANCE")


def test_sl_linkage_atomic_under_concurrency(
    redis_client: redis_lib.Redis,
    load_lua: Callable[[str], redis_lib.commands.core.Script],
) -> None:
    """RULE 3: 50 concurrent entries racing for margin covering only 10 must never
    overdraft."""
    script = load_lua("sl_linkage.lua")
    redis_client.set("portfolio:margin:available", "10000")
    margin_per_trade = "1000"
    n_threads = 50

    results: list[list[object]] = [None] * n_threads  # type: ignore[list-item]

    def _attempt(i: int) -> None:
        results[i] = script(
            keys=[f"SYM{i}"], args=[f"order-{i}", margin_per_trade, "100.0", "STRAT001"]
        )

    threads = [threading.Thread(target=_attempt, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = sum(1 for r in results if r is not None and r[0] == 1)
    assert successes == 10, "exactly 10 of 50 entries should succeed (10000 / 1000)"
    remaining_margin = int(str(redis_client.get("portfolio:margin:available")))
    assert remaining_margin == 0, "margin must never go negative under concurrency"
    assert redis_client.scard("portfolio:active_positions") == 10


def test_margin_guard_reserves_when_sufficient(
    redis_client: redis_lib.Redis,
    load_lua: Callable[[str], redis_lib.commands.core.Script],
) -> None:
    script = load_lua("margin_guard.lua")
    redis_client.set("portfolio:margin:available", "5000")

    assert script(args=["3000"]) == 1
    assert redis_client.get("portfolio:margin:available") == "2000"


def test_margin_guard_rejects_when_insufficient(
    redis_client: redis_lib.Redis,
    load_lua: Callable[[str], redis_lib.commands.core.Script],
) -> None:
    script = load_lua("margin_guard.lua")
    redis_client.set("portfolio:margin:available", "1000")

    assert script(args=["3000"]) == 0
    assert redis_client.get("portfolio:margin:available") == "1000"


def test_rate_limiter_priority_bypasses_empty_bucket(
    load_lua: Callable[[str], redis_lib.commands.core.Script],
) -> None:
    """is_priority=1 bypasses the throttle even with a fully-drained bucket (RULE 8)."""
    script = load_lua("rate_limiter.lua")

    result = script(keys=["client-1"], args=["1", "10", "0.01", "1000", "1"])

    assert result == 1


def test_rate_limiter_token_bucket_exhausts_and_blocks(
    load_lua: Callable[[str], redis_lib.commands.core.Script],
) -> None:
    script = load_lua("rate_limiter.lua")

    # capacity=3, fill_rate=0 (no refill within this test's time window) -> exactly 3
    # allowed.
    def args_for(t: int) -> list[str]:
        return ["1", "3", "0", str(t), "0"]

    assert script(keys=["client-2"], args=args_for(1000)) == 1
    assert script(keys=["client-2"], args=args_for(1001)) == 1
    assert script(keys=["client-2"], args=args_for(1002)) == 1
    assert script(keys=["client-2"], args=args_for(1003)) == 0


def test_rate_limiter_refills_over_time(
    load_lua: Callable[[str], redis_lib.commands.core.Script],
) -> None:
    script = load_lua("rate_limiter.lua")
    # capacity=1, fill_rate=1 token/ms -> draining then waiting 5ms must refill.
    assert script(keys=["client-3"], args=["1", "1", "1", "1000", "0"]) == 1
    assert script(keys=["client-3"], args=["1", "1", "1", "1000", "0"]) == 0
    assert script(keys=["client-3"], args=["1", "1", "1", "1005", "0"]) == 1


def test_circuit_breaker_triggers_at_or_below_limit(
    redis_client: redis_lib.Redis,
    load_lua: Callable[[str], redis_lib.commands.core.Script],
) -> None:
    script = load_lua("circuit_breaker.lua")

    result = script(args=["-2.5", "-2.0"])

    assert result == 1
    assert redis_client.get("system:status:halted") == "true"
    assert redis_client.get("system:status:reason") == "DAILY_LOSS_LIMIT_VIOLATION"


def test_circuit_breaker_does_not_trigger_above_limit(
    redis_client: redis_lib.Redis,
    load_lua: Callable[[str], redis_lib.commands.core.Script],
) -> None:
    script = load_lua("circuit_breaker.lua")

    result = script(args=["-1.0", "-2.0"])

    assert result == 0
    assert not redis_client.exists("system:status:halted")


def test_position_close_releases_margin_and_removes_position(
    redis_client: redis_lib.Redis,
    load_lua: Callable[[str], redis_lib.commands.core.Script],
) -> None:
    redis_client.set("portfolio:margin:available", "1000")
    redis_client.hset("position:RELIANCE", mapping={"status": "OPEN"})
    redis_client.sadd("portfolio:active_positions", "RELIANCE")
    script = load_lua("position_close.lua")

    result = script(keys=["RELIANCE"], args=["2000"])

    assert result == 1
    assert not redis_client.exists("position:RELIANCE")
    assert not redis_client.sismember("portfolio:active_positions", "RELIANCE")
    assert redis_client.get("portfolio:margin:available") == "3000"
