"""Pattern Recognition Engine (M06).

Candlestick pattern detection (TA-Lib full CDL set), Opening Range Breakout (ORB)
detection, and Support/Resistance level identification from swing pivots and
volume-at-price profiling. Supports multi-timeframe cross-validation (Gate 5 of the
9-gate signal system). Pure Python + NumPy/TA-Lib -- zero LLM (RULE 4).

Public API:
  - `shared.patterns.engine.compute_snapshot` -- single timeframe
  - `shared.patterns.engine.compute_multi_timeframe` -- cross-TF confirmation
  - `shared.patterns.candlestick.detect_all` / `detect_recent` -- direct CDL scan
  - `shared.patterns.orb.detect_orb` -- ORB state
  - `shared.patterns.support_resistance.detect_sr_levels` -- S/R levels

See `shared/patterns/__main__.py` for the standalone CLI (`python -m shared.patterns`).
"""
