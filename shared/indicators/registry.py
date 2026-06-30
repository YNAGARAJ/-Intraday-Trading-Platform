"""Extensible indicator registry.

The design goal (per MASTER_BUILD_PROMPT_FINAL.MD M04): adding an indicator means
adding one file under `shared/indicators/definitions/` and nothing else. Each
definition file calls `@register_indicator(...)` once at import time; nothing outside
that file needs to know the indicator exists. `shared.indicators.definitions` imports
every definition module so registration happens as a side effect of importing the
package -- see that package's `__init__.py`.
"""

from collections.abc import Callable
from dataclasses import dataclass

from shared.core.exceptions import DuplicateIndicatorError
from shared.indicators.models import CandleArrays, IndicatorOutputDict

ComputeFn = Callable[[CandleArrays], IndicatorOutputDict]


@dataclass(frozen=True)
class IndicatorSpec:
    """A single registered indicator: its name, minimum history requirement, and the
    function that computes it."""

    name: str
    min_candles: int
    compute: ComputeFn


_REGISTRY: dict[str, IndicatorSpec] = {}


def register_indicator(name: str, min_candles: int) -> Callable[[ComputeFn], ComputeFn]:
    """Decorator: register `fn` as the indicator named `name`.

    Args:
        name: Unique indicator name (e.g. "EMA", "RSI_14"). Used as both the
            registry key and, by convention, a prefix for the output dict's keys.
        min_candles: Minimum candle count required before `fn` is called; callers
            with fewer candles than this skip the indicator rather than calling it
            with insufficient data.

    Raises:
        DuplicateIndicatorError: If `name` is already registered -- two definition
            files claiming the same name would silently shadow one indicator with
            another, which is a correctness risk for anything reading the result.
    """

    def decorator(fn: ComputeFn) -> ComputeFn:
        if name in _REGISTRY:
            raise DuplicateIndicatorError(
                f"indicator {name!r} is already registered "
                f"(by {_REGISTRY[name].compute.__module__})"
            )
        _REGISTRY[name] = IndicatorSpec(name=name, min_candles=min_candles, compute=fn)
        return fn

    return decorator


def all_indicators() -> dict[str, IndicatorSpec]:
    """Return a snapshot of every currently-registered indicator."""
    return dict(_REGISTRY)


def reset_registry() -> None:
    """Clear all registrations. Test-only: lets unit tests register fakes without
    colliding with the real definitions or leaking into other tests."""
    _REGISTRY.clear()
