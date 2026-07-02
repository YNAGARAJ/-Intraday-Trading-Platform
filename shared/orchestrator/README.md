# M18 — Agent Orchestrator (LangGraph)

LangGraph-based state-graph orchestrator that wires all trading agents into a single
execution cycle, with ACT-R tiered memory, human-in-the-loop interrupts, and kill-switch
preemption.

## Architecture

```
regime_node → signal_node → reconciliation_node → risk_node
                                                       │
                  ┌────────────────────────────────────┤
                  ▼                                     │
           kill_switch_node ◄── kill/CB active ─────────┤
                  │                                     │
                  ▼                                     ▼
                 END                             hitl_node → END
```

Graph is compiled with `interrupt_before=['hitl_node']` (when `enable_hitl=True`).

## Module layout

| File | Responsibility |
|------|---------------|
| `state.py` | `TradingSystemState` TypedDict, `make_initial_state`, JSON helpers |
| `memory.py` | `WorkingMemory`, `ShortTermMemory`, `LongTermMemory`, `ACTRMemory` |
| `nodes.py` | Node factory functions for each graph node |
| `graph.py` | `OrchestratorGraph` — compiles and drives the LangGraph |
| `cli.py` | 20 VERIFY scenarios (run via `python -m shared.orchestrator`) |

## ACT-R Memory Tiers

| Tier | Backend | TTL | Purpose |
|------|---------|-----|---------|
| Working | In-process dict | 2 000 token budget | Market snapshot, active positions |
| Short-Term | Redis | 1 hour | Signal structures, order-flow anomalies |
| Long-Term | PostgreSQL | Nightly decay scoring | Successful setups, loss post-mortems |

**Activation formula:** `activation = ln(Σ t_i^(−d))` where `d = 0.5`, `t_i` = seconds
since the i-th retrieval.  Higher score → higher retrieval priority.

## Node responsibilities

| Node | Reads | Writes to state |
|------|-------|-----------------|
| `regime_node` | `regime:changes` stream | `market_regime`, `regime_confidence` |
| `signal_node` | `signals:generated` stream, halt/degraded keys | `signals_today`, `kill_switch_active` |
| `reconciliation_node` | `reconciliation:mismatches` stream | `last_reconciliation_at`, `reconciliation_mismatches_today` |
| `risk_node` | `open_positions`, `pnl_today_pct` | `circuit_breaker_active`, `pending_hitl_approval` |
| `hitl_node` | `pending_hitl_approval` | clears `pending_hitl_approval` |
| `kill_switch_node` | — | `kill_switch_active=True`, clears `pending_hitl_approval` |

## Signal node safety gates

All gates checked before incrementing `signals_today`:

1. `kill_switch_active` → block all entries
2. `circuit_breaker_active` → block all entries
3. `system:status:halted` Redis key set → block + set `kill_switch_active=True`
4. `system:status:degraded` Redis key set → DEGRADED_EXIT_ONLY (block new entries)
5. `market_regime == HIGH_VOL_CHAOS` → block (RULE 2)
6. Reconciliation block → block per symbol/exchange

## HITL interrupt

When `risk_node` detects a position exceeding `HITL_CAPITAL_THRESHOLD_PCT` (5%) of
starting capital, it sets `pending_hitl_approval`. The graph halts before `hitl_node`.

```python
orch = OrchestratorGraph(starting_capital=1_000_000.0, enable_hitl=True)
result = orch.run_cycle(state)  # returns None if interrupted

# Approve:
result = orch.approve_hitl()   # resumes; clears pending_hitl_approval

# Reject:
orch.reject_hitl()             # clears approval; graph routes to END
```

## Kill-switch preemption (RULE 8)

Kill switch always preempts a pending HITL approval — never the reverse.

```python
orch.trigger_kill_switch(reason="daily loss limit")
# → sets kill_switch_active=True immediately in local state
# → clears pending_hitl_approval
# → routes to kill_switch_node on next cycle
```

## Standalone run

```bash
python -m shared.orchestrator
# Runs 20 VERIFY scenarios; prints VERIFY_SUMMARY passed=20 total=20
```

## Environment variables / constants

| Constant | Value | Description |
|----------|-------|-------------|
| `HITL_CAPITAL_THRESHOLD_PCT` | 0.05 | Position size threshold triggering HITL (5%) |
| `WORKING_MEMORY_MAX_TOKENS` | 2 000 | Token budget for working memory |
| `SHORT_TERM_MEMORY_TTL_SECONDS` | 3 600 | Redis TTL for short-term memory (1 hour) |
| `SHORT_TERM_MEMORY_REDIS_KEY_PREFIX` | `orchestrator:stm` | Redis key namespace |
| `ACT_R_DECAY_PARAM` | 0.5 | Decay exponent `d` in activation formula |
| `ORCHESTRATOR_STATE_REDIS_KEY` | `orchestrator:state` | Key for `shutdown()` persistence |

## Redis keys read by this module

| Key | Type | Written by | Purpose |
|-----|------|-----------|---------|
| `system:status:halted` | String | M13 KillSwitchManager | Hard halt check |
| `system:status:degraded` | String | M16 DataIngestionAgent | WS-down fallback |
| `regime:changes` | Stream | M08 RegimePublisher | Latest regime |
| `signals:generated` | Stream | M11 SignalPublisher | New signals |
| `reconciliation:mismatches` | Stream | M17 MismatchPublisher | Mismatch count |
| `orchestrator:state` | String | `OrchestratorGraph.shutdown()` | Crash recovery |
| `orchestrator:stm:<key>` | String | `ShortTermMemory.put()` | ACT-R tier 2 |

## API reference

```python
from shared.orchestrator import (
    OrchestratorGraph,
    ACTRMemory,
    WorkingMemory,
    ShortTermMemory,
    LongTermMemory,
    LongTermMemoryEntry,
    TradingSystemState,
    make_initial_state,
    state_to_json,
    state_from_json,
)

# Build and run
orch = OrchestratorGraph(
    redis_client=redis,
    starting_capital=1_000_000.0,
    reconciliation_blocked_fn=block_registry.is_blocked,
    thread_id="session-2026-07-02",
    enable_hitl=True,
)
state = orch.run_cycle(make_initial_state("2026-07-02"))

# State persistence
orch.shutdown()                              # write state to Redis
orch2 = OrchestratorGraph.restore(redis)   # reload on restart

# Memory
mem = ACTRMemory(redis_client=redis, db_conn=pg_conn)
mem.remember("last_signal", "LONG RELIANCE 2500", tier="working")
mem.recall("last_signal", tier="working")   # → "LONG RELIANCE 2500"
```
