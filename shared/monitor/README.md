# M19 — Real-Time Monitor Agent

Live P&L tracker, agent heartbeat checker (Tier 3 Kill Switch trigger), and
Prometheus metrics exporter with Grafana dashboard provisioning.

## Module layout

| File | Responsibility |
|------|---------------|
| `models.py` | `HeartbeatRecord`, `AgentHealth`, `PnLSnapshot`, `MonitorSnapshot` |
| `pnl_tracker.py` | Reads daily P&L from Redis; circuit-breaker detection |
| `heartbeat.py` | Per-agent liveness monitoring; Tier 3 kill switch trigger |
| `metrics.py` | `PrometheusMetrics` — all Gauges with per-instance registry |
| `agent.py` | `MonitorAgent` — periodic polling loop, wires all components |
| `grafana_dashboard.json` | Grafana 10.4.1 dashboard provisioning JSON |
| `cli.py` | 20 VERIFY scenarios |

## Prometheus metrics

| Metric | Type | Description |
|--------|------|-------------|
| `trading_pnl_today_pct` | Gauge | Daily P&L as fraction of starting capital |
| `trading_pnl_today_abs` | Gauge | Daily P&L in base currency |
| `trading_open_positions_count` | Gauge | Open positions count |
| `trading_signals_today_total` | Gauge | Signals generated today |
| `trading_reconciliation_mismatches_total` | Gauge | Outstanding reconciliation mismatches |
| `trading_system_halted` | Gauge | 1 = kill switch/CB active, 0 = live |
| `trading_agent_heartbeat_age_seconds{agent_name}` | Gauge | Seconds since each agent's last heartbeat |

## Heartbeat protocol (Tier 3 Kill Switch — RULE 8)

Monitored agents call `monitor_agent.register_heartbeat(agent_name)` once per
heartbeat cycle (default: every 30 seconds). The `HeartbeatChecker`:

1. Reads the agent's timestamp from Redis key `monitor:heartbeat:<agent_name>`.
2. Computes `age_seconds = now - last_seen`.
3. If `age_seconds > HEARTBEAT_INTERVAL_SECONDS`, increments `missed_count`.
4. If `missed_count >= MAX_MISSED_HEARTBEATS_BEFORE_KILL` (2), triggers the
   injected `KillSwitchManager.trigger_tier3(reason)`.

## Redis keys

| Key | Type | Written by | Purpose |
|-----|------|-----------|---------|
| `monitor:heartbeat:<agent_name>` | String | Each agent | Last-seen Unix ms |
| `risk:daily:pnl:{YYYYMMDD}` | String | M12 RiskEngine | Absolute daily P&L |
| `system:status:halted` | String | M13 KillSwitchManager | Halt flag |
| `orchestrator:state` | String | M18 OrchestratorGraph | Full state blob (JSON) |
| `reconciliation:mismatches` | Stream | M17 MismatchPublisher | Mismatch events |

## API reference

```python
from shared.monitor import (
    MonitorAgent,
    HeartbeatChecker,
    PrometheusMetrics,
    PnLTracker,
    MonitorSnapshot,
    PnLSnapshot,
    AgentHealth,
    HeartbeatRecord,
)

# Wire components
pnl = PnLTracker(redis_client=redis, starting_capital=1_000_000.0)
hb  = HeartbeatChecker(redis_client=redis, kill_switch=kill_switch_mgr)
hb.add_watched_agent("signal_agent")
hb.add_watched_agent("data_agent")
pm  = PrometheusMetrics()           # fresh registry per instance
pm.start_http_server(port=8000)     # exposes /metrics for Prometheus scrape

agent = MonitorAgent(pnl, hb, pm, poll_interval_seconds=30)
agent.start()                       # background thread

# From each monitored agent:
agent.register_heartbeat("signal_agent")   # call every 30s

# Manual poll:
snap: MonitorSnapshot = agent.poll_once()

# Graceful shutdown:
agent.stop()
```

## Grafana provisioning

Import `grafana_dashboard.json` via Grafana → Dashboards → Import.
Select the `DS_PROMETHEUS` data source pointing at the Prometheus instance
configured in `docker-compose.yml`.

The dashboard auto-refreshes every 10 seconds and shows:
- Daily P&L % with −2% circuit-breaker line
- System halt state (green = LIVE, red = HALTED)
- Reconciliation mismatch count
- Open positions and signals today
- Per-agent heartbeat age table and time-series

## Standalone run

```bash
python -m shared.monitor
# Runs 20 VERIFY scenarios; prints VERIFY_SUMMARY passed=20 total=20
```

## Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `HEARTBEAT_INTERVAL_SECONDS` | 30 | Expected agent heartbeat cadence |
| `MAX_MISSED_HEARTBEATS_BEFORE_KILL` | 2 | Consecutive misses before Tier 3 trigger |
| `MONITOR_POLL_INTERVAL_SECONDS` | 30 | MonitorAgent background thread interval |
| `MONITOR_HEARTBEAT_REDIS_KEY_PREFIX` | `monitor:heartbeat` | Per-agent key prefix |
| `PROMETHEUS_METRICS_PORT` | 8000 | Default HTTP /metrics port |
