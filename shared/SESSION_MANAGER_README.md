# M02 — Market Calendar & Session Manager

NSE and ASX holiday calendars, session state machine (CLOSED → PRE_MARKET → OPEN → SNAPSHOT_WINDOW → APPROACHING_CLOSE → CLOSED), snapshot-window flag, and ASX staggered-open registry.

Module lives at `shared/session_manager.py` (single-file module).

## Standalone usage

```bash
python -m shared.session_manager
```

No `APP_ID` required — both exchanges are reported in one run.

## Environment variables

None required for standalone run. Holiday cache written to `shared/data/holiday_cache/` (gitignored).

## Key APIs

- `SessionStateMachine(region_config)` — `.get_state(dt)` → `SessionState`
- `SquareOffScheduler(region_config)` — `.is_square_off_due(dt)` → `bool`
- `HolidayCalendar(source)` — `.is_trading_day(date)` → `bool`; raises `CalendarUnavailableError` if weekday status unknown
- `get_ticker_open_time(symbol, market_date, tz)` → `datetime` — ASX staggered open for symbol's alphabetical group
- `NSEHolidaySource`, `ASXHolidaySource` — live fetch + local JSON cache (7-day TTL)

## Session states

`CLOSED` · `PRE_MARKET` · `OPEN` · `SNAPSHOT_WINDOW` (India 14:45–15:10) · `APPROACHING_CLOSE`

## Known limitations

ASX holiday endpoint currently returns 404 — `CalendarUnavailableError` raised on weekdays until a valid endpoint is confirmed (ADR-006, fails closed by design). NSE endpoint confirmed working.

## Example output

```
{"exchange": "NSE", "session_state": "CLOSED", "snapshot_window_active": false,
 "event": "session_state", "level": "info"}
{"exchange": "ASX", "error": "ASX holiday fetch failed: 404 ...",
 "event": "session_state_unavailable", "level": "error"}
{"symbol": "BHP", "group_open_at": "2026-07-01T10:00:00+10:00",
 "event": "asx_staggered_open_example", "level": "info"}
```
