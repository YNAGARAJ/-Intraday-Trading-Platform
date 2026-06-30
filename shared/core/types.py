"""Shared enums used across modules.

Scope is deliberately narrow for M01: only the enumerations that are cross-cutting and
referenced by the Ten Golden Rules / system overview belong here. Module-specific
TypedDicts (e.g. the full `TradingSystemState` orchestrator schema) are owned by the
module that introduces them (M18) and are not pre-built here.
"""

from enum import Enum


class TradingMode(str, Enum):
    """RULE 1: paper is always the default; live requires double confirmation."""

    PAPER = "PAPER"
    LIVE = "LIVE"


class AppId(str, Enum):
    """Identifies which regional app a process belongs to."""

    INDIA = "india"
    AUSTRALIA = "australia"


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    ASX = "ASX"


class MarketRegime(str, Enum):
    """Four-state regime classification; HIGH_VOL_CHAOS forces a hard halt (RULE 2)."""

    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    MEAN_REVERTING = "MEAN_REVERTING"
    HIGH_VOL_CHAOS = "HIGH_VOL_CHAOS"


class SessionState(str, Enum):
    """Session state machine implemented by the Market Calendar & Session Manager
    (M02)."""

    CLOSED = "CLOSED"
    PRE_MARKET = "PRE_MARKET"
    OPEN = "OPEN"
    SNAPSHOT_WINDOW = "SNAPSHOT_WINDOW"
    APPROACHING_CLOSE = "APPROACHING_CLOSE"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MPP = "MPP"
    SL = "SL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PLACED = "PLACED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class BrokerName(str, Enum):
    """Strategy-pattern broker adapter identity (M14)."""

    PAPER = "paper"
    KITE = "kite"
    IBKR = "ibkr"


class CorporateActionType(str, Enum):
    """Instrument Master & Corporate Actions (M05). SPLIT and BONUS both adjust
    historical price/volume series (see shared/instruments/adjustment.py); DIVIDEND
    and SYMBOL_CHANGE are recorded but not price-adjusted -- see ADR-010."""

    SPLIT = "SPLIT"
    BONUS = "BONUS"
    DIVIDEND = "DIVIDEND"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"
