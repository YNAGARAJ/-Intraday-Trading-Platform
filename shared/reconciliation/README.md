# M17 — Reconciliation Agent

Periodically diffs broker source-of-truth (positions + open orders) against internal
Redis/Postgres state. On any mismatch it emits a `ReconciliationMismatch` proto event
to a Redis Stream and blocks new entry signals on the affected symbol until the next
clean cycle.

## Modules

| File | Purpose |
|---|---|
| `models.py` | Frozen dataclasses: `BrokerPosition`, `BrokerOrder`, `InternalPosition`, `InternalOrder`, `ReconciliationMismatch`, `ReconciliationResult` |
| `differ.py` | Pure diff logic: `diff_positions()`, `diff_orders()` |
| `publisher.py` | `MismatchPublisher` — serialises to proto, writes to Redis Stream |
| `block_registry.py` | `BlockRegistry` — per-symbol entry-block flag in Redis (in-memory fallback) |
| `agent.py` | `ReconciliationAgent` — background timer, full cycle orchestration |
| `cli.py` | 20 VERIFY scenarios |

## Key APIs

```python
from shared.reconciliation import (
    ReconciliationAgent,
    BlockRegistry,
    MismatchPublisher,
    diff_positions,
    diff_orders,
)

agent = ReconciliationAgent(
    broker_state=my_broker_adapter,   # implements BrokerStateProvider
    internal_state=my_internal_store, # implements InternalStateProvider
    publisher=MismatchPublisher(redis_client),
    block_registry=BlockRegistry(redis_client),
    interval_seconds=90,
    on_mismatch=lambda mm: send_telegram_alert(mm),
)
agent.start()   # background daemon timer

# Check before forwarding signals (M18 orchestrator)
if agent.is_blocked("RELIANCE", "NSE"):
    ...  # suppress new entries

# Manual cycle (e.g. at square-off)
result = agent.run_cycle()
```

## Mismatch fields

| `MismatchField` | Trigger |
|---|---|
| `QUANTITY` | Broker qty ≠ internal qty |
| `AVG_PRICE` | Price delta > 0.1% |
| `ORDER_STATUS` | Status strings differ (case-insensitive) |
| `POSITION_MISSING` | Internal holds position, broker has none |
| `UNEXPECTED_POSITION` | Broker has position, internal has none |
| `ORDER_MISSING` | Internal tracks order, broker has no record |
| `UNEXPECTED_ORDER` | Broker has order not tracked internally |

## Redis keys

| Key | Purpose |
|---|---|
| `reconciliation:blocked:<EXCHANGE>:<SYMBOL>` | Entry-block flag per symbol |
| `reconciliation:mismatches` | Redis Stream of `ReconciliationMismatch` protos |

## Environment variables

None — interval and Redis client are injected at construction time.

## Degraded / fail-open behaviour

- Redis unavailable → `BlockRegistry` falls back to in-memory set; blocks survive
  only the current process lifetime but still prevent new entries.
- `MismatchPublisher` Redis failure → event is logged via `structlog`; the block flag
  is still set (blocking is the primary safety control, not the stream).
- Broker API failure → `BrokerStateProvider` implementations return empty lists;
  all internal state appears as `POSITION_MISSING` / `ORDER_MISSING` mismatches,
  triggering blocks. This is intentionally conservative.

## Running VERIFY

```bash
python -m shared.reconciliation
# Expected: 20/20 VERIFY_PASS
```

## Running tests

```bash
python -m pytest tests/test_reconciliation_*.py -v
# Expected: 65 passed
```
