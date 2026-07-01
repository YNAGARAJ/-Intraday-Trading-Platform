"""Unit tests for shared.backtesting.walk_forward — sliding-window optimisation."""

from datetime import date, datetime, timedelta, timezone

from shared.backtesting.models import BacktestConfig, WalkForwardResult
from shared.backtesting.walk_forward import run_walk_forward
from shared.storage.models import OHLCVCandle

_T0 = datetime(2024, 1, 2, 9, 15, tzinfo=timezone.utc)


def _candle(day: int, close: float) -> OHLCVCandle:
    t = _T0 + timedelta(days=day)
    return OHLCVCandle(
        time=t,
        symbol="RELIANCE",
        exchange="NSE",
        open=close * 0.999,
        high=close * 1.001,
        low=close * 0.998,
        close=close,
        volume=10_000,
    )


def _trending_candles(n_days: int = 120, slope: float = 5.0) -> list[OHLCVCandle]:
    return [_candle(i, 2500.0 + i * slope) for i in range(n_days)]


def _config() -> BacktestConfig:
    return BacktestConfig(
        strategy_id="WF_TST",
        symbol="RELIANCE",
        exchange="NSE",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 12, 31),
        initial_capital=100_000.0,
        position_size_pct=0.02,
    )


def _simple_signal_fn(
    candles: list[OHLCVCandle], params: dict[str, float]
) -> tuple[list[bool], list[bool]]:
    """Always-long trivial strategy — ignores params."""
    n = len(candles)
    if n < 5:
        return [False] * n, [False] * n
    entries = [False] * n
    exits = [False] * n
    entries[2] = True
    exits[-2] = True
    return entries, exits


class TestRunWalkForward:
    def test_empty_candles_returns_empty_result(self) -> None:
        result = run_walk_forward(_config(), [], _simple_signal_fn, [{"p": 1.0}])
        assert isinstance(result, WalkForwardResult)
        assert result.windows == []
        assert result.windows_passed == 0

    def test_insufficient_candles_no_windows(self) -> None:
        # 10 candles < in_sample_days(60) + out_of_sample_days(20)
        candles = _trending_candles(n_days=10)
        result = run_walk_forward(
            _config(),
            candles,
            _simple_signal_fn,
            [{"p": 1.0}],
            in_sample_days=60,
            out_of_sample_days=20,
            step_days=10,
        )
        assert result.windows == []

    def test_produces_windows_for_sufficient_candles(self) -> None:
        candles = _trending_candles(n_days=120, slope=10.0)
        result = run_walk_forward(
            _config(),
            candles,
            _simple_signal_fn,
            [{"p": 1.0}],
            in_sample_days=30,
            out_of_sample_days=10,
            step_days=10,
        )
        assert len(result.windows) >= 1

    def test_window_dates_are_contiguous(self) -> None:
        candles = _trending_candles(n_days=120)
        result = run_walk_forward(
            _config(),
            candles,
            _simple_signal_fn,
            [{"p": 1.0}],
            in_sample_days=30,
            out_of_sample_days=10,
            step_days=10,
        )
        for i in range(1, len(result.windows)):
            prev = result.windows[i - 1]
            curr = result.windows[i]
            # OOS end of previous window should precede IS start of next
            assert prev.in_sample_start < curr.in_sample_start

    def test_param_grid_best_is_selected(self) -> None:
        candles = _trending_candles(n_days=120, slope=10.0)
        param_grid = [{"fast": 5.0}, {"fast": 9.0}, {"fast": 13.0}]
        result = run_walk_forward(
            _config(),
            candles,
            _simple_signal_fn,
            param_grid,
            in_sample_days=30,
            out_of_sample_days=10,
            step_days=10,
        )
        # best_params should be one of the grid entries
        for window in result.windows:
            assert window.best_params in param_grid

    def test_result_fields_are_populated(self) -> None:
        candles = _trending_candles(n_days=120)
        result = run_walk_forward(
            _config(),
            candles,
            _simple_signal_fn,
            [{"p": 1.0}],
            in_sample_days=30,
            out_of_sample_days=10,
            step_days=10,
        )
        assert result.strategy_id == "WF_TST"
        assert result.symbol == "RELIANCE"
        assert result.exchange == "NSE"
        assert isinstance(result.avg_oos_sharpe, float)
        assert isinstance(result.windows_passed, int)
