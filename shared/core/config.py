"""Process configuration: environment-driven Settings plus per-region config.yaml.

Two distinct sources, by design:

- `Settings` (this module) -- environment-driven (`.env` / real env vars), validated by
  Pydantic Settings v2, fail-fast on type errors. Holds secrets, connection strings, and
  mode flags that differ between dev/staging/prod and must never be committed to git.
- `RegionConfig` -- static per-app regional parameters (exchange, broker, market hours)
  loaded from each app's `config.yaml`. These are not secrets and are safe to commit;
  they describe *which market* a process is trading, not *how to authenticate* to it.

`Settings` is intentionally scoped to the fields M01's own code needs (trading mode,
infra connection strings, logging). Later modules add their own fields here as they're
built (e.g. M15 adds broker credential fields) rather than M01 pre-declaring fields
nothing reads yet.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.core.exceptions import ConfigValidationError
from shared.core.types import AppId, Exchange, TradingMode


class Settings(BaseSettings):
    """Environment-driven configuration, shared by both apps.

    Loaded from process environment variables first, then `.env` for anything unset.
    See `.env.example` at the repo root for the full documented variable list across
    all modules.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_id: AppId
    environment: str = "development"
    log_level: str = "INFO"

    # RULE 1: paper trading is always the default. Live trading requires BOTH flags
    # true -- see `is_live_trading_enabled` below. Neither flag alone is sufficient.
    trading_mode: TradingMode = TradingMode.PAPER
    live_trading_confirmed: bool = False

    # Infra connection strings. `rediss://` / `sslmode=require` (TLS) are the expected
    # schemes in any non-local environment; localhost defaults here are for
    # docker-compose dev only.
    redis_url: str = "redis://localhost:6379/0"
    postgres_dsn: str = "postgresql://trading:trading@localhost:5432/trading"
    timescale_dsn: str = "postgresql://trading:trading@localhost:5433/trading_ts"

    @property
    def is_live_trading_enabled(self) -> bool:
        """True only when both `trading_mode=LIVE` and `live_trading_confirmed=true`.

        Deliberately fails closed: a partially-configured environment (one flag set,
        not the other) is treated as paper mode, never as an ambiguous/crashing state.
        """
        return self.trading_mode is TradingMode.LIVE and self.live_trading_confirmed


def load_settings(**overrides: Any) -> Settings:
    """Load `Settings`, wrapping Pydantic's `ValidationError` in our own exception type.

    Args:
        **overrides: Explicit field overrides (mainly for tests); else env/.env.

    Returns:
        A validated `Settings` instance.

    Raises:
        ConfigValidationError: If required fields are missing or fail validation.
    """
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        raise ConfigValidationError(str(exc)) from exc


class RegionConfig(BaseModel):
    """Static per-app regional configuration, loaded from `apps/<app>/config.yaml`."""

    app_id: AppId
    exchange: Exchange
    broker_name: str
    timezone: str
    """IANA timezone name, e.g. "Asia/Kolkata" or "Australia/Sydney"."""
    pre_market_local: str
    """Infra scale-on / knowledge-engine start time, "HH:MM" 24h format."""
    market_open_local: str
    """Local market open time, "HH:MM" 24h format."""
    market_close_local: str
    """Local market close time, "HH:MM" 24h format."""
    square_off_local: str
    """Hard square-off time, "HH:MM" 24h format."""
    snapshot_window_start_local: str | None = None
    """SEBI snapshot window start, "HH:MM" 24h format. India only -- None elsewhere."""


def load_region_config(path: Path) -> RegionConfig:
    """Load and validate a region's `config.yaml`.

    Args:
        path: Path to the YAML file.

    Returns:
        A validated `RegionConfig` instance.

    Raises:
        ConfigValidationError: If the file is missing, malformed, or fails validation.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        msg = f"Failed to read region config {path}: {exc}"
        raise ConfigValidationError(msg) from exc

    try:
        return RegionConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigValidationError(f"Invalid region config {path}: {exc}") from exc
