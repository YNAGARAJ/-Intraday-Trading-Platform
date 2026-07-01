"""M09 compliance exclusion list: NSE ASM/ESM/ban/MWPL fetchers with JSON cache.

Design decisions:
- Fail-open per category: if a cached/live fetch fails, that category is treated
  as empty (no exclusions from that list).  A warning is logged.
- M13 is the hard execution block; M09 is best-effort pre-filtering only.
- Cache files are JSON, stored in COMPLIANCE_CACHE_DIR (gitignored).
- MWPL (Market Wide Position Limit) threshold: if OI% ≥ 90% the stock is in the
  F&O ban period; we also exclude any MWPL-exceeded instruments.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import structlog

from shared.core.constants import (
    COMPLIANCE_CACHE_DIR,
    COMPLIANCE_CACHE_MAX_AGE_HOURS,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# NSE public endpoints (no auth required for these lists)
_NSE_ASM_URL = (
    "https://nseindia.com/api/reportASM"
)
_NSE_ESM_URL = (
    "https://nseindia.com/api/reportESM"
)
_NSE_BAN_URL = (
    "https://nseindia.com/api/fo-sec-ban-list"
)
_NSE_MWPL_URL = (
    "https://nseindia.com/api/reportMwpl"
)

_CACHE_FILE_NAMES: dict[str, str] = {
    "asm": "nse_asm.json",
    "esm": "nse_esm.json",
    "ban": "nse_ban.json",
    "mwpl": "nse_mwpl.json",
}

# MWPL OI utilisation threshold for exclusion (90% as per NSE F&O ban rules)
_MWPL_OI_THRESHOLD_PCT: float = 90.0


@dataclass(frozen=True)
class ComplianceExclusionList:
    """Aggregated SEBI/NSE compliance exclusion data for pre-market filtering.

    All symbol sets are upper-case canonical tickers.

    Args:
        asm_symbols:          Symbols on the Additional Surveillance Measure list.
        esm_symbols:          Symbols on the Enhanced Surveillance Measure list.
        ban_symbols:          Symbols in the F&O ban period (OI ≥ 95% MWPL).
        mwpl_exceeded_symbols: Symbols where OI ≥ 90% of MWPL (pre-ban warning).
        fetched_at:           UTC timestamp of the most recent successful fetch.
    """

    asm_symbols: frozenset[str]
    esm_symbols: frozenset[str]
    ban_symbols: frozenset[str]
    mwpl_exceeded_symbols: frozenset[str]
    fetched_at: datetime

    def is_excluded(self, symbol: str) -> bool:
        """Return True if the symbol appears on any compliance exclusion list."""
        sym = symbol.upper()
        return (
            sym in self.asm_symbols
            or sym in self.esm_symbols
            or sym in self.ban_symbols
            or sym in self.mwpl_exceeded_symbols
        )

    def exclusion_reason(self, symbol: str) -> str | None:
        """Return a human-readable reason string or None if not excluded."""
        sym = symbol.upper()
        reasons: list[str] = []
        if sym in self.asm_symbols:
            reasons.append("ASM")
        if sym in self.esm_symbols:
            reasons.append("ESM")
        if sym in self.ban_symbols:
            reasons.append("F&O ban")
        if sym in self.mwpl_exceeded_symbols:
            reasons.append("MWPL≥90%")
        return ", ".join(reasons) if reasons else None


def _cache_path(category: str) -> Path:
    """Return the Path for a compliance category's JSON cache file."""
    return Path(COMPLIANCE_CACHE_DIR) / _CACHE_FILE_NAMES[category]


def _is_cache_fresh(path: Path) -> bool:
    """Return True if the cache file exists and is within the max-age window."""
    if not path.exists():
        return False
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds < COMPLIANCE_CACHE_MAX_AGE_HOURS * 3600


def _read_cache(path: Path) -> list[dict[str, object]] | None:
    """Read and parse the JSON cache file; return None on any error."""
    try:
        with path.open() as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("compliance_cache_read_failed", path=str(path), error=str(exc))
    return None


def _write_cache(path: Path, data: list[dict[str, object]]) -> None:
    """Write data to the cache file, creating directories as needed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as fh:
            json.dump(data, fh)
    except OSError as exc:
        logger.warning("compliance_cache_write_failed", path=str(path), error=str(exc))


def _fetch_url(url: str) -> list[dict[str, object]] | None:
    """Fetch JSON from an NSE API endpoint; return None on any network/parse error.

    NSE requires a browser-like User-Agent and the nseindia.com cookie (set by
    the homepage) for most API endpoints.  Without the cookie, the API returns
    a 403 or redirect.  We do a best-effort two-step: first GET the homepage to
    obtain a session cookie, then GET the data URL with that cookie.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/",
    }
    # Bootstrap the NSE session cookie
    cookie: str = ""
    try:
        req_home = urllib.request.Request(
            "https://www.nseindia.com/", headers=headers
        )
        with urllib.request.urlopen(req_home, timeout=10) as resp:
            raw_cookie = resp.headers.get("Set-Cookie", "")
            cookie = raw_cookie.split(";")[0] if raw_cookie else ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("compliance_nse_home_fetch_failed", error=str(exc))

    try:
        fetch_headers = dict(headers)
        if cookie:
            fetch_headers["Cookie"] = cookie
        req = urllib.request.Request(url, headers=fetch_headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
        # NSE APIs wrap the list in {"data": [...]} or return a bare list
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return payload["data"]  # type: ignore[no-any-return]
    except Exception as exc:  # noqa: BLE001
        logger.warning("compliance_nse_fetch_failed", url=url, error=str(exc))
    return None


def _get_category_data(
    category: str, url: str
) -> list[dict[str, object]]:
    """Return list data for a compliance category, using cache when fresh.

    Falls back to empty list (fail-open) if both cache and live fetch fail.
    """
    path = _cache_path(category)
    if _is_cache_fresh(path):
        cached = _read_cache(path)
        if cached is not None:
            return cached

    logger.info("compliance_fetching_live", category=category)
    live = _fetch_url(url)
    if live is not None:
        _write_cache(path, live)
        return live

    # Live fetch failed — try stale cache before giving up
    stale = _read_cache(path)
    if stale is not None:
        logger.warning(
            "compliance_using_stale_cache",
            category=category,
            path=str(path),
        )
        return stale

    logger.warning("compliance_data_unavailable", category=category)
    return []


def _symbols_from_asm(data: list[dict[str, object]]) -> frozenset[str]:
    """Extract symbol set from NSE ASM API response."""
    symbols: set[str] = set()
    for row in data:
        sym = row.get("symbol") or row.get("Symbol") or row.get("scrip_cd")
        if isinstance(sym, str) and sym:
            symbols.add(sym.upper())
    return frozenset(symbols)


def _symbols_from_esm(data: list[dict[str, object]]) -> frozenset[str]:
    """Extract symbol set from NSE ESM API response."""
    symbols: set[str] = set()
    for row in data:
        sym = row.get("symbol") or row.get("Symbol") or row.get("scrip")
        if isinstance(sym, str) and sym:
            symbols.add(sym.upper())
    return frozenset(symbols)


def _symbols_from_ban(data: list[dict[str, object]]) -> frozenset[str]:
    """Extract symbol set from NSE F&O ban list response."""
    symbols: set[str] = set()
    for row in data:
        sym = row.get("symbol") or row.get("Symbol")
        if isinstance(sym, str) and sym:
            symbols.add(sym.upper())
    return frozenset(symbols)


def _symbols_from_mwpl(data: list[dict[str, object]]) -> frozenset[str]:
    """Extract symbols where OI utilisation ≥ 90% from MWPL response."""
    symbols: set[str] = set()
    for row in data:
        sym = row.get("symbol") or row.get("Symbol")
        raw_pct = row.get("pct_mwpl") or row.get("mwplPct") or row.get("utilPct")
        if not (isinstance(sym, str) and sym):
            continue
        try:
            pct = float(str(raw_pct).replace("%", ""))
        except (ValueError, TypeError):
            continue
        if pct >= _MWPL_OI_THRESHOLD_PCT:
            symbols.add(sym.upper())
    return frozenset(symbols)


class NSEComplianceSource:
    """Fetches and caches NSE compliance lists for pre-market universe filtering.

    Uses a 24-hour JSON file cache per category.  All fetches are fail-open:
    a failed fetch for any category returns an empty set for that category and
    logs a warning, but does NOT block the rest of the pipeline.  M13 is the
    hard enforcement point at order execution time.
    """

    def fetch(self) -> ComplianceExclusionList:
        """Fetch all four compliance categories and return a ComplianceExclusionList.

        Returns:
            Populated ComplianceExclusionList with UTC fetched_at timestamp.
        """
        asm_data = _get_category_data("asm", _NSE_ASM_URL)
        esm_data = _get_category_data("esm", _NSE_ESM_URL)
        ban_data = _get_category_data("ban", _NSE_BAN_URL)
        mwpl_data = _get_category_data("mwpl", _NSE_MWPL_URL)

        return ComplianceExclusionList(
            asm_symbols=_symbols_from_asm(asm_data),
            esm_symbols=_symbols_from_esm(esm_data),
            ban_symbols=_symbols_from_ban(ban_data),
            mwpl_exceeded_symbols=_symbols_from_mwpl(mwpl_data),
            fetched_at=datetime.now(tz=timezone.utc),
        )


def load_compliance_list(
    source: NSEComplianceSource | None = None,
) -> ComplianceExclusionList:
    """Load the compliance exclusion list from cache or live fetch.

    Args:
        source: Optional custom source for testing; defaults to NSEComplianceSource.

    Returns:
        ComplianceExclusionList (fail-open: empty sets if all sources fail).
    """
    if source is None:
        source = NSEComplianceSource()
    return source.fetch()


# Ensure the cache directory exists at import time so CLI/tests don't fail
# on first run even when the directory was never created.
os.makedirs(COMPLIANCE_CACHE_DIR, exist_ok=True)
