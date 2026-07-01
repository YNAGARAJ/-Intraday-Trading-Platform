"""MLflow model registry integration for the M08 regime classifier.

Responsibilities
----------------
- Log a fitted RegimeClassifier (RF + HMM pickle pair) to an MLflow run.
- Load the latest "Production" model from the registry.
- Gate model promotion on the same RULE 6 metrics used by M07's backtester.
- Provide ``list_model_versions()`` for operational inspection.

The RF model is logged as a sklearn flavour; the HMM is logged as a Python
object (pickle) attached as an artifact.  Both are loaded together so the
caller always gets a fully assembled RegimeClassifier.

Promotion gate (RULE 6)
-----------------------
Before a new weekly retrained model replaces the live model it must
independently clear the 20-day paper-trading gate via ``check_promotion_gate``
from ``shared.backtesting.promotion_gate``.  This function accepts a
BacktestMetrics object built from the model's out-of-sample evaluation period.
"""

from __future__ import annotations

import os
import pickle
import tempfile
from typing import Any

import mlflow
import mlflow.sklearn

from shared.backtesting.promotion_gate import check_promotion_gate
from shared.core.constants import REGIME_MLFLOW_EXPERIMENT
from shared.core.logging import get_logger
from shared.regime.classifier import RegimeClassifier

logger = get_logger(__name__)

_HMM_ARTIFACT_NAME = "hmm_model.pkl"
_STATE_MAP_ARTIFACT_NAME = "hmm_state_map.pkl"
_REGISTERED_MODEL_NAME = "regime_classifier"


def save_classifier(
    classifier: RegimeClassifier,
    metrics: dict[str, float] | None = None,
    tags: dict[str, str] | None = None,
) -> str:
    """Log a fitted RegimeClassifier to MLflow and return the run ID.

    Args:
        classifier: A fitted RegimeClassifier instance.
        metrics: Optional dict of evaluation metrics to log (e.g. accuracy).
        tags: Optional MLflow tags to attach to the run.

    Returns:
        MLflow run ID string.

    Raises:
        RuntimeError: When classifier is not fitted.
    """
    if not classifier._is_fitted:
        raise RuntimeError(
            "Cannot save an unfitted RegimeClassifier. Call fit() first."
        )
    if classifier._rf is None or classifier._hmm is None:
        raise RuntimeError("classifier._rf and classifier._hmm must both be set.")

    mlflow.set_experiment(REGIME_MLFLOW_EXPERIMENT)
    with mlflow.start_run(tags=tags) as run:
        if metrics:
            mlflow.log_metrics(metrics)

        # Log RF as sklearn model
        mlflow.sklearn.log_model(
            classifier._rf,
            artifact_path="rf_model",
            registered_model_name=_REGISTERED_MODEL_NAME,
        )

        # Log HMM and state map as pickle artifacts
        with tempfile.TemporaryDirectory() as tmpdir:
            hmm_path = os.path.join(tmpdir, _HMM_ARTIFACT_NAME)
            state_map_path = os.path.join(tmpdir, _STATE_MAP_ARTIFACT_NAME)
            with open(hmm_path, "wb") as f:
                pickle.dump(classifier._hmm, f)
            with open(state_map_path, "wb") as f:
                pickle.dump(classifier._hmm_state_to_regime, f)
            mlflow.log_artifact(hmm_path)
            mlflow.log_artifact(state_map_path)

        run_id: str = str(run.info.run_id)
        logger.info(
            "regime_classifier_saved",
            run_id=run_id,
            experiment=REGIME_MLFLOW_EXPERIMENT,
        )
        return run_id


def load_classifier(run_id: str) -> RegimeClassifier:
    """Load a RegimeClassifier from an MLflow run.

    Args:
        run_id: MLflow run ID returned by ``save_classifier``.

    Returns:
        Fully assembled RegimeClassifier with RF and HMM restored.

    Raises:
        mlflow.exceptions.MlflowException: When the run does not exist.
    """
    mlflow.set_experiment(REGIME_MLFLOW_EXPERIMENT)
    rf = mlflow.sklearn.load_model(f"runs:/{run_id}/rf_model")

    client = mlflow.tracking.MlflowClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        hmm_local = client.download_artifacts(run_id, _HMM_ARTIFACT_NAME, tmpdir)
        state_map_local = client.download_artifacts(
            run_id, _STATE_MAP_ARTIFACT_NAME, tmpdir
        )
        with open(hmm_local, "rb") as f:
            hmm = pickle.load(f)  # noqa: S301 — controlled MLflow artifact
        with open(state_map_local, "rb") as f:
            state_map = pickle.load(f)  # noqa: S301

    classifier = RegimeClassifier(rf_model=rf, hmm_model=hmm)
    classifier._hmm_state_to_regime = state_map
    logger.info("regime_classifier_loaded", run_id=run_id)
    return classifier


def promote_classifier(
    run_id: str,
    backtest_metrics: Any,
) -> list[str]:
    """Gate model promotion on RULE 6 metrics and transition to Production.

    Args:
        run_id: MLflow run ID for the candidate model.
        backtest_metrics: BacktestMetrics from the 20-day paper-trading eval.

    Returns:
        List of failure strings (empty list = gate passed, model promoted).
    """
    failures = check_promotion_gate(backtest_metrics)
    if failures:
        logger.warning(
            "regime_promotion_gate_failed",
            run_id=run_id,
            failures=failures,
        )
        return failures

    client = mlflow.tracking.MlflowClient()
    versions = client.search_model_versions(f"name='{_REGISTERED_MODEL_NAME}'")
    # Find the version registered in this run
    for mv in versions:
        if mv.run_id == run_id:
            client.transition_model_version_stage(
                name=_REGISTERED_MODEL_NAME,
                version=mv.version,
                stage="Production",
                archive_existing_versions=True,
            )
            logger.info(
                "regime_classifier_promoted",
                run_id=run_id,
                version=mv.version,
            )
            return []

    logger.warning("regime_version_not_found_for_run", run_id=run_id)
    return [f"No registered model version found for run_id={run_id}"]


def list_model_versions() -> list[dict[str, str]]:
    """Return summary info for all registered regime classifier versions.

    Returns:
        List of dicts with keys: version, run_id, stage, status.
    """
    client = mlflow.tracking.MlflowClient()
    try:
        versions = client.search_model_versions(f"name='{_REGISTERED_MODEL_NAME}'")
    except Exception:
        return []
    return [
        {
            "version": mv.version,
            "run_id": mv.run_id,
            "stage": mv.current_stage,
            "status": mv.status,
        }
        for mv in versions
    ]
