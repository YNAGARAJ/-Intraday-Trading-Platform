-- TimescaleDB schema: tick hypertable, 1-minute OHLCV base hypertable, and 5m/15m/1h
-- continuous aggregates derived from it. Applied once at DB init time (see
-- shared/storage/connection.py:apply_schema). Idempotent -- every statement uses
-- IF NOT EXISTS / *_if_not_exists so re-running this file is always safe.
--
-- Design note: ohlcv_1m is the base table that downstream continuous aggregates derive
-- from (not the ticks table directly), because the actual tick -> 1m candle aggregation
-- happens in the Data Ingestion Agent's NumPy in-memory aggregator (M16), not in SQL --
-- this schema only needs to store and roll up what M16 writes.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- Raw ticks
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ticks (
    time        TIMESTAMPTZ NOT NULL,
    symbol      TEXT NOT NULL,
    exchange    TEXT NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    volume      BIGINT NOT NULL,
    bid         DOUBLE PRECISION,
    ask         DOUBLE PRECISION
);

SELECT create_hypertable('ticks', by_range('time'), if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks (symbol, time DESC);

ALTER TABLE ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, exchange',
    timescaledb.compress_orderby = 'time DESC'
);

SELECT add_compression_policy('ticks', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('ticks', INTERVAL '2 years', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- 1-minute OHLCV (base table for the continuous aggregates below)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ohlcv_1m (
    time        TIMESTAMPTZ NOT NULL,
    symbol      TEXT NOT NULL,
    exchange    TEXT NOT NULL,
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      BIGINT NOT NULL,
    PRIMARY KEY (symbol, exchange, time)
);

SELECT create_hypertable('ohlcv_1m', by_range('time'), if_not_exists => TRUE);

ALTER TABLE ohlcv_1m SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, exchange',
    timescaledb.compress_orderby = 'time DESC'
);

SELECT add_compression_policy('ohlcv_1m', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('ohlcv_1m', INTERVAL '5 years', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- Continuous aggregates: 5m, 15m, 1h -- all derived directly from ohlcv_1m
-- (not chained from one another) to avoid hierarchical-CAGG version-specific quirks.
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_5m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT
    time_bucket('5 minutes', time) AS time,
    symbol,
    exchange,
    first(open, time) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, time) AS close,
    sum(volume) AS volume
FROM ohlcv_1m
GROUP BY time_bucket('5 minutes', time), symbol, exchange
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ohlcv_5m',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_15m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT
    time_bucket('15 minutes', time) AS time,
    symbol,
    exchange,
    first(open, time) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, time) AS close,
    sum(volume) AS volume
FROM ohlcv_1m
GROUP BY time_bucket('15 minutes', time), symbol, exchange
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ohlcv_15m',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '15 minutes',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_1h
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT
    time_bucket('1 hour', time) AS time,
    symbol,
    exchange,
    first(open, time) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, time) AS close,
    sum(volume) AS volume
FROM ohlcv_1m
GROUP BY time_bucket('1 hour', time), symbol, exchange
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ohlcv_1h',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);
