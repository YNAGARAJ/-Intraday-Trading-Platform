"""Run M17 VERIFY scenarios.

Usage:
    python -m shared.reconciliation
"""

from shared.reconciliation.cli import run_verify

if __name__ == "__main__":
    success = run_verify()
    raise SystemExit(0 if success else 1)
