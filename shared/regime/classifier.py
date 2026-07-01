"""M08 Random Forest + HMM regime classifier.

Architecture
------------
- **Random Forest** (primary): scikit-learn RandomForestClassifier trained on
  labelled RegimeFeatures vectors.  Outputs a probability distribution over
  the four MarketRegime classes.
- **HMM** (secondary / smoothing): hmmlearn GaussianHMM trained on the same
  feature matrix, unsupervised.  After training the HMM states are mapped to
  MarketRegime labels by plurality vote of the RF predictions seen in each
  HMM state.  On inference, the HMM Viterbi path provides temporal smoothing:
  if the RF confidence is below REGIME_CONFIDENCE_THRESHOLD the HMM state is
  used to confirm or override the RF prediction.
- **Rule-based fallback**: when the models are not yet fitted (e.g. on first
  boot, before sufficient training data is collected) a deterministic
  rule-based classifier is used.  This guarantees HIGH_VOL_CHAOS is always
  returned when VIX > threshold, satisfying RULE 2 even before any model
  training has occurred.

RULE 2 — HIGH_VOL_CHAOS priority
---------------------------------
Regardless of model output, if VIX > REGIME_VIX_CHAOS_THRESHOLD OR
features.atr_spike is True, the classifier ALWAYS returns HIGH_VOL_CHAOS.
This hard override is enforced inside ``classify()`` and is not bypassable
by model outputs or confidence thresholds.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

from shared.core.constants import (
    REGIME_ADX_MEAN_REVERT_THRESHOLD,
    REGIME_ADX_TREND_THRESHOLD,
    REGIME_CONFIDENCE_THRESHOLD,
    REGIME_HMM_N_COMPONENTS,
    REGIME_RF_MAX_DEPTH,
    REGIME_RF_N_ESTIMATORS,
    REGIME_RSI_MEAN_REVERT_HIGH,
    REGIME_RSI_MEAN_REVERT_LOW,
    REGIME_VIX_CHAOS_THRESHOLD,
)
from shared.core.logging import get_logger
from shared.regime.models import MarketRegime, RegimeClassification, RegimeFeatures

if TYPE_CHECKING:
    from hmmlearn.hmm import GaussianHMM
    from sklearn.ensemble import RandomForestClassifier

logger = get_logger(__name__)

# Ordered list matching sklearn's label encoding when training data is built
# with ``_regime_to_label`` below.
_REGIME_ORDER: list[MarketRegime] = [
    MarketRegime.BEAR_TREND,
    MarketRegime.BULL_TREND,
    MarketRegime.HIGH_VOL_CHAOS,
    MarketRegime.MEAN_REVERTING,
]


def _regime_to_label(regime: MarketRegime) -> int:
    return _REGIME_ORDER.index(regime)


def _label_to_regime(label: int) -> MarketRegime:
    return _REGIME_ORDER[label]


class RegimeClassifier:
    """Random Forest + HMM market regime classifier.

    Typical lifecycle
    -----------------
    1. Collect enough labelled candle feature vectors (>= REGIME_MIN_TRAINING_SAMPLES).
    2. Call ``fit(X, y)`` to train RF and HMM.
    3. Call ``classify(features)`` on each 5-minute update.
    4. Persist the fitted models via ``shared.regime.mlflow_registry``.

    Before ``fit()`` is called the classifier falls back to deterministic
    rule-based classification (see ``_rule_based_classify``).
    """

    def __init__(
        self,
        rf_model: "RandomForestClassifier | None" = None,
        hmm_model: "GaussianHMM | None" = None,
    ) -> None:
        """Initialise the classifier with optional pre-fitted models.

        Args:
            rf_model: Pre-fitted RandomForestClassifier (from MLflow).
            hmm_model: Pre-fitted GaussianHMM (from MLflow).
        """
        self._rf = rf_model
        self._hmm = hmm_model
        self._hmm_state_to_regime: dict[int, MarketRegime] = {}
        self._is_fitted: bool = rf_model is not None and hmm_model is not None

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(
        self,
        x_train: npt.NDArray[np.float64],
        y: list[MarketRegime],
    ) -> None:
        """Fit the Random Forest and HMM on labelled feature data.

        Args:
            x_train: Feature matrix of shape (n_samples, n_features), where
                each row is ``RegimeFeatures.to_feature_array()``.
            y: Regime label for each row.

        Raises:
            ValueError: When fewer than 2 samples are provided.
        """
        from hmmlearn.hmm import GaussianHMM
        from sklearn.ensemble import RandomForestClassifier

        if len(x_train) < 2:
            raise ValueError(f"Need at least 2 samples to fit, got {len(x_train)}")

        labels = np.array([_regime_to_label(r) for r in y], dtype=np.int32)

        self._rf = RandomForestClassifier(
            n_estimators=REGIME_RF_N_ESTIMATORS,
            max_depth=REGIME_RF_MAX_DEPTH,
            random_state=42,
            n_jobs=-1,
            class_weight="balanced",
        )
        self._rf.fit(x_train, labels)

        self._hmm = GaussianHMM(
            n_components=REGIME_HMM_N_COMPONENTS,
            covariance_type="full",
            n_iter=100,
            random_state=42,
        )
        self._hmm.fit(x_train)

        # Map each HMM state to a MarketRegime by majority vote of RF predictions
        hmm_states = self._hmm.predict(x_train)
        rf_preds = self._rf.predict(x_train)
        self._hmm_state_to_regime = _build_state_map(hmm_states, rf_preds)

        self._is_fitted = True
        logger.info(
            "regime_classifier_fitted",
            n_samples=len(x_train),
            hmm_state_map={k: v.value for k, v in self._hmm_state_to_regime.items()},
        )

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def classify(self, features: RegimeFeatures) -> RegimeClassification:
        """Classify the current market regime.

        HIGH_VOL_CHAOS is always returned when VIX > threshold or ATR spike
        is present, regardless of model output (RULE 2).

        Args:
            features: Computed from the most recent candle window.

        Returns:
            RegimeClassification with regime, confidence, and HMM state.
        """
        # RULE 2: hard override — must check before model inference
        if _is_chaos(features):
            return RegimeClassification(
                regime=MarketRegime.HIGH_VOL_CHAOS,
                confidence=1.0,
                features=features,
                hmm_state=-1,
                classified_at=datetime.now(timezone.utc),
            )

        if not self._is_fitted:
            return self._rule_based_classify(features)

        return self._model_classify(features)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _model_classify(self, features: RegimeFeatures) -> RegimeClassification:
        """Use fitted RF + HMM to produce a classification."""
        assert self._rf is not None  # guaranteed by _is_fitted check
        assert self._hmm is not None

        x = np.array([features.to_feature_array()], dtype=np.float64)

        proba = self._rf.predict_proba(x)[0]
        rf_label = int(np.argmax(proba))
        rf_regime = _label_to_regime(rf_label)
        rf_confidence = float(proba[rf_label])

        hmm_state = int(self._hmm.predict(x)[0])
        hmm_regime = self._hmm_state_to_regime.get(hmm_state, rf_regime)

        # If RF confidence is below threshold, let HMM provide the regime
        if rf_confidence < REGIME_CONFIDENCE_THRESHOLD:
            regime = hmm_regime
            confidence = rf_confidence
        else:
            regime = rf_regime
            confidence = rf_confidence

        logger.debug(
            "regime_classified",
            regime=regime.value,
            confidence=round(confidence, 4),
            rf_regime=rf_regime.value,
            hmm_state=hmm_state,
            hmm_regime=hmm_regime.value,
        )

        return RegimeClassification(
            regime=regime,
            confidence=round(confidence, 4),
            features=features,
            hmm_state=hmm_state,
            classified_at=datetime.now(timezone.utc),
        )

    def _rule_based_classify(self, features: RegimeFeatures) -> RegimeClassification:
        """Deterministic fallback classification when models are not fitted.

        Priority: HIGH_VOL_CHAOS > BULL/BEAR (ADX > trend threshold) >
        MEAN_REVERTING (ADX < mean-revert threshold) > BULL_TREND (default).
        Note: CHAOS is already handled in ``classify()`` before this is called.
        """
        if features.adx >= REGIME_ADX_TREND_THRESHOLD:
            if features.vwap_deviation_pct >= 0.0:
                regime = MarketRegime.BULL_TREND
            else:
                regime = MarketRegime.BEAR_TREND
        elif (
            features.adx < REGIME_ADX_MEAN_REVERT_THRESHOLD
            and REGIME_RSI_MEAN_REVERT_LOW <= features.rsi
            and features.rsi <= REGIME_RSI_MEAN_REVERT_HIGH
        ):
            regime = MarketRegime.MEAN_REVERTING
        elif features.adx >= REGIME_ADX_TREND_THRESHOLD:
            regime = MarketRegime.BULL_TREND
        else:
            # Ambiguous — default to MEAN_REVERTING (lower-risk posture)
            regime = MarketRegime.MEAN_REVERTING

        return RegimeClassification(
            regime=regime,
            confidence=0.0,
            features=features,
            hmm_state=-1,
            classified_at=datetime.now(timezone.utc),
        )


def _is_chaos(features: RegimeFeatures) -> bool:
    """Return True when features indicate HIGH_VOL_CHAOS (RULE 2 trigger)."""
    return features.vix > REGIME_VIX_CHAOS_THRESHOLD or features.atr_spike


def _build_state_map(
    hmm_states: npt.NDArray[np.int64],
    rf_labels: npt.NDArray[np.int32],
) -> dict[int, MarketRegime]:
    """Map each HMM hidden state to the MarketRegime most predicted by the RF.

    Args:
        hmm_states: HMM Viterbi state sequence, shape (n_samples,).
        rf_labels: RF predicted labels (encoded ints), shape (n_samples,).

    Returns:
        Dict mapping HMM state int → MarketRegime.
    """
    state_map: dict[int, MarketRegime] = {}
    for state in range(REGIME_HMM_N_COMPONENTS):
        mask = hmm_states == state
        if not np.any(mask):
            # Unused state — assign MEAN_REVERTING as a safe default
            state_map[state] = MarketRegime.MEAN_REVERTING
            continue
        counts = np.bincount(rf_labels[mask], minlength=len(_REGIME_ORDER))
        majority_label = int(np.argmax(counts))
        state_map[state] = _label_to_regime(majority_label)
    return state_map
