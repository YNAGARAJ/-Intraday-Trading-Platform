"""M10 Sentiment & News Agent — market indicator scrapers.

Fetches India VIX, NIFTY put-call ratio, and FII/DII provisional trading
data from NSE public APIs.  All functions are fail-open: they return ``None``
on any network or parse failure so the SentimentAgent can continue without
blocking on live market data availability.

Public API
----------
fetch_india_vix()  → VIXData | None
fetch_fii_dii()    → FIIDIIData | None
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import cast

import structlog

from shared.sentiment.models import FIIDIIData, VIXData

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# NSE API endpoints (public, no auth required; require cookie bootstrap)
# ---------------------------------------------------------------------------

_NSE_HOME: str = "https://www.nseindia.com/"
_NSE_ALL_INDICES: str = "https://www.nseindia.com/api/allIndices"
_NSE_FII_DII: str = "https://www.nseindia.com/api/fiidiiTradeReact"
_NSE_OPTION_CHAIN: str = (
    "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
)

_USER_AGENT: str = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS: dict[str, str] = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/",
}
_TIMEOUT_SECONDS: int = 15
_VIX_INDEX_NAME: str = "INDIA VIX"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_nse_cookie() -> str:
    """Perform a GET on the NSE homepage to obtain a session cookie.

    Returns:
        Cookie string for subsequent API calls, or empty string on failure.
    """
    try:
        req = urllib.request.Request(_NSE_HOME, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            raw: str = cast(str, resp.headers.get("Set-Cookie", ""))
            return raw.split(";")[0] if raw else ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("nse_home_fetch_failed", error=str(exc))
        return ""


def _fetch_nse_json(url: str, cookie: str) -> object | None:
    """Fetch JSON from an NSE API endpoint with the provided session cookie.

    Returns:
        Parsed JSON object, or ``None`` on any failure.
    """
    headers = dict(_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            return cast(object, json.loads(resp.read()))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        logger.warning("nse_api_fetch_failed", url=url, error=str(exc))
        return None


# ---------------------------------------------------------------------------
# India VIX
# ---------------------------------------------------------------------------


def fetch_india_vix() -> VIXData | None:
    """Fetch the current India VIX level from NSE's allIndices API.

    Also attempts to fetch the NIFTY put-call ratio from the option chain.
    Fails open — returns ``None`` if any network or parse error occurs.

    Returns:
        ``VIXData`` with current VIX and optional PCR, or ``None`` on failure.
    """
    now = datetime.now(tz=timezone.utc)
    cookie = _get_nse_cookie()
    data = _fetch_nse_json(_NSE_ALL_INDICES, cookie)

    if data is None:
        return None

    # Response format: {"data": [{"indexName": "INDIA VIX", "last": "14.5", ...}, ...]}
    indices_list: list[object] = []
    if isinstance(data, dict):
        raw = data.get("data")
        if isinstance(raw, list):
            indices_list = raw

    vix_val: float | None = None
    for entry in indices_list:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("indexName", "")).upper() == _VIX_INDEX_NAME:
            try:
                vix_val = float(str(entry.get("last", "")))
            except (ValueError, TypeError):
                pass
            break

    if vix_val is None:
        logger.warning("india_vix_not_found_in_response")
        return None

    # Best-effort PCR from NIFTY option chain
    pcr = _fetch_put_call_ratio(cookie)

    logger.info("india_vix_fetched", vix=vix_val, pcr=pcr)
    try:
        return VIXData(vix=vix_val, put_call_ratio=pcr, fetched_at=now)
    except ValueError as exc:
        logger.warning("india_vix_validation_failed", error=str(exc))
        return None


def _fetch_put_call_ratio(cookie: str) -> float | None:
    """Compute NIFTY PCR from the option chain (total_put_OI / total_call_OI).

    Returns:
        PCR as a float, or ``None`` if the option chain fetch fails.
    """
    data = _fetch_nse_json(_NSE_OPTION_CHAIN, cookie)
    if data is None or not isinstance(data, dict):
        return None

    filtered = data.get("filtered", {})
    if not isinstance(filtered, dict):
        return None

    try:
        total_ce_oi = float(str(filtered.get("CE", {}).get("totOI", 0) or 0))
        total_pe_oi = float(str(filtered.get("PE", {}).get("totOI", 0) or 0))
    except (ValueError, TypeError, AttributeError):
        return None

    if total_ce_oi <= 0.0:
        return None

    return round(total_pe_oi / total_ce_oi, 4)


# ---------------------------------------------------------------------------
# FII / DII
# ---------------------------------------------------------------------------


def fetch_fii_dii() -> FIIDIIData | None:
    """Fetch provisional FII and DII daily trading data from NSE.

    NSE's ``fiidiiTradeReact`` endpoint returns intraday provisional numbers
    updated approximately every 30 minutes during market hours.  The returned
    values are in INR crores (negative = net sell).

    Fails open — returns ``None`` on any network or parse error.

    Returns:
        ``FIIDIIData`` for today, or ``None`` on failure.
    """
    now = datetime.now(tz=timezone.utc)
    today = date.today()
    cookie = _get_nse_cookie()
    data = _fetch_nse_json(_NSE_FII_DII, cookie)

    if data is None or not isinstance(data, list):
        logger.warning("fii_dii_unexpected_response", type=type(data).__name__)
        return None

    fii_net: float | None = None
    dii_net: float | None = None

    for row in data:
        if not isinstance(row, dict):
            continue
        category = str(row.get("category", "")).upper()
        try:
            net_str = str(row.get("netValue", row.get("net", "0")) or "0")
            net_val = float(net_str.replace(",", ""))
        except (ValueError, TypeError):
            continue

        if "FII" in category or "FPI" in category:
            fii_net = net_val
        elif "DII" in category:
            dii_net = net_val

    if fii_net is None or dii_net is None:
        logger.warning(
            "fii_dii_incomplete",
            fii_found=fii_net is not None,
            dii_found=dii_net is not None,
        )
        return None

    logger.info(
        "fii_dii_fetched",
        fii_net_crore=fii_net,
        dii_net_crore=dii_net,
    )
    try:
        return FIIDIIData(
            date=today,
            fii_net_crore=fii_net,
            dii_net_crore=dii_net,
            fetched_at=now,
        )
    except ValueError as exc:
        logger.warning("fii_dii_validation_failed", error=str(exc))
        return None
