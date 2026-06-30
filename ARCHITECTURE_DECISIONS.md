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
