"""Tests for shared.core.config: Settings and RegionConfig."""

from pathlib import Path

import pytest

from shared.core.config import (
    RegionConfig,
    Settings,
    load_region_config,
    load_settings,
)
from shared.core.exceptions import ConfigValidationError
from shared.core.types import AppId, Exchange, TradingMode


class TestSettings:
    def test_defaults_to_paper_trading(self) -> None:
        settings = Settings(app_id=AppId.INDIA)

        assert settings.trading_mode is TradingMode.PAPER
        assert settings.live_trading_confirmed is False
        assert settings.is_live_trading_enabled is False

    def test_live_requires_both_flags(self) -> None:
        live_mode_only = Settings(app_id=AppId.INDIA, trading_mode=TradingMode.LIVE)
        assert live_mode_only.is_live_trading_enabled is False

        confirmed_only = Settings(app_id=AppId.INDIA, live_trading_confirmed=True)
        assert confirmed_only.is_live_trading_enabled is False

    def test_live_enabled_only_when_both_flags_true(self) -> None:
        settings = Settings(
            app_id=AppId.INDIA,
            trading_mode=TradingMode.LIVE,
            live_trading_confirmed=True,
        )

        assert settings.is_live_trading_enabled is True

    def test_load_settings_wraps_validation_error(self) -> None:
        with pytest.raises(ConfigValidationError):
            load_settings(trading_mode="not-a-valid-mode")

    def test_extra_env_vars_are_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Future-module env vars in a broad .env must not break Settings load."""
        monkeypatch.setenv("KITE_API_KEY", "irrelevant-to-m01")
        settings = Settings(app_id=AppId.INDIA)
        assert settings.app_id is AppId.INDIA


class TestRegionConfig:
    def test_load_valid_region_config(self, valid_region_yaml: Path) -> None:
        config = load_region_config(valid_region_yaml)

        assert config.app_id is AppId.INDIA
        assert config.exchange is Exchange.NSE
        assert config.broker_name == "zerodha_kite"
        assert config.market_open_local == "09:15"
        assert config.square_off_local == "15:10"

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigValidationError):
            load_region_config(tmp_path / "does_not_exist.yaml")

    def test_load_malformed_yaml_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "config.yaml"
        bad.write_text("not: valid: yaml: [unterminated")
        with pytest.raises(ConfigValidationError):
            load_region_config(bad)

    def test_load_invalid_app_id_raises(self, region_yaml_factory) -> None:  # type: ignore[no-untyped-def]
        path = region_yaml_factory(app_id="not_a_real_app")

        with pytest.raises(ConfigValidationError):
            load_region_config(path)

    def test_load_invalid_exchange_raises(self, region_yaml_factory) -> None:  # type: ignore[no-untyped-def]
        path = region_yaml_factory(exchange="NOT_A_REAL_EXCHANGE")

        with pytest.raises(ConfigValidationError):
            load_region_config(path)

    def test_australia_region_config(self, region_yaml_factory) -> None:  # type: ignore[no-untyped-def]
        path = region_yaml_factory()
        config = load_region_config(path)

        assert config.app_id is AppId.AUSTRALIA
        assert config.exchange is Exchange.ASX

    def test_region_config_is_frozen_data(self, valid_region_yaml: Path) -> None:
        config = load_region_config(valid_region_yaml)
        assert isinstance(config, RegionConfig)
