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
        # cache_logger_on_first_use=False (the default): module-level `logger =
        # get_logger(__name__)` singletons are common in this codebase, and if their
        # underlying logger were cached on first use, a later configure_logging()
        # call (e.g. a test reconfiguring the level, or any legitimate runtime
        # reconfiguration) would silently not apply to already-cached loggers --
        # observed as a hard crash ("I/O operation on closed file") when pytest's
        # capsys swaps sys.stdout between tests and a stale cached logger from an
        # earlier test tries to write to it. Re-resolving on every call costs
        # microseconds and isn't on the RULE 4 hot path (LLM calls), so the
        # robustness is worth it.
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to `name`.

    Args:
        name: Logger name, conventionally the calling module's `__name__`.

    Returns:
        A configured structlog bound logger.
    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]
