"""Tests for shared.core.logging: structlog JSON configuration."""

import json
import logging

import pytest

from shared.core.logging import configure_logging, get_logger


def test_configure_logging_produces_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    logger = get_logger("test.logger")

    logger.info("test_event", foo="bar", count=3)

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["event"] == "test_event"
    assert payload["foo"] == "bar"
    assert payload["count"] == 3
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_configure_logging_respects_level_filtering(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("WARNING")
    logger = get_logger("test.logger.filtered")

    logger.info("should_be_filtered_out")
    logger.warning("should_appear")

    captured = capsys.readouterr()
    assert "should_be_filtered_out" not in captured.out
    assert "should_appear" in captured.out


def test_configure_logging_accepts_lowercase_level() -> None:
    # Must not raise -- getattr(logging, "info".upper()) resolves correctly.
    configure_logging("info")
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_falls_back_to_info_on_unknown_level() -> None:
    configure_logging("NOT_A_REAL_LEVEL")
    assert logging.getLogger().level == logging.INFO
