"""M08: Random Forest + HMM market regime classifier.

Public API
----------
- ``MarketRegime`` — four-state enum (BULL_TREND, BEAR_TREND, MEAN_REVERTING,
  HIGH_VOL_CHAOS).
- ``RegimeFeatures`` — feature vector dataclass (ADX, RSI, BB-width, ATR-pct,
  VWAP-deviation, volume-ratio, VIX, ATR-spike flag).
- ``RegimeClassification`` — output of a single classify() call.
- ``RegimeClassifier`` — RF primary + HMM smoothing classifier.
- ``extract_features(candles, vix)`` — compute features from OHLCV window.
- ``publish_regime_change(classification, redis_client)`` — emit to Redis Streams.
"""

from shared.regime.classifier import RegimeClassifier
from shared.regime.features import extract_features
from shared.regime.models import MarketRegime, RegimeClassification, RegimeFeatures
from shared.regime.publisher import publish_regime_change

__all__ = [
    "MarketRegime",
    "RegimeFeatures",
    "RegimeClassification",
    "RegimeClassifier",
    "extract_features",
    "publish_regime_change",
]
