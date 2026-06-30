"""Structlog JSON logging configuration.

`configure_logging()` must be called exactly once at process startup, before any module
obtains a logger via `get_logger()`. Output is always JSON (never a human-readable
console renderer) so logs are uniformly machine-parseable in every environment --
structured fields matter more than local dev convenience here, since this is the same
logger used in production.

Secrets must never be passed as log fields. There is no automatic redaction layer:
callers are responsible for never logging tokens, API keys, or credentials (see RULE:
"Secrets: NEVER logged, printed, or in error messages" in MASTER_BUILD_PROMPT_FINAL.MD).
"""

import logging
import sys

import structlog


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog for JSON output across the process.

    Args:
        log_level: Standard logging level name (e.g. "DEBUG", "INFO", "WARNING").
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # force=True: logging.basicConfig() is a no-op if the root logger already has
    # handlers (e.g. a prior call in the same process), so without this, calling
    # configure_logging() more than once per process would silently not reconfigure.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to `name`.

    Args:
        name: Logger name, conventionally the calling module's `__name__`.

    Returns:
        A configured structlog bound logger.
    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]
