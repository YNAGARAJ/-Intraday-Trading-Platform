"""Run M18 VERIFY scenarios.

Usage:
    python -m shared.orchestrator
"""

from shared.orchestrator.cli import run_verify

if __name__ == "__main__":
    success = run_verify()
    raise SystemExit(0 if success else 1)
