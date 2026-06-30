"""Sanity checks on shared.core.constants -- catches transcription errors vs. spec."""

from shared.core import constants as c


def test_daily_loss_limit_is_negative_two_percent() -> None:
    assert c.DAILY_LOSS_LIMIT_PCT == -2.0


def test_357_rule_ordering() -> None:
    """3-5-7 rule: per-trade < per-sector < portfolio-wide, by construction."""
    assert c.MAX_SINGLE_TRADE_LOSS_PCT < c.MAX_SECTOR_EXPOSURE_PCT
    assert c.MAX_SECTOR_EXPOSURE_PCT < c.MAX_PORTFOLIO_HEAT_PCT
    assert c.MAX_SINGLE_TRADE_LOSS_PCT == 3.0
    assert c.MAX_SECTOR_EXPOSURE_PCT == 5.0
    assert c.MAX_PORTFOLIO_HEAT_PCT == 7.0


def test_regime_risk_posture_ordering() -> None:
    """HIGH_VOL_CHAOS must be the strictly lowest risk posture (hard halt, RULE 2)."""
    assert c.RISK_PCT_HIGH_VOL_CHAOS == 0.0
    assert (
        c.RISK_PCT_HIGH_VOL_CHAOS
        < c.RISK_PCT_MEAN_REVERTING
        < c.RISK_PCT_BEAR_TREND
        < c.RISK_PCT_BULL_TREND
    )


def test_gate_9_snapshot_window_threshold_is_stricter() -> None:
    assert c.GATE_9_CONFIDENCE_THRESHOLD_SNAPSHOT_WINDOW > c.GATE_9_CONFIDENCE_THRESHOLD


def test_strategy_id_max_length_matches_kite_tag_cap() -> None:
    assert c.STRATEGY_ID_MAX_LENGTH == 8


def test_paper_trading_validation_gate_values() -> None:
    assert c.PAPER_TRADING_MIN_DAYS == 20
    assert c.PAPER_TRADING_MIN_SHARPE == 1.5
    assert c.PAPER_TRADING_MIN_WIN_RATE_PCT == 50.0
    assert c.PAPER_TRADING_MAX_DRAWDOWN_PCT == 5.0


def test_orders_per_second_self_throttle_is_ten() -> None:
    assert c.ORDERS_PER_SECOND_SELF_THROTTLE == 10
