# M12 — Risk & Position Sizing Engine

ATR-based stop-loss sizing with 3-5-7 Rule enforcement, regime-adjusted sizing, snapshot-window multiplier, correlation guard, and daily-loss circuit breaker (RULE 8).

## Guard evaluation order (fail-fast)

| # | Guard | Threshold | Source |
|---|-------|-----------|--------|
| 1 | System halted flag | `system:status:halted=true` in Redis | RULE 8 / Kill Switch |
| 2 | Circuit breaker | Daily P&L ≤ -2% of capital | RULE 8 |
| 3 | Daily trade count | MAX_DAILY_TRADES = 10 | constants.py |
| 4 | Per-trade risk | ≤ 3% of capital | 3-5-7 Rule |
| 5 | Per-sector risk | ≤ 5% of capital | 3-5-7 Rule |
| 6 | Portfolio heat | ≤ 7% of capital | 3-5-7 Rule |
| 7 | Correlation guard | |corr| ≤ 0.70 vs all open positions | Risk spec |
| 8 | Position sizing | ATR fixed-risk or Kelly (off by default) | M11 signal output |
| 9 | Final per-trade cap | Computed risk ≤ 3% of capital | 3-5-7 Rule |

## Key APIs

```python
from shared.risk import RiskEngine, RiskParameters, OpenPosition

engine = RiskEngine()

params = RiskParameters(
    capital=100_000.0,
    open_positions=[],           # list[OpenPosition] for correlation/sector checks
    daily_pnl=-500.0,            # negative = loss today
    daily_trade_count=3,
    is_snapshot_window=False,    # True during 14:45-15:30 IST (0.5× sizing)
    regime=regime,               # RegimeClassification from M08
    proposed_sector="IT",
    proposed_returns=returns,    # list[float] daily returns for correlation guard
    halted=redis.get("system:status:halted") == b"true",
)
decision = engine.evaluate(entry_price=2450.0, stop_loss=2413.0, params=params)

if decision.approved:
    qty = decision.position_size.quantity
```

## Sizing methods

### ATR fixed-risk (default)
```
risk_amount = capital × base_risk_pct × regime_multiplier × snapshot_multiplier
quantity    = floor(risk_amount / stop_distance)
```

### Fractional Kelly (opt-in, off by default)
```
kelly_full = (b × p − q) / b     where b=win/loss ratio, p=win rate, q=1−p
fraction   = 0.25 × kelly_full   (quarter-Kelly)
quantity   = floor(capital × fraction × regime_mult × snapshot_mult / stop_distance)
```
Kelly requires `use_kelly=True` + valid `win_rate` + `avg_win_loss_ratio` in `RiskParameters`.
Must complete 20-day paper-trading validation gate before enabling in live mode (RULE 6).

## Regime risk percentages

| Regime | Base risk | Notes |
|--------|-----------|-------|
| BULL_TREND | 1.0% | Full allocation |
| BEAR_TREND | 0.75% | Conservative |
| MEAN_REVERTING | 0.5% | Reduced |
| HIGH_VOL_CHAOS | 0.0% | Blocked by M11 Gate 1 (RULE 2) |

## Standalone usage

```bash
python -m shared.risk verify                   # all scenarios
python -m shared.risk verify --scenario normal # single scenario
```

Example output for approved trade:
```
--- Normal approved trade ---
  Approved: True  Quantity: 27  Risk: 0.999%  Method: ATR_FIXED_RISK
  [PASS] SYSTEM_HALTED   [PASS] CIRCUIT_BREAKER   [PASS] MAX_PER_TRADE_RISK
  [PASS] MAX_SECTOR_RISK [PASS] MAX_PORTFOLIO_HEAT [PASS] CORRELATION_GUARD
```

## Test results

108 unit tests, 98% coverage (circuit_breaker 100%, correlation 100%, sizing 100%, models 100%).
