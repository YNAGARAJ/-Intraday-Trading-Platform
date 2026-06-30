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
