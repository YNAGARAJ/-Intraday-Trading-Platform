"""M16 Data Ingestion Agent — public API.

Key components:
- ``DataIngestionAgent``: orchestrates WS + fallback + aggregation + buffering
- ``CandleAggregator``: NumPy-backed OHLCV aggregator
- ``TickSequenceValidator``: rejects out-of-sequence / corrupt ticks
- ``TickBuffer``: Redis-backed async queue with in-memory fallback
- ``YFinanceFallback``: REST fallback on WebSocket drop (DEGRADED mode)
- ``KiteWebSocketAdapter``: Kite Connect WS feed (App 1 / NSE/BSE)
- ``IBKRStreamAdapter``: IBKR TWS stream (App 2 / ASX)
"""

from shared.ingestion.agent import DataIngestionAgent
from shared.ingestion.aggregator import CandleAggregator
from shared.ingestion.buffer import TickBuffer
from shared.ingestion.ibkr_ws import IBKRStreamAdapter
from shared.ingestion.kite_ws import KiteWebSocketAdapter
from shared.ingestion.models import (
    IngestionStatus,
    OHLCVCandle,
    RawTick,
    TickValidationError,
)
from shared.ingestion.validator import TickSequenceValidator
from shared.ingestion.yfinance_fallback import YFinanceFallback

__all__ = [
    "CandleAggregator",
    "DataIngestionAgent",
    "IBKRStreamAdapter",
    "IngestionStatus",
    "KiteWebSocketAdapter",
    "OHLCVCandle",
    "RawTick",
    "TickBuffer",
    "TickSequenceValidator",
    "TickValidationError",
    "YFinanceFallback",
]
