"""M08 data models for market regime classification.

MarketRegime is a str-enum so it can be compared directly to the string values
stored in the RegimeChanged protobuf field and in Redis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class MarketRegime(str, Enum):
    """Four distinct market regimes recognised by the classifier.

    HIGH_VOL_CHAOS triggers a hard trade halt (RULE 2) — zero risk, no exceptions.
    """

    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    MEAN_REVERTING = "MEAN_REVERTING"
    HIGH_VOL_CHAOS = "HIGH_VOL_CHAOS"


@dataclass(frozen=True)
class RegimeFeatures:
    """Feature vector fed to both the Random Forest and HMM models.

    All values are computed from a lookback window of OHLCV candles.  The
    ``vix`` field is injected by the caller (from an external VIX data source)
    since it is not derivable from equity OHLCV alone.
    """

    adx: float
    """ADX(14): directional-movement strength (0–100)."""

    rsi: float
    """RSI(14): momentum oscillator (0–100)."""

    bb_width_pct: float
    """Bollinger Band width as a percentage of the middle band price."""

    atr_pct: float
    """ATR(14) normalised as a percentage of the current close price."""

    vwap_deviation_pct: float
    """(close - session VWAP) / session VWAP × 100."""

    volume_ratio: float
    """Current bar volume divided by 20-bar rolling mean volume."""

    vix: float
    """VIX level injected externally; 0.0 when unavailable."""

    atr_spike: bool
    """True when current ATR > REGIME_ATR_SPIKE_MULTIPLIER × rolling mean ATR."""

    def to_feature_array(self) -> list[float]:
        """Return a flat float list suitable for numpy/sklearn ingestion.

        atr_spike is cast to 0.0/1.0 so the array is fully numeric.
        """
        return [
            self.adx,
            self.rsi,
            self.bb_width_pct,
            self.atr_pct,
            self.vwap_deviation_pct,
            self.volume_ratio,
            self.vix,
            1.0 if self.atr_spike else 0.0,
        ]


@dataclass(frozen=True)
class RegimeClassification:
    """Output of a single regime-classification call.

    ``confidence`` is the RF model's predicted probability for the chosen
    regime class.  When the rule-based fallback is used (model not yet
    fitted), confidence is set to 1.0 for HIGH_VOL_CHAOS and 0.0 otherwise
    to signal that the value is not an RF probability.
    """

    regime: MarketRegime
    confidence: float
    features: RegimeFeatures
    hmm_state: int
    """Raw HMM hidden-state index (0–3).  The mapping to MarketRegime labels
    is established at training time and stored alongside the model."""
    classified_at: datetime
