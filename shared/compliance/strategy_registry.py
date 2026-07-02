"""Strategy ID registry for SEBI April 2026 compliance.

Every algorithmic NSE/BSE order must carry a broker-compatible identification tag.
Zerodha Kite's ``tag`` field is capped at 8 alphanumeric characters, so all strategy
names are mapped to a compressed token.  When ``USE_GENERIC_ALGO_ID=true``, every
order uses the single generic credential ``GENALG01`` regardless of strategy.

Strategy tags are loaded from environment variables at startup; the defaults below
are the canonical compressed tokens defined in the spec.  Override them via:
    ``STRATEGY_ID_EMA_VWAP_TREND=STRAT001``
    ``STRATEGY_ID_ORB_BREAKOUT=STRAT002``
    ... etc.
"""

from __future__ import annotations

import os

import structlog

from shared.core.constants import STRATEGY_ID_MAX_LENGTH

logger = structlog.get_logger(__name__)

# Canonical strategy names (used as the ``strategy_name`` field on ``OrderIntent``)
STRATEGY_EMA_VWAP_TREND: str = "EMA_VWAP_TREND"
STRATEGY_ORB_BREAKOUT: str = "ORB_BREAKOUT"
STRATEGY_MOMENTUM_RSI: str = "MOMENTUM_RSI"
STRATEGY_MEAN_REVERT_PIVOT: str = "MEAN_REVERT_PIVOT"
STRATEGY_ORDER_FLOW_ABSORPTION: str = "ORDER_FLOW_ABSORPTION"
STRATEGY_GENERIC: str = "GENERIC"

GENERIC_ALGO_TAG: str = "GENALG01"
"""Generic broker-provided algorithmic credential tag (``USE_GENERIC_ALGO_ID=true``)."""

_DEFAULT_TAGS: dict[str, str] = {
    STRATEGY_EMA_VWAP_TREND: "STRAT001",
    STRATEGY_ORB_BREAKOUT: "STRAT002",
    STRATEGY_MOMENTUM_RSI: "STRAT003",
    STRATEGY_MEAN_REVERT_PIVOT: "STRAT004",
    STRATEGY_ORDER_FLOW_ABSORPTION: "STRAT005",
    STRATEGY_GENERIC: GENERIC_ALGO_TAG,
}


def _env_key(strategy_name: str) -> str:
    """Return the environment variable name for a strategy's compressed tag."""
    return f"STRATEGY_ID_{strategy_name}"


def _load_registry(use_generic: bool) -> dict[str, str]:
    """Build the strategy → compressed-tag mapping from env overrides + defaults."""
    if use_generic:
        return {name: GENERIC_ALGO_TAG for name in _DEFAULT_TAGS}
    registry: dict[str, str] = {}
    for name, default_tag in _DEFAULT_TAGS.items():
        env_val = os.environ.get(_env_key(name), "").strip()
        tag = env_val if env_val else default_tag
        if len(tag) > STRATEGY_ID_MAX_LENGTH:
            logger.warning(
                "strategy_tag_too_long",
                strategy=name,
                tag=tag,
                max_len=STRATEGY_ID_MAX_LENGTH,
            )
            tag = tag[:STRATEGY_ID_MAX_LENGTH]
        registry[name] = tag
    return registry


class StrategyRegistry:
    """Thread-safe mapping from strategy name to broker-compatible compressed tag.

    Instantiated once at engine startup; safe to reuse across threads because
    the underlying dict is never mutated after ``__init__``.

    Args:
        use_generic: When ``True``, all strategies map to ``GENALG01``.
            Controlled by ``USE_GENERIC_ALGO_ID`` environment variable.
    """

    def __init__(self, use_generic: bool | None = None) -> None:
        if use_generic is None:
            use_generic = (
                os.environ.get("USE_GENERIC_ALGO_ID", "false").lower() == "true"
            )
        self._use_generic = use_generic
        self._registry = _load_registry(use_generic)
        logger.info(
            "strategy_registry_loaded",
            use_generic=use_generic,
            strategies=list(self._registry.keys()),
        )

    @property
    def use_generic(self) -> bool:
        """True when all orders use the generic algo credential."""
        return self._use_generic

    def resolve(self, strategy_name: str) -> str | None:
        """Return the compressed tag for ``strategy_name``, or ``None`` if unknown.

        When ``use_generic=True``, returns ``GENALG01`` for ANY strategy name
        (including unregistered ones) — the generic credential covers all algos.

        Args:
            strategy_name: Canonical strategy name (e.g. ``'EMA_VWAP_TREND'``).

        Returns:
            Compressed ≤ 8-char tag string, or ``None`` when not registered.
        """
        if self._use_generic:
            return GENERIC_ALGO_TAG
        return self._registry.get(strategy_name)

    def all_strategies(self) -> list[str]:
        """Return all registered strategy names."""
        return list(self._registry.keys())

    def all_tags(self) -> dict[str, str]:
        """Return a copy of the full name → tag mapping."""
        return dict(self._registry)
