"""Core Technical Indicator Engine (M04).

Pure-Python, zero-LLM, vectorized indicator computation over OHLCV candles (RULE 4:
hot path is zero LLM). Computation is dispatched through an extensible registry
(`shared.indicators.registry`) so that adding a new indicator means adding one file
under `shared/indicators/definitions/` and nothing else -- no other module needs to
change.

See `shared.indicators.engine.compute_all` for the entry point used by callers, and
`shared/indicators/__main__.py` for the standalone CLI (`python -m shared.indicators`).
"""
