"""Entry point: python -m dashboard

Launches the Streamlit operational dashboard.
Run: streamlit run dashboard/app.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Launch the Streamlit dashboard."""
    app_path = Path(__file__).parent / "app.py"
    result = subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path)] + sys.argv[1:],
        check=False,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
