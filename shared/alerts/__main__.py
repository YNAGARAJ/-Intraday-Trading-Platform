"""Entry point for ``python -m shared.alerts`` (M20 VERIFY harness)."""

from __future__ import annotations

import sys

from shared.alerts.cli import run_verify

if __name__ == "__main__":
    sys.exit(0 if run_verify() else 1)
