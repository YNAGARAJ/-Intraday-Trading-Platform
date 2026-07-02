"""Entry point: python -m api

With no arguments, runs 20 VERIFY scenarios.
Pass `--serve` to start the uvicorn ASGI server.
"""

from __future__ import annotations

import sys


def main() -> None:
    """Dispatch to VERIFY CLI or uvicorn server based on argv."""
    if "--serve" in sys.argv:
        import uvicorn

        from shared.core.config import settings

        uvicorn.run(
            "api.app:app",
            host="0.0.0.0",
            port=settings.api_port,
            log_level="info",
            reload=False,
        )
    else:
        from api.cli import run_verify

        sys.exit(0 if run_verify() else 1)


if __name__ == "__main__":
    main()
