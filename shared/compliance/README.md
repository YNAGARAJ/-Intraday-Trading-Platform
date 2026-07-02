# M13 — Compliance & Regulatory Engine

Pre-trade compliance gateway (India SEBI + Australia ASIC). Every order must pass
`ComplianceEngine.check()` before reaching M14 — there is no bypass path.

## Checks at a glance

### India (NSE/BSE) — SEBI April 2026 Framework

| Check | Rule | Outcome on fail |
|-------|------|-----------------|
| Strategy-ID / Generic Algo ID | Every algo order must carry a tag | Rejected — `NO_STRATEGY_ID` |
| MARKET order → MPP conversion | Convert to limit + 0.25% buffer | Blocked if LTP missing; otherwise auto-converted |
| Max leverage 5× | `notional / capital ≤ 5` | Rejected — `LEVERAGE_EXCEEDED` |
| MWPL filter | OI ≤ 90% of Market Wide Position Limit | Rejected — `MWPL_EXCEEDED` |
| Force square-off | No new entries at/after 15:10 IST | Rejected — `FORCE_SQUARE_OFF` |

### Australia (ASX) — ASIC obligations

| Check | Rule | Outcome on fail |
|-------|------|-----------------|
| Wash trading | No opposing order on same symbol within 60 s | Rejected — `WASH_TRADING` |
| Layering | No simultaneous opposing pending orders | Rejected — `LAYERING` |
| Short-sell approval | Symbol must be on IBKR-verified short list | Rejected — `SHORT_SELL_NOT_APPROVED` |
| Staggered open | 15-min noise filter from ASX group open time | Rejected — `STAGGERED_OPEN_NOISE_FILTER` |
| Post-close cutoff | No new entries after 16:21:30 AEST | Rejected — `POST_CLOSE_CUTOFF` |

### Tiered Kill Switch (ASIC + RULE 1)

| Tier | Trigger | Entry point |
|------|---------|-------------|
| 1 — Autonomous | Circuit breaker: -2% daily P&L | `KillSwitchManager.trigger_tier1()` |
| 2 — External API | Telegram `/kill` or `POST /api/v1/controls/kill` | `KillSwitchManager.trigger_tier2()` |
| 3 — Heartbeat | M19 detects 2 missed agent heartbeats | `KillSwitchManager.trigger_tier3()` |

All tiers set `system:status:halted = true` in Redis. `KillSwitchEvent.is_priority = True`
is set ONLY by `KillSwitchManager` — no signal/entry/API code may set it (RULE 8).

## Key APIs

```python
from shared.compliance import ComplianceEngine, KillSwitchManager, OrderIntent

engine = ComplianceEngine()

order = OrderIntent(
    symbol="RELIANCE", exchange="NSE", direction="LONG",
    order_type="LIMIT", quantity=10, price=2450.0, stop_loss=2413.0,
    strategy_name="EMA_VWAP_TREND", client_order_id="unique-id-001",
    ltp=2450.0, notional_value=24500.0, capital=100_000.0,
)
dec = engine.check(order, now_ist=datetime(2026, 7, 2, 10, 30))

if dec.approved:
    tag = dec.tagged_order.strategy_tag      # "STRAT001"
    eff_type = dec.tagged_order.effective_order_type  # "LIMIT" or "MPP"
    mpp_price = dec.tagged_order.mpp_price   # None for LIMIT
else:
    for v in dec.violations:
        print(v.code, v.detail)

# Kill switch (all three tiers)
ks = KillSwitchManager(redis_client=redis)
event = ks.trigger_tier1(daily_pnl_pct=-2.3)   # event.is_priority is True
```

## Strategy IDs

| Strategy name | Compressed tag | Env override |
|--------------|----------------|--------------|
| `EMA_VWAP_TREND` | `STRAT001` | `STRATEGY_ID_EMA_VWAP_TREND` |
| `ORB_BREAKOUT` | `STRAT002` | `STRATEGY_ID_ORB_BREAKOUT` |
| `MOMENTUM_RSI` | `STRAT003` | `STRATEGY_ID_MOMENTUM_RSI` |
| `MEAN_REVERT_PIVOT` | `STRAT004` | `STRATEGY_ID_MEAN_REVERT_PIVOT` |
| `ORDER_FLOW_ABSORPTION` | `STRAT005` | `STRATEGY_ID_ORDER_FLOW_ABSORPTION` |
| (any, generic mode) | `GENALG01` | `USE_GENERIC_ALGO_ID=true` |

## Standalone usage

```bash
python -m shared.compliance verify           # 20 scenarios, all must pass
python -m shared.compliance verify --scenario 01_missing_strategy_id
```

Example output:
```
  [PASS] 01_missing_strategy_id: India: unknown strategy → NO_STRATEGY_ID
  ...
  [PASS] 20_kill_switch_tiers_23: Kill switch Tier 2+3 → SYSTEM_HALTED

VERIFY PASS — 20/20 scenarios correct.
```

## Test results

163 unit tests, ruff clean, mypy --strict clean.
