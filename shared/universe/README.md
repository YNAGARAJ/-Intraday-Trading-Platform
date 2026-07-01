# M09 — Stock Universe Filter

Pre-market alpha scoring pipeline that ranks all tradeable instruments and produces a
compliance-clean watchlist for downstream signal generation (M11).

## Formula

```
Γ = β_Trend·TrendScore + β_Vol·VolScore + β_Liq·LiqScore + β_Sent·SentScore
```

β weights are regime-aware (BULL_TREND / BEAR_TREND / MEAN_REVERTING). When the market
regime is `HIGH_VOL_CHAOS`, `run_universe_filter()` immediately returns `[]` per **RULE 2**.

## Modules

| File | Responsibility |
|---|---|
| `models.py` | `AlphaComponents`, `AlphaWeights`, `WatchlistEntry` dataclasses |
| `scoring.py` | `score_stock()`, `compute_composite()`, `rank_entries()`, `BETA_WEIGHTS` |
| `compliance.py` | `NSEComplianceSource`, `ComplianceExclusionList` — ASM/ESM/F&O ban/MWPL≥90% |
| `filter.py` | `run_universe_filter()` — main pipeline entry point |
| `repository.py` | `store_watchlist()` / `load_watchlist()` — TimescaleDB hypertable + Redis TTL cache |
| `cli.py` | `main()` — argument parsing, DB/Redis wiring, CLI output |

## Standalone usage

```bash
# Score NSE universe, store to DB + Redis (requires live TimescaleDB + Redis)
APP_ID=app1 python -m shared.universe --exchange NSE --regime BULL_TREND

# Dry run — score only, no writes
APP_ID=app1 python -m shared.universe --exchange NSE --regime BULL_TREND --no-store

# Load last cached watchlist
APP_ID=app1 python -m shared.universe --exchange ASX --load

# Override VIX + top-N
APP_ID=app1 python -m shared.universe --exchange NSE --vix 22.5 --top-n 10
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_ID` | Yes | — | Application identifier (`app1` or `app2`) |
| `DATABASE_URL` | Yes | — | PostgreSQL connection string (TimescaleDB) |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection string |
| `TRADING_MODE` | No | `PAPER` | Must be `PAPER` or `LIVE` |

## NSE compliance cache

Compliance lists (ASM, ESM, F&O ban, MWPL) are fetched from NSE public APIs and cached as
JSON files under `shared/data/compliance_cache/` with a 24-hour TTL. The source fails open
— if both the live fetch and the stale cache fail, the category returns an empty exclusion
set so the system stays operational.

## Output schema

`WatchlistEntry` fields written to `watchlist_history` (TimescaleDB hypertable):

```
symbol, exchange, rank, composite_score,
trend_score, vol_score, liq_score, sent_score,
regime, strategy_id, scored_at
```

Redis key: `universe:watchlist:<EXCHANGE>` — JSON, 8-hour TTL.

## Testing

```bash
# Unit tests only (no live DB/Redis)
pytest tests/unit/test_universe_*.py -v

# Integration tests (requires TimescaleDB)
pytest tests/integration/universe/ -v

# Coverage report
pytest tests/unit/test_universe_*.py --cov=shared/universe --cov-report=term-missing
```

591 unit tests pass (M01–M09). 58 integration tests skipped without live services.
