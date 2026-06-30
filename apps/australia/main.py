"""App 2 (Australia / ASX) execution entrypoint.

M01 scope: boot configuration and logging, confirm the trading-mode safety invariant,
and run a minimal heartbeat loop so the container has a real long-running process for
docker-compose healthchecks. Actual agent wiring is owned by the orchestrator (M18)
and is not present yet -- every module from here through M17 plugs into this
entrypoint incrementally.
"""

import time
from pathlib import Path

from shared.core.config import load_region_config, load_settings
from shared.core.logging import configure_logging, get_logger
from shared.core.types import AppId

CONFIG_PATH = Path(__file__).parent / "config.yaml"
HEARTBEAT_INTERVAL_SECONDS = 10.0


def main() -> None:
    """Boot the Australia app process and run the scaffold heartbeat loop."""
    settings = load_settings(app_id=AppId.AUSTRALIA)
    configure_logging(settings.log_level)
    logger = get_logger(__name__)

    region = load_region_config(CONFIG_PATH)

    logger.info(
        "system_starting",
        app_id=settings.app_id.value,
        exchange=region.exchange.value,
        broker=region.broker_name,
        trading_mode=settings.trading_mode.value,
        live_trading_enabled=settings.is_live_trading_enabled,
    )

    if settings.is_live_trading_enabled:
        logger.warning(
            "live_trading_enabled",
            detail="TRADING_MODE=LIVE and LIVE_TRADING_CONFIRMED=true are both set",
        )
    else:
        logger.info("paper_trading_mode_active")

    logger.info("heartbeat_loop_starting", interval_seconds=HEARTBEAT_INTERVAL_SECONDS)
    try:
        while True:
            logger.info("heartbeat", app_id=settings.app_id.value)
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("system_shutdown", app_id=settings.app_id.value)


if __name__ == "__main__":
    main()
