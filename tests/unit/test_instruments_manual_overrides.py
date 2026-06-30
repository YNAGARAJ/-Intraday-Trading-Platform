"""Unit tests for shared.instruments.manual_overrides.load_manual_overrides."""

from pathlib import Path

import pytest

from shared.core.exceptions import ConfigValidationError
from shared.instruments.manual_overrides import (
    DEFAULT_OVERRIDES_PATH,
    load_manual_overrides,
)


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "overrides.yaml"
    path.write_text(content, encoding="utf-8")
    return path


class TestLoadManualOverrides:
    def test_empty_list_yields_no_overrides(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "[]\n")

        assert load_manual_overrides(path) == []

    def test_valid_split_entry(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
- symbol: EXAMPLE
  exchange: NSE
  ex_date: "2024-01-01"
  action_type: SPLIT
  ratio_numerator: 2
  ratio_denominator: 1
""",
        )

        overrides = load_manual_overrides(path)

        assert len(overrides) == 1
        assert overrides[0].symbol == "EXAMPLE"
        assert overrides[0].source == "MANUAL"
        assert overrides[0].ratio_numerator == 2

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
- symbol: EXAMPLE
  exchange: NSE
  action_type: SPLIT
  ratio_numerator: 2
  ratio_denominator: 1
""",
        )

        with pytest.raises(ConfigValidationError, match="Invalid manual override"):
            load_manual_overrides(path)

    def test_invalid_action_type_raises(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            """
- symbol: EXAMPLE
  exchange: NSE
  ex_date: "2024-01-01"
  action_type: NOT_A_REAL_TYPE
""",
        )

        with pytest.raises(ConfigValidationError):
            load_manual_overrides(path)

    def test_entry_failing_corporate_action_validation_raises(
        self, tmp_path: Path
    ) -> None:
        # action_type SPLIT but no ratio -- CorporateAction.__post_init__ rejects it.
        path = _write(
            tmp_path,
            """
- symbol: EXAMPLE
  exchange: NSE
  ex_date: "2024-01-01"
  action_type: SPLIT
""",
        )

        with pytest.raises(ConfigValidationError, match="Invalid manual override"):
            load_manual_overrides(path)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigValidationError):
            load_manual_overrides(tmp_path / "does-not-exist.yaml")

    def test_default_path_is_the_real_shipped_file(self) -> None:
        assert DEFAULT_OVERRIDES_PATH.name == "manual_overrides.yaml"
        assert DEFAULT_OVERRIDES_PATH.exists()

    def test_default_shipped_file_parses_cleanly(self) -> None:
        # The real, checked-in file -- empty by default (see its own header comment).
        assert load_manual_overrides() == []
