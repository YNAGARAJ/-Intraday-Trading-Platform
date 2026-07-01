# Architecture Decisions

This log records every non-trivial engineering decision made during the build, in addition to the
items the spec (`MASTER_BUILD_PROMPT_FINAL.MD`) explicitly requires to be recorded here (DR
posture for total instance/AZ loss per RULE 5; any other open compliance/risk decision deferred
to the user per RULE 10).

## Entry template

```
### ADR-NNN: <short title>
- **Date:** YYYY-MM-DD
- **Module:** MXX or N/A
- **Context:** what problem/ambiguity prompted this decision
- **Decision:** what was decided
- **Alternatives considered:** options weighed and why they were not chosen
- **Consequences:** trade-offs, follow-ups, or constraints this creates downstream
```

---

### ADR-001: Build origin and spec authority
- **Date:** 2026-06-30
- **Module:** N/A
- **Context:** This is a fresh build with no prior SPEC v1 history to reconcile against. The
  project starts directly from `MASTER_BUILD_PROMPT_FINAL.MD` (Revision 2), which is treated as
  the single source of truth for every requirement, rule, and module spec for the remainder of
  the build.
- **Decision:** `MASTER_BUILD_PROMPT_FINAL.MD` is authoritative and will not be paraphrased into
  other tracking files in a way that could drift out of sync — `CLAUDE.md` only summarizes for
  navigation and always defers to the spec file itself when in doubt. No code changes were made
  in this entry; it exists purely to anchor the decision log at the start of the build.
- **Alternatives considered:** N/A — no prior spec version exists to reconcile.
- **Consequences:** All future ADR entries are additive to this log; the spec file itself is
  never edited or renamed during the build.

---

### ADR-002: DR posture for total EC2/AZ instance loss
- **Date:** 2026-06-30
- **Module:** N/A (applies system-wide; revisited at M23)
- **Context:** RULE 5 requires an explicit, recorded DR posture for total instance/AZ loss, since
  in-process Redis/SQLite buffering does not survive the host dying. Left undecided by the spec
  for the user to choose.
- **Decision:** **Accepted risk, manual restart, no warm standby.** On total instance/AZ loss,
  the system goes down; recovery is a manual restart. State recovery relies on PostgreSQL (durable
  trade/audit log) and the SQLite failover buffer for anything not yet flushed. No automated
  failover or standby compute is built in this phase.
- **Alternatives considered:** Warm standby in a second AZ (replicated Redis/Postgres, standby
  compute, automated failover) — rejected for now as disproportionate cost/complexity while the
  system is in build/paper-trading phase with no live capital at risk. Deferring the decision to
  M23 — rejected in favor of deciding now so M01's infra scaffolding (docker-compose, AWS scripts)
  is built consistent with the chosen posture from the start, rather than retrofitted later.
- **Consequences:** No multi-AZ redundancy work is in scope for M01–M23 as currently planned. This
  posture **must be re-reviewed before live deployment** (tracked on the spec's own pre-flight
  checklist) — if the live-trading risk profile changes, this ADR should be superseded rather than
  silently ignored.

---

### ADR-003: TRADING_MODE default confirmation
- **Date:** 2026-06-30
- **Module:** N/A (applies system-wide)
- **Context:** RULE 1 mandates paper trading as the always-default mode; spec Step 10 ("Ask,
  never assume") called for explicit confirmation since this gates every module's safety posture.
- **Decision:** Confirmed. `TRADING_MODE=PAPER` is the default in every config file, `.env.example`,
  docker-compose service definition, and test fixture, in every module, for the entire build.
  `TRADING_MODE=LIVE` is never a default anywhere and is only ever set by explicit user instruction
  at actual deploy time, gated by both `TRADING_MODE=LIVE` and `LIVE_TRADING_CONFIRMED=true`.
- **Alternatives considered:** Adding a further manual gate beyond the two env vars (e.g., a
  separate CLI confirmation flag or manual code-review checklist item before any LIVE order) —
  user selected the standard two-env-var gate as sufficient for now; an additional gate can be
  layered in later (e.g., at M14/M23) without contradicting this decision.
- **Consequences:** Every module's `.env.example` and config defaults must be checked against this
  before being marked "complete" in PROGRESS.md.

---

### ADR-004: pyproject.toml pin drift, and scoping Dockerfile.base to M01's actual imports
- **Date:** 2026-06-30
- **Module:** M01
- **Context:** Building `infra/docker/Dockerfile.base` per the spec's literal description ("Pre-
  compiled TA-Lib Base Layer" installing the full pinned `pyproject.toml` manifest via Poetry) hit
  three consecutive, distinct build failures:
  1. `pandas-ta==0.3.14b0` (the spec's pin) does not exist on PyPI at all -- confirmed via the
     PyPI JSON API. The package's old 0.3.x/0.4.0-0.4.66 release line appears to have been
     removed/renumbered upstream; only `0.4.67b0` and `0.4.71b0` are published today.
  2. After repinning to `pandas-ta==0.4.71b0`, Poetry's resolver reported that release requires
     Python `>=3.12`, conflicting with the Dockerfile's `python:3.11-slim` base (pyproject.toml's
     `python = "^3.11"` constraint already permits 3.12, so the base image was bumped to
     `python:3.12-slim` instead of re-pinning pandas-ta again).
  3. The TA-Lib 0.4.0 C source release's bundled `gen_code` build tool fails to link
     (`undefined reference to 'main'`) against the GCC shipped in `python:3.12-slim`'s current
     Debian base -- a known class of issue with TA-Lib's ~2007-era autotools build script on
     modern toolchains, unrelated to any of this project's own pins.
  This is exactly the situation the spec itself anticipated ("Re-verify each pin against current
  PyPI releases at build time") and the situation RULE 9 asks for self-restraint on ("if the same
  error type recurs more than twice, stop ... before a third attempt"). None of M01's own code
  (`shared/core/*`, `shared/proto/*`, `apps/*/main.py`) imports TA-Lib, pandas-ta, TensorFlow,
  Prophet, vectorbt, mlflow, langchain/langgraph, or any broker SDK -- those belong to M04, M07,
  M08, M09, M14-M16 respectively, none of which are built yet.
- **Decision:** `pyproject.toml` remains the full, authoritative pinned manifest (with the
  `pandas-ta` pin corrected to `0.4.71b0` and an inline comment explaining the deviation).
  `infra/docker/Dockerfile.base`, for now, installs only the exact-pinned subset M01's code
  actually imports (`pydantic`, `pydantic-settings`, `pyyaml`, `structlog`, `redis`, `protobuf`,
  `psycopg2-binary`) via direct `pip install`, *not* `poetry install` of the complete graph, and
  drops the TA-Lib C source compile step entirely. `docker build -f infra/docker/Dockerfile.base`
  now succeeds and the app images (`apps/india/Dockerfile`, `apps/australia/Dockerfile`) build and
  run on top of it.
- **Alternatives considered:** (a) Keep fighting the full Poetry resolve + TA-Lib compile until
  every pin in the ~30-package manifest is verified and every toolchain issue is patched --
  rejected as disproportionate effort for a module whose own code uses none of it, and a poor use
  of an M01 turn versus letting each owning module (M04 for TA-Lib, M07-M09 for the ML stack)
  resolve and test its own dependencies when it's actually being built, where any fix can be
  properly verified against real usage. (b) Strip the heavy packages out of `pyproject.toml`
  entirely until needed -- rejected because the spec wants the full manifest declared upfront as
  the system's dependency contract; removing entries would understate the eventual footprint and
  contradict the spec's own dependency table.
- **Consequences:** `poetry.lock` is not yet generated or committed -- deferred until a module
  that needs the full graph is built and the lock can be produced against a working resolution
  (tracked as a known follow-up in PROGRESS.md's M01 row). TA-Lib C library compilation needs a
  real fix (e.g., a newer source fork, a prebuilt wheel, or a build patch) when M04 is built --
  tracked as a known M04 follow-up, not silently deferred. Any module that needs a package outside
  M01's installed subset must extend `Dockerfile.base` (or add its own install step) when it's
  built, and re-verify that package's pin against PyPI at that time per the spec's own guidance.

---

### ADR-005: Session state machine boundaries (SNAPSHOT_WINDOW / APPROACHING_CLOSE)
- **Date:** 2026-06-30
- **Module:** M02
- **Context:** The spec defines the session state enum (CLOSED -> PRE_MARKET -> OPEN ->
  SNAPSHOT_WINDOW -> APPROACHING_CLOSE -> CLOSED) and gives the SEBI snapshot window as a single
  14:45-15:30 IST band, but doesn't explicitly say where SNAPSHOT_WINDOW ends and
  APPROACHING_CLOSE begins within that band, or what Australia (which has no snapshot-window
  concept at all) does in its place. Note this is a state-machine *boundary* decision, not the
  RULE-2-relevant question of whether entries are blocked vs. merely reduced-size during the
  window -- that's M12's job (position sizing) and M11's job (Gate 7's 30-minute closing-window
  check), neither built yet, so it wasn't treated as a RULE-10 compliance/risk question requiring
  the user's input.
- **Decision:** For India: SNAPSHOT_WINDOW = [snapshot_window_start_local, square_off_local) =
  [14:45, 15:10); APPROACHING_CLOSE = [square_off_local, market_close_local) = [15:10, 15:30).
  This reuses `square_off_local` (already a RegionConfig field) as the natural boundary, rather
  than inventing a new config field. For Australia (`snapshot_window_start_local` is `None`):
  SNAPSHOT_WINDOW is skipped entirely; OPEN runs straight to APPROACHING_CLOSE at
  `square_off_local` (15:50 AEST). `RegionConfig` gained two new fields to support this:
  `pre_market_local` (infra scale-on time, was previously only implicit) and
  `snapshot_window_start_local: str | None` (India-only).
- **Alternatives considered:** Treating the post-close ASX residual-clearance window
  (16:11-16:21:30 AEST) as a 6th session state -- rejected; the spec's own `TradingSystemState`
  schema defines exactly 5 states, and the post-close clearance is a distinct procedural concept
  (M17 reconciliation territory) better exposed as its own flag when that module is built, not
  forced into this enum.
- **Consequences:** M12 (risk sizing) and M11 (Gate 7) must read `SessionStateMachine` /
  `SquareOffScheduler` for their own timing needs rather than re-deriving market-hours math
  independently. If a future module needs the post-close clearance window as a flag, add it
  there rather than overloading `SessionState`.

---

### ADR-006: Holiday calendar fails closed; live-fetch endpoints are best-effort
- **Date:** 2026-06-30
- **Module:** M02
- **Context:** The spec calls for "auto-fetched weekly" NSE/ASX holiday calendars. Verified during
  this build: NSE's site/API rejects bare requests (confirmed blocked via raw `curl`, but a
  proper browser-like `requests.Session` with cookie bootstrap **does** work -- it successfully
  fetched real 2026 NSE holiday data during this build). ASX has no confirmed stable public JSON
  API for trading holidays (the implemented endpoint currently 404s; the only verified-working
  ASX resource is an HTML calendar page, not a clean API). Holiday correctness is genuinely
  risk-relevant (trading on an actual holiday, or refusing to trade on an actual trading day), so
  guessing wrong is worse than failing visibly.
- **Decision:** `HolidayCalendar` fails closed (RULE 2 spirit): weekend closure is always
  resolvable with zero calendar data (no fetch needed). Weekday holiday status requires data from
  cache or a live fetch; if a weekday's status truly can't be determined (no cache, fetch fails),
  `is_trading_day`/`get_state` raise `CalendarUnavailableError` rather than silently assuming the
  market is open. No hand-curated static holiday list was added as a fallback -- fabricating
  specific holiday dates from training data without a verified source would itself be a
  compliance-relevant correctness risk, worse than a visible, logged failure. `NSEHolidaySource`
  and `ASXHolidaySource` are real, working implementations (not stubs), with local JSON caching
  (`shared/data/holiday_cache/`, gitignored) refreshed weekly (`HOLIDAY_CACHE_MAX_AGE_DAYS=7`); a
  stale cache is preferred over a hard failure if a live refetch fails but prior data exists.
- **Alternatives considered:** Shipping a static fallback list of guessed 2026 holidays --
  rejected per the reasoning above. Treating ASX's 404 as something to keep guessing endpoints
  for indefinitely -- rejected as disproportionate for M02; the fail-closed path already produces
  correct, safe, visible behavior (demonstrated live via `python -m shared.session_manager`), and
  the real endpoint can be corrected later without changing any calling code (only
  `ASXHolidaySource.HOLIDAY_API_URL`/parsing).
- **Consequences:** Until ASX's real holiday endpoint is found/confirmed, `SessionStateMachine`
  for Australia will raise `CalendarUnavailableError` on every weekday (verified live during this
  build). This is a known, visible limitation, not a silent gap -- tracked in PROGRESS.md. NSE's
  endpoint is confirmed working as of this build but, per the spec's own guidance on regulatory/
  external-data citations, should be periodically re-verified, not assumed permanently stable.

---

### ADR-007: ohlcv_1m stores finest-available granularity, not strictly 1-minute bars
- **Date:** 2026-06-30
- **Module:** M03
- **Context:** The spec's own M03 VERIFY command asks for a 30-day backfill of RELIANCE.NS
  queried back as 5-minute candles. Yahoo Finance (the backfill source) only serves 1-minute
  intraday data for the trailing ~7 days; ranges beyond that require requesting a coarser
  interval (5m, available up to ~60 days). Meanwhile TimescaleDB continuous aggregates
  (`ohlcv_5m`/`ohlcv_15m`/`ohlcv_1h`) are read-only materialized views computed from `ohlcv_1m` --
  there is no way to INSERT directly into them, so a coarse-granularity backfill can't write
  "5-minute data" into a separate writable 5m table even if one existed.
- **Decision:** `ohlcv_1m` is treated as "the finest-grained OHLCV data actually available for
  this bucket," not literally "exactly one row per calendar minute, always." Live ingestion (M16)
  will write genuine 1-minute rows; the yfinance backfill utility, when only 5-minute granularity
  is available (any backfill > `ONE_MINUTE_MAX_BACKFILL_DAYS` = 7 days), writes one row per
  5-minute bucket instead. The continuous aggregates still produce correct results in both cases,
  because `time_bucket()` + `first/max/min/last/sum` aggregate whatever rows exist in a bucket --
  a bucket with a single coarse row reproduces that row's own OHLC values exactly (verified by
  `test_5m_aggregate_reflects_single_row_bucket_exactly`), and a bucket with several genuine
  1-minute rows aggregates them normally (verified by
  `test_5m_continuous_aggregate_rolls_up_1m_rows_correctly`).
- **Alternatives considered:** Adding separate directly-writable `ohlcv_5m_raw` style tables for
  backfilled data, distinct from the continuous-aggregate-derived `ohlcv_5m` -- rejected as it
  would mean two different code paths (and two different table sets) compute "5-minute candles"
  depending on data source, contradicting the spec's explicit "Continuous aggregates: 1m -> 5m ->
  15m -> 1h" design and adding real complexity for a problem the bucket semantics already solve.
- **Consequences:** Code reading `ohlcv_1m` directly (rather than through the timeframe-aware
  `OHLCVRepository.query_candles`) must not assume every calendar minute has a row, or that rows
  are exactly 60 seconds apart -- only `query_candles(..., "1m", ...)` on freshly-ingested live
  data has that guarantee; backfilled historical ranges do not.

---

### ADR-008: Continuous aggregates use materialized_only=false (real-time aggregation)
- **Date:** 2026-06-30
- **Module:** M03
- **Context:** Verified directly against a live TimescaleDB 2.14.0 container: continuous
  aggregates created with plain `WITH (timescaledb.continuous)` defaulted to
  `materialized_only = true` in this version, meaning queries against `ohlcv_5m` etc. returned
  zero rows for data inserted into `ohlcv_1m` since the last scheduled refresh -- confirmed by
  inserting 5 rows into `ohlcv_1m` and immediately querying `ohlcv_5m`, which returned 0 rows
  until the setting was corrected. For a system whose signal generation (M11) and indicators
  (M04) need current candles, not candles as-of-the-last-refresh-policy-run, this default is
  wrong.
- **Decision:** All three continuous aggregates (`ohlcv_5m`, `ohlcv_15m`, `ohlcv_1h`) are created
  with `WITH (timescaledb.continuous, timescaledb.materialized_only = false)`, enabling real-time
  aggregation: queries merge materialized chunks with a live computation over any not-yet-
  materialized raw data, so a row inserted into `ohlcv_1m` is immediately visible through the
  rolled-up views without waiting for `add_continuous_aggregate_policy`'s `schedule_interval` to
  fire. Re-verified after the fix: the same insert-then-query-immediately test now returns the
  correct aggregated row (confirmed live).
- **Alternatives considered:** Leaving `materialized_only = true` and having callers explicitly
  `CALL refresh_continuous_aggregate(...)` before querying -- rejected as it pushes a
  TimescaleDB-specific operational detail onto every caller (M04, M11, M21, ...) and reintroduces
  exactly the kind of "candle data lags reality" bug this system can't tolerate on the signal
  path.
- **Consequences:** Real-time aggregation has a small per-query cost for the unmaterialized tail
  (merging raw rows at query time) -- acceptable here since OHLCV queries are not on the < 100ms
  pure-Python signal hot path (RULE 4); they're called by indicator/signal code before that hot
  path runs, not inside it.

---

### ADR-009: TA-Lib resolved via prebuilt wheel; pandas-ta dropped in favor of NumPy/pandas
- **Date:** 2026-06-30
- **Module:** M04
- **Context:** ADR-004 (M01) deferred TA-Lib to M04 after the spec's pinned `ta-lib==0.4.28`
  failed to build from source -- the bundled C library's `gen_code` tool doesn't link against
  modern GCC. On revisiting for M04: `pip install TA-Lib` resolved a prebuilt manylinux wheel,
  version 0.6.8, for Python 3.12 with the C library bundled -- no system install or compilation
  needed, confirmed by actually importing it and computing an EMA. Separately, the spec also
  calls for `pandas-ta` (extended indicators, multi-timeframe). Both versions currently on PyPI
  (0.4.67b0, 0.4.71b0 -- 0.3.14b0 from the spec no longer exists, per ADR-004) hard-require
  `numpy>=2.2.6` and `pandas>=2.3.2`. Installing it pulled in numpy 2.2.6 and pandas 3.0.3,
  silently replacing the pinned numpy==1.26.4/pandas==2.2.1 that M01-M03's 189 passing tests were
  built and verified against -- confirmed by reproducing the upgrade and watching pip's own
  dependency-conflict warning when reverting.
- **Decision:** Pin `TA-Lib==0.6.8` (replaces the spec's `ta-lib==0.4.28`). Drop `pandas-ta`
  entirely rather than force a numpy/pandas major-version bump across the whole stack. Every
  indicator the spec lists is either a direct TA-Lib function (EMA, ADX, RSI, MACD, Stochastic,
  CCI, MFI, ROC, Williams %R, ATR, BBANDS, OBV) or not a TA-Lib/pandas-ta function at all (VWAP,
  VWAP bands, Volume Delta, Pivot points -- Standard/Fibonacci/Camarilla), so pandas-ta wasn't
  actually load-bearing for anything in the required indicator set; the latter four are
  implemented directly with NumPy/pandas in `shared/indicators/definitions/`.
- **Alternatives considered:** (1) Bump numpy/pandas project-wide to satisfy pandas-ta -- rejected
  as unnecessary risk to the already-verified M01-M03 stack (189 green tests) for a dependency
  that turned out not to supply any indicator the spec actually requires. (2) Keep pandas-ta
  pinned but unused/uninstalled "for future modules" -- rejected as dead weight; nothing later in
  the build plan (M06-M09) has been shown to need it either, and adding it back is a one-line
  pyproject.toml change if a real need appears.
- **Consequences:** `shared/indicators/` has zero pandas-ta dependency. If a future module needs
  a pandas-ta-specific indicator not easily hand-rolled, revisit this decision then (and budget
  for re-verifying the full numpy/pandas stack bump at that point, not silently). Volume Delta is
  a candle-direction proxy (signed volume by close-vs-open), not true tick-level aggressor-side
  volume -- documented in `shared/indicators/definitions/volume_delta.py`; the latter would need
  bid/ask-aware tick classification from M16 (Data Ingestion Agent), not available yet.

---

### ADR-010: Instrument master & corporate actions -- sources, schema placement, and
adjustment scope
- **Date:** 2026-06-30
- **Module:** M05
- **Context:** Four related decisions came up building the instrument master and corporate
  actions module, each verified against real endpoints/data rather than assumed:
  1. **Live data sources.** NSE's archived equity list
     (`archives.nseindia.com/content/equities/EQUITY_L.csv`) and corporate-actions API
     (`nseindia.com/api/corporates-corporateActions`, same cookie-bootstrap pattern as M02's
     NSE holiday source) both confirmed live and reachable, including ISIN, lot size, and
     real split/bonus/dividend history (e.g. a real fetch found PGIL's actual 10->5 face-value
     split and RELIANCE's actual 2025/2026 dividends). ASX's listed-companies CSV
     (`asx.com.au/asx/research/ASXListedCompanies.csv`) is also live, but has no ISIN, lot
     size, or tick size fields, and no bulk corporate-actions endpoint was found reachable from
     this build's sandbox after trying several plausible URLs (mirrors M02's ASX holiday
     situation) -- the one working per-symbol endpoint
     (`asx.api.markitdigital.com/.../key-statistics`) exposes a dividend's ex/record/pay
     *dates* but not its *amount*, which `CorporateAction`'s own validation requires, so it
     can't construct a usable DIVIDEND action either.
  2. **Schema placement.** `instruments`/`corporate_actions` are plain relational tables
     (reference data, not a time series) added to `shared/storage/schema.sql` -- the existing
     single TimescaleDB connection's schema file -- rather than a separate
     `shared/instruments/schema.sql` with its own `apply_schema()` call. The `postgres`
     (pgvector) service was considered and rejected: the spec scopes it explicitly to "trade
     log, audit, backtest results, episodic memory," not instrument reference data.
  3. **Manual-override precedence.** `corporate_actions` has a UNIQUE constraint on
     `(symbol, exchange, ex_date, action_type)` *without* `source` in the key, so a later
     upsert replaces an earlier one for the same logical event. `refresh_corporate_actions`
     always writes live-fetched rows first, then manual overrides last -- precedence is just
     write ordering, not read-time filtering logic.
  4. **Adjustment scope.** Only SPLIT and BONUS adjust the price/volume series
     (`shared/instruments/adjustment.py`). DIVIDEND is recorded but not applied: a correct
     cash-dividend (total-return) adjustment needs the close price the day before ex-date,
     which depends on point-in-time data this pure function deliberately doesn't fetch, and
     the spec's own VERIFY command only tests a split. SYMBOL_CHANGE is recorded but doesn't
     stitch a renamed symbol's history onto its predecessor's -- no downstream module needs
     that yet.
- **Decision:** Implement NSE sources fully (both instrument master and corporate actions,
  live-verified). Implement ASX's instrument master fully (live-verified, with ISIN/lot
  size/tick size left `None` and documented why). Implement `ASXCorporateActionSource` as a
  real, callable, per-symbol attempt against the one working endpoint rather than an immediate
  stub -- it returns `[]` today (no amount field available) but the attempt is genuine and
  testable if that endpoint changes. ASX split/bonus/dividend data relies on the manual
  override table (`shared/instruments/manual_overrides.yaml`) for now, per the spec's own
  explicit allowance for one. Schema lives in `shared/storage/schema.sql`. Manual overrides
  win via write-ordering, not a read-time precedence rule. Adjustment covers SPLIT/BONUS only.
- **Alternatives considered:** Scraping ASX announcement PDFs for corporate-action data --
  rejected as a much larger, fragile undertaking (unstructured PDF parsing) for a build-time
  decision better revisited if a real need appears. Applying a same-day dividend adjustment
  using the day's own close as an approximation of "close before ex-date" -- rejected as
  introducing an admittedly-wrong number into a price series, worse than recording the
  dividend but not adjusting for it.
- **Consequences:** Australia's automatic corporate-action coverage is split/bonus/dividend-free
  until either ASX exposes a usable bulk feed or enough manual overrides are curated -- a known,
  visible limitation (logged via `asx_corporate_actions_no_symbols`), not a silent gap. Any
  future module needing dividend-adjusted (total-return) series or symbol-change history
  stitching must extend `shared/instruments/adjustment.py` rather than assume it's already
  handled.

---

### ADR-011: Pattern Recognition Engine -- design decisions (M06)
- **Date:** 2026-07-01
- **Module:** M06
- **Context:** Four non-obvious decisions arose during M06's build that downstream modules
  (M07 backtester, M11 signal engine) need to know about.
- **Decision:**

  1. **CDL function discovery via `dir(talib)` at import time.** Rather than maintaining a
     hardcoded list of ~61 CDL* function names, `shared/patterns/candlestick.py` scans
     `dir(talib)` for names starting with `CDL` once at import. This means a TA-Lib upgrade
     that adds new candlestick functions is automatically picked up without a code change.
     Normalisation: TA-Lib returns ±200 for some functions (e.g. CDLABANDONEDBABY with
     penetration); these are normalised to ±100 so every caller sees a simple signed direction.

  2. **ORB `session_open` clamps lower bound.** When `session_open` is explicitly provided,
     the ORB range is computed only from candles with `session_open <= time <= session_open +
     N_minutes`. Without the lower-bound clamp, candles from before the explicit session open
     (e.g. pre-market or prior-session bars in the same calendar date) would contaminate the
     range. Found via a failing unit test; fixed in the same PR. When `session_open` is None,
     the earliest candle on the last date's session is inferred as the open.

  3. **S/R clustering before touch counting.** Swing pivots and volume-profile peaks are
     clustered first (nearby candidates within `SR_CLUSTER_TOLERANCE_PCT` = 0.3% merged), then
     touches are counted against the clustered representative prices. The alternative -- counting
     touches per raw pivot then merging -- risks double-counting when two pivots within the
     cluster tolerance each get the same touches. Clustering first gives a single canonical
     price per zone.

  4. **`compute_multi_timeframe` accepts `Mapping[str, Sequence[OHLCVCandle]]` not `dict`.** The
     parameter type is `Mapping` (covariant in value type) rather than `dict` so callers can
     pass `dict[str, list[OHLCVCandle]]` without mypy errors. `dict[str, Sequence[...]]` is
     invariant and would require the caller to have the exact type annotation -- a poor API
     contract for a utility function. This mirrors the Python stdlib's own pattern (e.g.
     `json.loads` accepting `Mapping` not `dict`).

- **Alternatives considered:**
  - Hardcoded CDL name list: fragile to TA-Lib version bumps; rejected.
  - Inferring ORB from candle density rather than explicit time boundary: ambiguous around
    partial candles; rejected in favour of the explicit session_open parameter.
  - Volume-weighted S/R strength (multiply touch count by accumulated volume at the level):
    would add accuracy but requires normalising volumes across very different price instruments;
    deferred to a future enhancement, current strength is touch-count-only normalised to 0–1.

- **Consequences:** M11 (signal engine) Gate 4 should call `detect_recent(candles,
  lookback_bars=3)` (not `detect_all`) to efficiently check whether the most recent bars carry
  a confirming pattern. Gate 6 (S/R proximity) should pass only the last `SR_LOOKBACK_CANDLES`
  (100) bars to `detect_sr_levels` -- same default the engine already applies. The `Mapping`
  typing means callers don't need to cast their `list`-valued dicts.

---

## M01–M06 Validation Summary (2026-07-01)

Full cross-check of M01–M06 against `MASTER_BUILD_PROMPT_FINAL.MD` run on 2026-07-01.
Result: all modules spec-aligned, all 361 tests pass (359 + 2 skipped), ruff clean,
mypy --strict clean (133 files). One formatting issue found and fixed (orb.py, commit 227f76c).

**Verified wiring:**
- M04 `candle_arrays_from_candles` → used by M06 `candlestick.detect_all`
- M05 `adjusted_candles` → correct upstream for M06 (patterns must run on adjusted series)
- M06 `PatternSnapshot` → consumed by M11 Gate 4 (CDL) and Gate 6 (S/R proximity)
- M06 `ORBState` → consumed by M11 Gate 3 (ORB breakout confirmation)

**API names for future sessions (verified in code, not just docs):**
- `settings.is_live_trading_enabled` — live-trading guard property
- `SQLiteFailoverBuffer` — RULE 5 DB-outage buffer
- `TickSequenceValidator` — tick validation class
- `all_indicators()` — returns full registry dict
- Continuous aggregates: `ohlcv_5m`, `ohlcv_15m`, `ohlcv_1h`

---

### ADR-012: Backtesting Engine — design decisions (M07)
- **Date:** 2026-07-01
- **Module:** M07

- **Decision 1: plotly pinned to 5.24.1.**
  vectorbt 0.26.x references `heatmapgl` in plotly's layout template `Data` class, which
  was removed in plotly 6.0. Without the pin, `import vectorbt` raises `AttributeError:
  module 'plotly.graph_objs._figure' has no attribute 'heatmapgl'` at import time.
  Pin: `plotly==5.24.1` in pyproject.toml (extras group `backtesting`).
  Consequence: any future plotly upgrade requires re-testing vectorbt compatibility first.

- **Decision 2: Log-normal slippage injected before vectorbt sees prices (not via built-in
  slippage parameter).** vectorbt's built-in slippage is a fixed flat percentage applied
  uniformly to all trades. The spec requires a log-normal distribution parameterised by
  time-of-day bucket AND bid-ask spread width. Implementation: for each entry bar, compute
  `adj_price[i] = close[i] * (1 + slip_bps/10000)`; for each exit bar, `adj_price[i] =
  close[i] * (1 - slip_bps/10000)`. Pass `adj_price` as the `price=` argument to
  `Portfolio.from_signals()`. vectorbt then executes against the adjusted price, giving
  realistic per-trade slippage without monkey-patching the library.
  Default NSE parameters: OPEN μ=2.0/σ=0.5 (~7.4 bps median), MID μ=1.4/σ=0.4
  (~4.1 bps), CLOSE μ=1.8/σ=0.5 (~6.0 bps). `fit_from_fills()` refits from real M16
  fill data once available.

- **Decision 3: T+1s markout not implemented (candle-resolution limitation).**
  The spec lists T+1s, T+1m, T+5m markout offsets. Candle-based backtesting cannot
  resolve sub-candle timing. T+1s requires tick-level data from M16 (Data Ingestion).
  Current implementation computes T+1m and T+5m only. This is documented as a known
  limitation; T+1s will be added as a post-M16 enhancement.

- **Decision 4: `backtest_results` stored as a regular PostgreSQL table, not a hypertable.**
  Each backtest run produces exactly one summary row (not a time-series). Hypertables are
  optimised for high-frequency time-ordered appends; a regular table with `run_id` as PK
  is simpler and equally performant for the ~hundreds of rows per strategy expected here.
  `promotion_failures` stored as JSONB (list of failure label strings) for flexible
  querying without a separate join table.

- **Decision 5: Walk-forward uses Sharpe as the sole optimisation objective.**
  The spec does not prescribe an objective function. Sharpe is chosen because it penalises
  both return magnitude and volatility, which aligns with RULE 6's gate criteria. A simple
  `max(trades * win_rate)` objective would favour high-frequency strategies that may not
  generalise. Alternatives (Calmar, Sortino) are available as metrics but not used for
  parameter selection in walk-forward.

- **Alternatives considered:**
  - Using vectorbt's built-in `slippage` parameter: fixed percentage, not log-normal,
    cannot vary by time-of-day or spread — rejected.
  - Jinja2 for HTML report templates: adds a dependency with no template files to manage;
    rejected in favour of f-string self-contained HTML.
  - Storing full equity curves in PostgreSQL: ~252 floats per run, manageable but not
    queried analytically — omitted from DB, available in the HTML report only.

- **Consequences:** M08 (Market Regime Classifier) must be promotion-gated via the same
  20-day paper-trading gate (`check_promotion_gate`) defined here. M16 fill data enables
  `fit_from_fills()` to refit log-normal parameters for each instrument. The walk-forward
  `SignalFn` type alias (`Callable[[list[OHLCVCandle], dict[str, float]], tuple[list[bool],
  list[bool]]]`) is the contract any M11+ strategy must satisfy to participate in
  walk-forward optimisation.

- **Note (ADR-012 addendum — storage location):** The spec architecture diagram shows
  `backtest_results` in the pgvector PostgreSQL instance. The implementation uses the
  TimescaleDB connection (`TIMESCALE_DSN`) for this table. Both are PostgreSQL; the pgvector
  instance is reserved for M18 episodic memory (vector similarity search). Since
  `backtest_results` is a plain relational table with no time-series or vector requirements,
  TimescaleDB is the appropriate single writable database for all non-vector tabular data,
  consistent with `instruments` and `corporate_actions` (M05, same decision).

---

### ADR-013: Market Regime Classifier — design decisions (M08)
- **Date:** 2026-07-01
- **Module:** M08
- **Context:** Several non-obvious decisions arose during M08's build that downstream modules
  (M09 universe filter, M11 signal engine, M18 orchestrator) need to know about.
- **Decision:**

  1. **RULE 2 hard override is evaluated before any model inference.** `RegimeClassifier.classify()`
     checks `_is_chaos(features)` as its first instruction: if `features.vix > 25.0` (strict
     greater-than; VIX exactly 25.0 does NOT trigger) or `features.atr_spike is True`, it
     returns `HIGH_VOL_CHAOS` with `confidence=1.0` without invoking the RF or HMM. This
     guarantees RULE 2 regardless of model state.

  2. **HMM state mapping uses RF majority-vote post-training.** HMM hidden states have no
     inherent semantic label. After fitting, each HMM state is labelled by majority vote of
     the RF's regime predictions for all training samples assigned to that state. The mapping
     is stored alongside the HMM in MLflow and restored at load time.

  3. **Feature set deviation from spec.** The spec lists 9 features including put-call ratio
     and order flow delta. Both require data sources not yet available (options chain for
     put-call ratio, bid-ask-aware tick classification for true order flow delta). The
     implementation uses 8 features: ADX, RSI, BB width, ATR%, VWAP deviation, volume ratio
     (recent/average — a candle-based proxy for volume delta), VIX level, ATR spike flag.
     Put-call ratio and order flow delta are deferred until M10/M16 provide the required
     data feeds. The `RegimeFeatures` field is named `volume_ratio` not `volume_delta` to
     accurately reflect what is computed; the proto field `volume_delta` receives this value
     (known naming mismatch, documented here — correcting the proto field name is a breaking
     proto change deferred to a future version).

  4. **MLflow `list_model_versions()` catches all exceptions and logs a structured warning.**
     MLflow connectivity failures at inspection time must not crash the caller. The function
     returns `[]` and logs `mlflow_list_versions_failed` so ops tooling can detect
     connectivity problems.

  5. **Rule-based fallback when not fitted.** An unfitted `RegimeClassifier` classifies via
     explicit ADX/RSI thresholds (ADX>25 + RSI>55 → BULL, ADX>25 + RSI<45 → BEAR, else
     MEAN_REVERTING). This ensures the module is useful immediately during warm-up before
     training data is available, and during M18 orchestrator startup before the first MLflow
     model is loaded.

- **Alternatives considered:**
  - Using VIX=25 (inclusive) as the chaos threshold — rejected; `>` (strict) is the
    conventional interpretation of "above 25" and ensures VIX exactly at 25 is not treated
    as chaos (verified in `test_regime_classifier.py`).
  - Using put-call ratio and order flow delta as zero-valued placeholders — rejected as
    misleading; zero PCR is a valid value (all calls, no puts), so a zero placeholder would
    produce wrong regime classifications.

- **Consequences:** M09 (universe filter) reads regime from Redis stream `regime:changes`
  (key `REGIME_REDIS_STREAM`) via `read_latest_regime()`. M11 signal engine Gate 1 must
  block all entries when regime is `HIGH_VOL_CHAOS`. M18 orchestrator wires the 5-minute
  reclassification loop. Once M10 provides sentiment/PCR data and M16 provides tick-level
  fills, `RegimeFeatures` should be extended with `put_call_ratio` and `order_flow_delta`
  fields and the proto updated accordingly.

---

### ADR-014: M08 periodic classification loop deferred to M18
- **Date:** 2026-07-01
- **Module:** M08 / M18
- **Context:** The spec implies M08 should classify the market regime on a recurring
  schedule (the regime must be current when M11 evaluates Gate 1). The M08 build provides
  `RegimeClassifier.classify()` and `publish_regime_change()` as callable functions, but
  does not include a scheduled loop that calls them every 5 minutes.
- **Decision:** The scheduling loop is deferred to M18 (Agent Orchestrator, LangGraph).
  M18 owns the agent state graph and controls all recurring agent invocations; embedding a
  `while True: sleep(300)` loop inside M08 would create a second scheduler that conflicts
  with M18's graph. M08 is invocable both as a one-shot CLI (`python -m shared.regime`)
  and as a library (`classify(features)`) — both patterns work today without a scheduler.
- **Alternatives considered:** Background thread in M08 — rejected; a thread inside a
  library module creates implicit side effects on import and is incompatible with M18's
  LangGraph event loop model.
- **Consequences:** M18 must wire a periodic node (every 5 minutes during OPEN session
  state) that calls `extract_features()` → `classify()` → `publish_regime_change()`. M09
  and M11, when built, may read the last-published regime from Redis rather than calling
  `classify()` directly.
