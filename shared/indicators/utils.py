"""Small shared helpers used by multiple indicator definition files."""

import numpy as np
from numpy.typing import NDArray


def last_value(arr: NDArray[np.float64]) -> float | None:
    """Return the most recent value in `arr`, or `None` if empty or NaN.

    TA-Lib pads the unstable warm-up period of any indicator with NaN -- e.g.
    EMA(200) on 50 candles is all NaN. Every definition file uses this rather than
    indexing `arr[-1]` directly so callers get a clean `None` instead of a NaN
    silently propagating into cached results or, worse, a signal-gate comparison.
    """
    if arr.size == 0:
        return None
    value = float(arr[-1])
    return None if np.isnan(value) else value
