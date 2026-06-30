"""Instrument Master & Corporate Actions (M05).

Maintains the canonical instrument list (symbol, exchange, lot size, tick size, ISIN)
and applies split/bonus adjustments to historical price series before they reach
indicators (M04), patterns (M06), backtesting (M07), and regime classification (M08).
Without this, those modules silently corrupt around ex-dates.

See `shared.instruments.service` for the daily refresh entry point and
`shared.instruments.adjustment` for the price-series adjustment function downstream
modules should call instead of reading raw OHLCV directly.
"""
