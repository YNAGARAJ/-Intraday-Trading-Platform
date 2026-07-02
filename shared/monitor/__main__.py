"""Entry point: python -m shared.monitor"""

import sys

from shared.monitor.cli import run_verify

if __name__ == "__main__":
    sys.exit(0 if run_verify() else 1)
