"""Streamlit operational dashboard for the intraday trading system.

Run via: streamlit run dashboard/app.py
"""

from __future__ import annotations

import time

import streamlit as st

from dashboard.fetcher import (
    fetch_pnl,
    fetch_positions,
    fetch_signals,
    fetch_status,
    fetch_watchlist,
    post_kill,
    post_pause,
    post_resume,
)

_REFRESH_INTERVAL_S = 5

st.set_page_config(
    page_title="Trading System Dashboard",
    page_icon="📈",
    layout="wide",
)

st.title("Intraday Trading System — Operational Dashboard")

# ---------------------------------------------------------------------------
# Sidebar: controls and settings
# ---------------------------------------------------------------------------

st.sidebar.header("System Controls")
api_key_input = st.sidebar.text_input(
    "X-API-Key", type="password", help="Required for kill/pause/resume"
)

col_kill, col_pause, col_resume = st.sidebar.columns(3)
if col_kill.button("KILL", type="primary", use_container_width=True):
    if api_key_input:
        result = post_kill(api_key_input)
        if result.get("success"):
            st.sidebar.success("Kill switch triggered")
        else:
            st.sidebar.error(f"Failed: {result.get('reason')}")
    else:
        st.sidebar.warning("Enter API key first")

if col_pause.button("Pause", use_container_width=True):
    if api_key_input:
        result = post_pause(api_key_input)
        if result.get("success"):
            st.sidebar.success("Entries paused")
        else:
            st.sidebar.error(f"Failed: {result.get('reason')}")
    else:
        st.sidebar.warning("Enter API key first")

if col_resume.button("Resume", use_container_width=True):
    if api_key_input:
        result = post_resume(api_key_input)
        if result.get("success"):
            st.sidebar.success("Entries resumed")
        else:
            st.sidebar.error(f"Failed: {result.get('reason')}")
    else:
        st.sidebar.warning("Enter API key first")

st.sidebar.divider()
exchange_filter = st.sidebar.selectbox("Watchlist exchange", ["NSE", "ASX"])
auto_refresh = st.sidebar.checkbox("Auto-refresh (5 s)", value=True)

# ---------------------------------------------------------------------------
# Fetch data
# ---------------------------------------------------------------------------

status = fetch_status()
pnl = fetch_pnl()
positions = fetch_positions()
signals = fetch_signals()
watchlist = fetch_watchlist(str(exchange_filter))

# ---------------------------------------------------------------------------
# Status banner
# ---------------------------------------------------------------------------

mode = str(status.get("trading_mode", "PAPER"))
is_halted = bool(status.get("is_halted", False))
is_paused = bool(status.get("is_paused", False))
is_degraded = bool(status.get("is_degraded", False))

banner_parts: list[str] = [f"Mode: **{mode}**"]
if is_halted:
    banner_parts.append("🔴 **HALTED**")
elif is_paused:
    banner_parts.append("🟡 **PAUSED**")
else:
    banner_parts.append("🟢 Running")
if is_degraded:
    banner_parts.append("⚠️ Degraded (exit-only)")

st.info("  |  ".join(banner_parts))

# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------

def _f(v: object, default: float = 0.0) -> float:
    return float(v) if isinstance(v, (int, float)) else default


def _i(v: object, default: int = 0) -> int:
    return int(v) if isinstance(v, (int, float)) else default


k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Regime", str(status.get("regime") or "-"))
k2.metric(
    "P&L Today",
    f"${_f(pnl.get('total_pnl')):,.0f}",
    f"{_f(pnl.get('total_pnl_pct')):.2f}%",
)
k3.metric("Open Positions", _i(status.get("open_positions_count")))
k4.metric("Signals Today", _i(status.get("signals_today")))
k5.metric("Recon Mismatches", _i(status.get("reconciliation_mismatches")))

st.divider()

# ---------------------------------------------------------------------------
# Main panels
# ---------------------------------------------------------------------------

col_left, col_right = st.columns([3, 2])

with col_left:
    st.subheader("Open Positions")
    if positions:
        st.table(positions)
    else:
        st.caption("No open positions.")

    st.subheader("Recent Signals")
    if signals:
        st.table(signals)
    else:
        st.caption("No signals received today.")

with col_right:
    st.subheader(f"Watchlist — {exchange_filter}")
    if watchlist:
        st.table(watchlist)
    else:
        st.caption("Watchlist not yet published.")

# ---------------------------------------------------------------------------
# Auto-refresh
# ---------------------------------------------------------------------------

if auto_refresh:
    time.sleep(_REFRESH_INTERVAL_S)
    st.rerun()
