"""Loads the manual corporate-action override table (see manual_overrides.yaml's own
header comment for the schema and why this exists).
"""

from datetime import date
from pathlib import Path

import yaml

from shared.core.exceptions import ConfigValidationError
from shared.core.types import CorporateActionType
from shared.instruments.models import CorporateAction

DEFAULT_OVERRIDES_PATH = Path(__file__).resolve().parent / "manual_overrides.yaml"


def load_manual_overrides(path: Path = DEFAULT_OVERRIDES_PATH) -> list[CorporateAction]:
    """Parse `path` into a list of MANUAL-sourced `CorporateAction`s.

    Raises:
        ConfigValidationError: If the file is missing, malformed YAML, or an entry
            is missing a required field / has an invalid action_type -- a broken
            override file fails the whole refresh rather than silently dropping
            entries, since a missing override is exactly the kind of "silent
            corruption around ex-dates" this module exists to prevent.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigValidationError(f"Failed to read {path}: {exc}") from exc

    if not raw:
        return []

    overrides = []
    for entry in raw:
        try:
            overrides.append(
                CorporateAction(
                    symbol=entry["symbol"],
                    exchange=entry["exchange"],
                    ex_date=date.fromisoformat(entry["ex_date"]),
                    action_type=CorporateActionType(entry["action_type"]),
                    source="MANUAL",
                    ratio_numerator=entry.get("ratio_numerator"),
                    ratio_denominator=entry.get("ratio_denominator"),
                    dividend_amount=entry.get("dividend_amount"),
                    new_symbol=entry.get("new_symbol"),
                )
            )
        except (KeyError, ValueError) as exc:
            raise ConfigValidationError(
                f"Invalid manual override entry in {path}: {entry!r} ({exc})"
            ) from exc
    return overrides
