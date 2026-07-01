"""Unit tests for M09 compliance exclusion list: parsing, caching, is_excluded."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from shared.universe.compliance import (
    ComplianceExclusionList,
    NSEComplianceSource,
    _is_cache_fresh,
    _read_cache,
    _symbols_from_asm,
    _symbols_from_ban,
    _symbols_from_esm,
    _symbols_from_mwpl,
    _write_cache,
    load_compliance_list,
)

_NOW = datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)


def _make_exclusion_list(
    asm: frozenset[str] = frozenset(),
    esm: frozenset[str] = frozenset(),
    ban: frozenset[str] = frozenset(),
    mwpl: frozenset[str] = frozenset(),
) -> ComplianceExclusionList:
    return ComplianceExclusionList(
        asm_symbols=asm,
        esm_symbols=esm,
        ban_symbols=ban,
        mwpl_exceeded_symbols=mwpl,
        fetched_at=_NOW,
    )


# ---------------------------------------------------------------------------
# ComplianceExclusionList.is_excluded
# ---------------------------------------------------------------------------


class TestIsExcluded:
    def test_asm_excluded(self) -> None:
        cel = _make_exclusion_list(asm=frozenset(["RELIANCE"]))
        assert cel.is_excluded("RELIANCE") is True

    def test_esm_excluded(self) -> None:
        cel = _make_exclusion_list(esm=frozenset(["YESBANK"]))
        assert cel.is_excluded("YESBANK") is True

    def test_ban_excluded(self) -> None:
        cel = _make_exclusion_list(ban=frozenset(["VEDL"]))
        assert cel.is_excluded("VEDL") is True

    def test_mwpl_excluded(self) -> None:
        cel = _make_exclusion_list(mwpl=frozenset(["HDFC"]))
        assert cel.is_excluded("HDFC") is True

    def test_not_excluded(self) -> None:
        cel = _make_exclusion_list()
        assert cel.is_excluded("INFY") is False

    def test_case_insensitive(self) -> None:
        cel = _make_exclusion_list(asm=frozenset(["RELIANCE"]))
        assert cel.is_excluded("reliance") is True
        assert cel.is_excluded("Reliance") is True

    def test_empty_lists_never_excluded(self) -> None:
        cel = _make_exclusion_list()
        assert cel.is_excluded("ANY_SYMBOL") is False


# ---------------------------------------------------------------------------
# ComplianceExclusionList.exclusion_reason
# ---------------------------------------------------------------------------


class TestExclusionReason:
    def test_returns_none_if_not_excluded(self) -> None:
        cel = _make_exclusion_list()
        assert cel.exclusion_reason("INFY") is None

    def test_returns_asm_reason(self) -> None:
        cel = _make_exclusion_list(asm=frozenset(["X"]))
        assert cel.exclusion_reason("X") == "ASM"

    def test_returns_multiple_reasons(self) -> None:
        cel = _make_exclusion_list(
            asm=frozenset(["X"]), ban=frozenset(["X"])
        )
        reason = cel.exclusion_reason("X")
        assert reason is not None
        assert "ASM" in reason
        assert "F&O ban" in reason


# ---------------------------------------------------------------------------
# Symbol extraction helpers
# ---------------------------------------------------------------------------


class TestSymbolParsers:
    def test_asm_extracts_symbol_key(self) -> None:
        data: list[dict[str, object]] = [{"symbol": "RELIANCE"}, {"symbol": "TATA"}]
        result = _symbols_from_asm(data)
        assert "RELIANCE" in result
        assert "TATA" in result

    def test_asm_handles_capital_symbol_key(self) -> None:
        data: list[dict[str, object]] = [{"Symbol": "hdfc"}]
        result = _symbols_from_asm(data)
        assert "HDFC" in result

    def test_esm_extracts_symbol(self) -> None:
        data: list[dict[str, object]] = [{"symbol": "YESBANK"}]
        assert "YESBANK" in _symbols_from_esm(data)

    def test_ban_extracts_symbol(self) -> None:
        data: list[dict[str, object]] = [{"symbol": "VEDL"}]
        assert "VEDL" in _symbols_from_ban(data)

    def test_mwpl_threshold_inclusion(self) -> None:
        data: list[dict[str, object]] = [
            {"symbol": "A", "pct_mwpl": "92.5"},
            {"symbol": "B", "pct_mwpl": "85.0"},
        ]
        result = _symbols_from_mwpl(data)
        assert "A" in result
        assert "B" not in result  # below 90%

    def test_mwpl_handles_numeric_pct(self) -> None:
        data: list[dict[str, object]] = [{"symbol": "C", "pct_mwpl": 95.0}]
        result = _symbols_from_mwpl(data)
        assert "C" in result

    def test_mwpl_skips_unparseable_pct(self) -> None:
        data: list[dict[str, object]] = [{"symbol": "D", "pct_mwpl": "N/A"}]
        result = _symbols_from_mwpl(data)
        assert "D" not in result

    def test_mwpl_missing_symbol_skipped(self) -> None:
        data: list[dict[str, object]] = [{"pct_mwpl": "95.0"}]
        result = _symbols_from_mwpl(data)
        assert len(result) == 0

    def test_empty_data_returns_empty(self) -> None:
        assert len(_symbols_from_asm([])) == 0
        assert len(_symbols_from_esm([])) == 0
        assert len(_symbols_from_ban([])) == 0
        assert len(_symbols_from_mwpl([])) == 0


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


class TestCacheHelpers:
    def test_cache_fresh_when_recent(self, tmp_path: Path) -> None:
        p = tmp_path / "test.json"
        p.write_text("[]")
        # Just written — should be fresh
        assert _is_cache_fresh(p) is True

    def test_cache_stale_when_old(self, tmp_path: Path) -> None:
        p = tmp_path / "test.json"
        p.write_text("[]")
        # Mock mtime to 25 hours ago
        old_time = time.time() - 25 * 3600
        import os

        os.utime(p, (old_time, old_time))
        assert _is_cache_fresh(p) is False

    def test_cache_missing_not_fresh(self, tmp_path: Path) -> None:
        p = tmp_path / "nonexistent.json"
        assert _is_cache_fresh(p) is False

    def test_read_cache_returns_list(self, tmp_path: Path) -> None:
        data = [{"symbol": "X"}]
        p = tmp_path / "cache.json"
        p.write_text(json.dumps(data))
        result = _read_cache(p)
        assert result == data

    def test_read_cache_invalid_json_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("not json")
        assert _read_cache(p) is None

    def test_read_cache_missing_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "absent.json"
        assert _read_cache(p) is None

    def test_write_cache_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "deep" / "nested" / "cache.json"
        _write_cache(p, [{"symbol": "Y"}])
        assert p.exists()
        assert json.loads(p.read_text()) == [{"symbol": "Y"}]


# ---------------------------------------------------------------------------
# NSEComplianceSource (mocked network)
# ---------------------------------------------------------------------------


class TestNSEComplianceSource:
    @patch("shared.universe.compliance._fetch_url")
    def test_fetch_returns_exclusion_list(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = [{"symbol": "TEST"}]
        source = NSEComplianceSource()
        result = source.fetch()
        assert isinstance(result, ComplianceExclusionList)
        assert result.fetched_at.tzinfo is not None

    @patch("shared.universe.compliance._get_category_data")
    def test_fetch_fail_open_on_network_error(
        self, mock_get: MagicMock
    ) -> None:
        # Patch _get_category_data (not _fetch_url) to bypass the file cache.
        mock_get.return_value = []
        source = NSEComplianceSource()
        result = source.fetch()
        # All sets empty — fail open
        assert len(result.asm_symbols) == 0
        assert len(result.esm_symbols) == 0
        assert len(result.ban_symbols) == 0
        assert len(result.mwpl_exceeded_symbols) == 0

    @patch("shared.universe.compliance._get_category_data")
    def test_symbols_populated_from_live(self, mock_get: MagicMock) -> None:
        # Patch _get_category_data (not _fetch_url) to bypass the file cache.
        mock_get.side_effect = [
            [{"symbol": "ASM1"}],  # asm
            [{"symbol": "ESM1"}],  # esm
            [{"symbol": "BAN1"}],  # ban
            [{"symbol": "MWPL1", "pct_mwpl": "91.0"}],  # mwpl
        ]
        source = NSEComplianceSource()
        result = source.fetch()
        assert "ASM1" in result.asm_symbols
        assert "ESM1" in result.esm_symbols
        assert "BAN1" in result.ban_symbols
        assert "MWPL1" in result.mwpl_exceeded_symbols


# ---------------------------------------------------------------------------
# load_compliance_list
# ---------------------------------------------------------------------------


class TestLoadComplianceList:
    @patch("shared.universe.compliance._fetch_url")
    def test_uses_default_source(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = []
        result = load_compliance_list()
        assert isinstance(result, ComplianceExclusionList)

    @patch("shared.universe.compliance._fetch_url")
    def test_accepts_custom_source(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = []
        custom_source = NSEComplianceSource()
        result = load_compliance_list(source=custom_source)
        assert isinstance(result, ComplianceExclusionList)
