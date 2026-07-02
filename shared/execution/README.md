# M14 — Order Execution Engine

Routes validated `OrderIntent` objects through M13 compliance, then submits them to a
broker adapter with idempotency checking, exponential-jitter retry, and dead-letter
queuing.

## Architecture

```
OrderIntent
    │
    ▼
ExecutionEngine.submit()
    ├─ 1. Kill-switch pre-check   (Redis KILL_SWITCH_HALTED_KEY)
    │       └─ skipped if order.is_priority == True
    ├─ 2. ComplianceEngine.check()  (M13)
    │       └─ REJECTED FillReport on violations
    ├─ 3. BrokerAdapter.place_order()
    │       ├─ On retry: query_order() first (idempotency — never blind-retry)
    │       ├─ BrokerTransientError → exponential jitter retry (MAX_RETRIES=3)
    │       └─ BrokerPermanentError → dead-letter immediately
    └─ 4. DeadLetterQueue.enqueue()  (all retries exhausted)
```

## Key design decisions

| Decision | Rule |
|---|---|
| `is_priority=True` settable **only** by `make_sl_exit_order()` and `make_kill_switch_liquidation_order()` | RULE 8 |
| No blind retry — `query_order()` called before any re-submission | CLAUDE.md |
| `sl_quantity` recomputed from `filled_quantity` (not `requested_quantity`) | Spec |
| Paper is the default broker; Kite/IBKR stubs require M15 auth | RULE 1 |
| Dead-letter persisted to Redis `dlq:orders`; in-memory fallback if Redis down | RULE 5 |

## Public API

```python
from shared.execution import (
    ExecutionEngine,
    make_sl_exit_order,             # authorized is_priority=True setter #1
    make_kill_switch_liquidation_order,  # authorized is_priority=True setter #2
    FillReport,
    OrderStatus,
    DeadLetterQueue,
)
```

### `ExecutionEngine`

```python
engine = ExecutionEngine(
    broker=PaperBroker(),
    compliance_engine=ComplianceEngine(),   # optional; created internally if omitted
    dead_letter_queue=DeadLetterQueue(),    # optional
    redis_client=redis,                     # optional; None = no kill-switch Redis check
    max_retries=3,                          # optional; default from constants
    retry_base_delay=0.5,                   # optional; seconds
)

fill: FillReport = engine.submit(
    order,
    now_ist=datetime(...),          # IST time for India compliance checks
    now_aest=datetime(...),         # AEST time for ASX compliance checks
    recent_orders=[...],            # for ASX wash-trade check
    pending_orders=[...],           # for ASX layering check
    approved_short_list=frozenset(["BHP", ...]),  # for ASX short-sell check
)
```

### Priority order constructors

```python
# Exit a stop-loss (is_priority=True, bypasses kill-switch block)
sl = make_sl_exit_order(
    symbol="RELIANCE", exchange="NSE", direction="LONG",
    quantity=100, stop_loss=190.0, client_order_id="SL-001",
    strategy_name="EMA_VWAP_TREND", ltp=192.0,
)

# Emergency liquidation during kill-switch sequence
liq = make_kill_switch_liquidation_order(
    symbol="TCS", exchange="NSE", direction="LONG",
    quantity=200, ltp=3500.0, client_order_id="LIQ-001",
    strategy_name="EMA_VWAP_TREND",
)
```

### `FillReport` fields

| Field | Description |
|---|---|
| `status` | `FILLED / PARTIALLY_FILLED / REJECTED / CANCELLED` |
| `filled_quantity` | Shares/contracts actually filled |
| `sl_quantity` | SL quantity — always equals `filled_quantity`, never `requested_quantity` |
| `compliance_audit_id` | M13 audit log reference |
| `attempt_count` | Number of broker submission attempts |
| `broker_order_id` | Broker-assigned ID (`None` on rejection before placement) |

### Broker adapters

| Adapter | Status | Auth |
|---|---|---|
| `PaperBroker` | Fully functional, in-memory | None |
| `KiteBroker` | Stub | M15 (`inject_client`) |
| `IBKRBroker` | Stub | M15 (`inject_client`) |

`PaperBroker` accepts `partial_fill_ratio` and `fail_count` for simulation.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `TRADING_MODE` | `PAPER` | `PAPER` or `LIVE` |
| `USE_GENERIC_ALGO_ID` | `false` | Use GENALG01 for all strategies |

## Standalone verify

```bash
python -m shared.execution verify
```

Runs 20 scenarios covering: all 5 strategies on NSE/BSE/ASX, partial fill, SL exit,
kill-switch liquidation, duplicate idempotency (no double fill), transient retry,
dead-letter queue, compliance rejection (strategy ID + force square-off), kill-switch
halted (non-priority blocked, priority passes), MPP conversion, and full audit log.
