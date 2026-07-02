"""Tests for M20 alert data models."""

from __future__ import annotations

import time

import pytest

from shared.alerts.models import Alert, AlertLevel, AlertType


class TestAlertLevel:
    def test_info_value(self) -> None:
        assert AlertLevel.INFO.value == "INFO"

    def test_warning_value(self) -> None:
        assert AlertLevel.WARNING.value == "WARNING"

    def test_critical_value(self) -> None:
        assert AlertLevel.CRITICAL.value == "CRITICAL"

    def test_exactly_three_levels(self) -> None:
        assert len(list(AlertLevel)) == 3


class TestAlertType:
    def test_signal(self) -> None:
        assert AlertType.SIGNAL.value == "SIGNAL"

    def test_fill(self) -> None:
        assert AlertType.FILL.value == "FILL"

    def test_error(self) -> None:
        assert AlertType.ERROR.value == "ERROR"

    def test_pnl(self) -> None:
        assert AlertType.PNL.value == "PNL"

    def test_circuit_breaker(self) -> None:
        assert AlertType.CIRCUIT_BREAKER.value == "CIRCUIT_BREAKER"

    def test_kill_switch(self) -> None:
        assert AlertType.KILL_SWITCH.value == "KILL_SWITCH"

    def test_reconciliation_mismatch(self) -> None:
        assert AlertType.RECONCILIATION_MISMATCH.value == "RECONCILIATION_MISMATCH"

    def test_llm_cost(self) -> None:
        assert AlertType.LLM_COST.value == "LLM_COST"

    def test_dead_letter(self) -> None:
        assert AlertType.DEAD_LETTER.value == "DEAD_LETTER"

    def test_heartbeat(self) -> None:
        assert AlertType.HEARTBEAT.value == "HEARTBEAT"

    def test_exactly_ten_types(self) -> None:
        assert len(list(AlertType)) == 10


class TestAlert:
    def test_required_fields_stored(self) -> None:
        a = Alert(AlertType.SIGNAL, AlertLevel.INFO, "test")
        assert a.alert_type is AlertType.SIGNAL
        assert a.level is AlertLevel.INFO
        assert a.message == "test"

    def test_timestamp_defaults_to_now(self) -> None:
        before = time.time() * 1000
        a = Alert(AlertType.FILL, AlertLevel.INFO, "filled")
        after = time.time() * 1000
        assert before <= a.timestamp_ms <= after

    def test_metadata_defaults_to_empty_dict(self) -> None:
        a = Alert(AlertType.ERROR, AlertLevel.CRITICAL, "oops")
        assert a.metadata == {}

    def test_metadata_stored(self) -> None:
        a = Alert(
            AlertType.KILL_SWITCH,
            AlertLevel.CRITICAL,
            "halted",
            metadata={"reason": "circuit_breaker"},
        )
        assert a.metadata["reason"] == "circuit_breaker"

    def test_custom_timestamp(self) -> None:
        ts = 1_700_000_000_000.0
        a = Alert(AlertType.PNL, AlertLevel.WARNING, "pnl", timestamp_ms=ts)
        assert a.timestamp_ms == ts

    def test_independent_metadata_dicts(self) -> None:
        a1 = Alert(AlertType.SIGNAL, AlertLevel.INFO, "a")
        a2 = Alert(AlertType.SIGNAL, AlertLevel.INFO, "b")
        a1.metadata["k"] = "v"
        assert "k" not in a2.metadata

    @pytest.mark.parametrize("level", list(AlertLevel))
    def test_all_levels_accepted(self, level: AlertLevel) -> None:
        a = Alert(AlertType.PNL, level, "msg")
        assert a.level is level

    @pytest.mark.parametrize("atype", list(AlertType))
    def test_all_types_accepted(self, atype: AlertType) -> None:
        a = Alert(atype, AlertLevel.INFO, "msg")
        assert a.alert_type is atype
