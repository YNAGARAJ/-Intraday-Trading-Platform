"""M09 — Stock Universe Filter.

Scores and ranks instruments by a regime-weighted alpha composite:

  Σ = β_Trend·TrendScore + β_Vol·VolScore + β_Liq·LiqScore + β_Sent·SentScore

SentScore is always 0.0 until M10 supplies sentiment data.
HIGH_VOL_CHAOS regime returns an empty watchlist (RULE 2).

Public API:
    run_universe_filter(instruments, candles_by_symbol, regime, exclusion_list)
    load_compliance_list()
    apply_universe_schema(conn)
    store_watchlist(entries, conn, redis_client)
    load_watchlist(exchange, conn, redis_client)
"""

from shared.universe.compliance import ComplianceExclusionList, load_compliance_list
from shared.universe.filter import run_universe_filter
from shared.universe.models import AlphaComponents, AlphaWeights, WatchlistEntry
from shared.universe.repository import (
    apply_universe_schema,
    load_watchlist,
    store_watchlist,
)
from shared.universe.scoring import BETA_WEIGHTS, assign_strategy_id, score_stock

__all__ = [
    "AlphaComponents",
    "AlphaWeights",
    "BETA_WEIGHTS",
    "ComplianceExclusionList",
    "WatchlistEntry",
    "apply_universe_schema",
    "assign_strategy_id",
    "load_compliance_list",
    "load_watchlist",
    "run_universe_filter",
    "score_stock",
    "store_watchlist",
]
