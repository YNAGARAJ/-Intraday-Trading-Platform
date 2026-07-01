"""Unit tests for the M08 MLflow registry (save/load/promote, all mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from shared.regime.classifier import RegimeClassifier
from shared.regime.mlflow_registry import (
    _REGISTERED_MODEL_NAME,
    list_model_versions,
    promote_classifier,
    save_classifier,
)
from shared.regime.models import MarketRegime


def _fitted_classifier() -> RegimeClassifier:
    clf = RegimeClassifier()
    rng = np.random.default_rng(1)
    per_class = 25
    rows = []
    labels = []
    for regime, center in [
        (MarketRegime.BULL_TREND, [32.0, 65.0, 2.0, 0.5, 1.5, 1.1, 14.0, 0.0]),
        (MarketRegime.BEAR_TREND, [30.0, 35.0, 2.2, 0.6, -1.5, 1.2, 14.0, 0.0]),
        (MarketRegime.MEAN_REVERTING, [14.0, 50.0, 3.0, 0.4, 0.1, 0.9, 13.0, 0.0]),
        (MarketRegime.HIGH_VOL_CHAOS, [20.0, 45.0, 8.0, 2.0, 0.5, 3.0, 30.0, 1.0]),
    ]:
        noise = rng.normal(0, 0.5, size=(per_class, 8))
        rows.append(np.array(center, dtype=np.float64) + noise)
        labels.extend([regime] * per_class)
    x_train = np.vstack(rows)
    clf.fit(x_train, labels)
    return clf


class TestSaveClassifier:
    def test_raises_when_not_fitted(self) -> None:
        clf = RegimeClassifier()
        with pytest.raises(RuntimeError, match="unfitted"):
            save_classifier(clf)

    @patch("shared.regime.mlflow_registry.mlflow")
    def test_returns_run_id(self, mock_mlflow: MagicMock) -> None:
        clf = _fitted_classifier()
        run_mock = MagicMock()
        run_mock.__enter__ = MagicMock(return_value=run_mock)
        run_mock.__exit__ = MagicMock(return_value=False)
        run_mock.info.run_id = "abc123"
        mock_mlflow.start_run.return_value = run_mock
        mock_mlflow.sklearn.log_model = MagicMock()
        mock_mlflow.log_artifact = MagicMock()
        mock_mlflow.log_metrics = MagicMock()

        run_id = save_classifier(clf, metrics={"accuracy": 0.9})
        assert run_id == "abc123"

    @patch("shared.regime.mlflow_registry.mlflow")
    def test_logs_metrics_when_provided(self, mock_mlflow: MagicMock) -> None:
        clf = _fitted_classifier()
        run_mock = MagicMock()
        run_mock.__enter__ = MagicMock(return_value=run_mock)
        run_mock.__exit__ = MagicMock(return_value=False)
        run_mock.info.run_id = "run42"
        mock_mlflow.start_run.return_value = run_mock

        save_classifier(clf, metrics={"f1_macro": 0.88})
        mock_mlflow.log_metrics.assert_called_once_with({"f1_macro": 0.88})


class TestPromoteClassifier:
    def _metrics_pass(self) -> MagicMock:
        """BacktestMetrics mock that passes RULE 6 gate."""
        m = MagicMock()
        m.sharpe_ratio = 2.0
        m.win_rate_pct = 55.0
        m.max_drawdown_pct = 3.0
        m.trading_days = 25
        return m

    def _metrics_fail(self) -> MagicMock:
        """BacktestMetrics mock that fails the RULE 6 gate."""
        m = MagicMock()
        m.sharpe_ratio = 0.5
        m.win_rate_pct = 40.0
        m.max_drawdown_pct = 10.0
        m.trading_days = 10
        return m

    def test_returns_failures_when_gate_fails(self) -> None:
        failures = promote_classifier("run1", self._metrics_fail())
        assert len(failures) > 0

    @patch("shared.regime.mlflow_registry.mlflow")
    def test_promotes_model_when_gate_passes(self, mock_mlflow: MagicMock) -> None:
        mv = MagicMock()
        mv.run_id = "run_pass"
        mv.version = "3"
        client = mock_mlflow.tracking.MlflowClient.return_value
        client.search_model_versions.return_value = [mv]
        client.transition_model_version_stage = MagicMock()

        failures = promote_classifier("run_pass", self._metrics_pass())
        assert failures == []
        client.transition_model_version_stage.assert_called_once_with(
            name=_REGISTERED_MODEL_NAME,
            version="3",
            stage="Production",
            archive_existing_versions=True,
        )

    @patch("shared.regime.mlflow_registry.mlflow")
    def test_returns_error_when_run_not_found(self, mock_mlflow: MagicMock) -> None:
        client = mock_mlflow.tracking.MlflowClient.return_value
        client.search_model_versions.return_value = []
        failures = promote_classifier("nonexistent_run", self._metrics_pass())
        assert any(
            "not found" in f.lower() or "no registered" in f.lower()
            for f in failures
        )


class TestListModelVersions:
    @patch("shared.regime.mlflow_registry.mlflow")
    def test_returns_list_of_dicts(self, mock_mlflow: MagicMock) -> None:
        mv = MagicMock()
        mv.version = "1"
        mv.run_id = "abc"
        mv.current_stage = "Production"
        mv.status = "READY"
        client = mock_mlflow.tracking.MlflowClient.return_value
        client.search_model_versions.return_value = [mv]

        result = list_model_versions()
        assert len(result) == 1
        assert result[0]["version"] == "1"
        assert result[0]["stage"] == "Production"

    @patch("shared.regime.mlflow_registry.logger")
    @patch("shared.regime.mlflow_registry.mlflow")
    def test_returns_empty_on_exception_and_logs_warning(
        self, mock_mlflow: MagicMock, mock_logger: MagicMock
    ) -> None:
        client = mock_mlflow.tracking.MlflowClient.return_value
        client.search_model_versions.side_effect = Exception("connection refused")
        result = list_model_versions()
        assert result == []
        mock_logger.warning.assert_called_once_with(
            "mlflow_list_versions_failed", error="connection refused"
        )
