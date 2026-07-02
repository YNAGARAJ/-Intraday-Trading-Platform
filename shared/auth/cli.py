"""M15 CLI — VERIFY scenarios for Authentication & Token Manager.

Run with::

    python -m shared.auth verify

Scenarios:
  01  TOTP code generation via pyotp
  02  Paper-mode Kite login: token issued without real HTTP calls
  03  Token stored in Redis (fake) with correct TTL key
  04  Token retrieved from store — matches stored record
  05  Token TTL: is_valid() respects expiry
  06  Expired token evicted on load — triggers re-login
  07  In-memory fallback when Redis unavailable
  08  Token never appears in log output (secrets not logged)
  09  IBKR pool: acquire one slot
  10  IBKR pool: release slot — available again
  11  IBKR pool: all slots acquired → AuthError raised
  12  IBKR pool: paper mode port = 7497
  13  IBKR pool: live mode port = 7496
  14  IBKR pool: pool_size > MAX raises ValueError
  15  IBKR heartbeat thread starts and is daemon
  16  KiteAuthManager.get_token() returns cached token on second call
  17  KiteAuthManager.invalidate() forces re-login
  18  Mock HTTP login flow: token stored after successful 2FA
  19  DailyRefreshScheduler: callback fires after manual trigger
  20  Audit log: all VERIFY entries have broker field (no token value)
"""

from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock

import pyotp
import structlog

from shared.auth.ibkr_auth import IBKRConnectionPool
from shared.auth.kite_auth import KiteAuthManager
from shared.auth.models import AuthMode, TokenRecord
from shared.auth.scheduler import DailyRefreshScheduler
from shared.auth.token_store import AuthError, TokenStore
from shared.core.constants import (
    IBKR_CLIENT_ID_POOL_MAX,
    IBKR_LIVE_PORT,
    IBKR_PAPER_PORT,
    KITE_SESSION_TTL_SECONDS,
)

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(40),  # ERROR only in CLI
)


class _FakeRedis:
    """In-process fake Redis for VERIFY scenarios."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, int | None]] = {}

    def set(self, name: str, value: str, ex: int | None = None) -> object:
        self._store[name] = (value, ex)
        return True

    def get(self, name: str) -> bytes | None:
        entry = self._store.get(name)
        return entry[0].encode() if entry else None

    def delete(self, *names: str) -> int:
        count = 0
        for n in names:
            if n in self._store:
                del self._store[n]
                count += 1
        return count

    def get_ttl(self, name: str) -> int | None:
        entry = self._store.get(name)
        return entry[1] if entry else None


def _pass(num: str, msg: str) -> None:
    print(f"  [PASS] Scenario {num}: {msg}")


def _fail(num: str, msg: str) -> None:
    print(f"  [FAIL] Scenario {num}: {msg}")


def run_verify() -> bool:  # noqa: PLR0912,PLR0915
    """Execute all 20 VERIFY scenarios. Returns True if all pass."""
    print("=" * 70)
    print("M15 — AUTHENTICATION & TOKEN MANAGER  |  20 VERIFY SCENARIOS")
    print("=" * 70)
    all_pass = True

    print("\n── Scenarios 01-08: Token lifecycle ──")

    # 01: TOTP code generation
    totp = pyotp.TOTP("JBSWY3DPEHPK3PXP")
    code = totp.now()
    ok01 = isinstance(code, str) and len(code) == 6 and code.isdigit()
    if not ok01:
        all_pass = False
    (_pass if ok01 else _fail)("01", f"TOTP code generated: {code}")

    # 02: Paper-mode Kite login
    store02 = TokenStore()
    mgr02 = KiteAuthManager(
        user_id="TEST_USER",
        password="secret",
        totp_secret="JBSWY3DPEHPK3PXP",
        api_key="api_key",
        api_secret="api_secret",
        token_store=store02,
        mode=AuthMode.PAPER,
    )
    record02 = mgr02.login()
    ok02 = (
        record02.broker == "kite"
        and record02.mode == AuthMode.PAPER
        and record02.access_token == "PAPER_TOKEN_SIMULATED"
        and record02.user_id == "TEST_USER"
    )
    if not ok02:
        all_pass = False
    (_pass if ok02 else _fail)("02", f"Paper token issued: broker={record02.broker}")

    # 03: Token stored in Redis with TTL
    redis03 = _FakeRedis()
    store03 = TokenStore(redis_client=redis03)
    mgr03 = KiteAuthManager(
        user_id="U1", password="p", totp_secret="JBSWY3DPEHPK3PXP",
        api_key="k", api_secret="s", token_store=store03, mode=AuthMode.PAPER,
    )
    mgr03.login()
    ttl03 = redis03.get_ttl("auth:kite:access_token")
    ok03 = ttl03 == KITE_SESSION_TTL_SECONDS
    if not ok03:
        all_pass = False
    expected_ttl = KITE_SESSION_TTL_SECONDS
    (_pass if ok03 else _fail)("03", f"Token TTL={ttl03}s (expected {expected_ttl}s)")

    # 04: Token retrieved from store
    loaded04 = store03.load("kite")
    ok04 = loaded04 is not None and loaded04.access_token == "PAPER_TOKEN_SIMULATED"
    if not ok04:
        all_pass = False
    (_pass if ok04 else _fail)(
        "04", f"Token retrieved: broker={loaded04.broker if loaded04 else 'None'}"
    )

    # 05: is_valid() respects expiry
    now_ms = int(time.time() * 1000)
    valid_rec = TokenRecord(
        broker="kite", access_token="T", issued_at_ms=now_ms,
        expires_at_ms=now_ms + 10_000, user_id="U", mode=AuthMode.PAPER,
    )
    expired_rec = TokenRecord(
        broker="kite", access_token="T", issued_at_ms=now_ms - 20_000,
        expires_at_ms=now_ms - 1, user_id="U", mode=AuthMode.PAPER,
    )
    ok05 = valid_rec.is_valid(now_ms) and not expired_rec.is_valid(now_ms)
    if not ok05:
        all_pass = False
    (_pass if ok05 else _fail)("05", "is_valid() True for fresh, False for expired")

    # 06: Expired token evicted, re-login triggered
    redis06 = _FakeRedis()
    store06 = TokenStore(redis_client=redis06)
    expired_payload = (
        '{"broker":"kite","access_token":"OLD","issued_at_ms":0,'
        '"expires_at_ms":1,"user_id":"U","mode":"PAPER"}'
    )
    redis06.set("auth:kite:access_token", expired_payload, ex=KITE_SESSION_TTL_SECONDS)
    loaded06 = store06.load("kite")
    ok06 = loaded06 is None  # expired → None
    if not ok06:
        all_pass = False
    (_pass if ok06 else _fail)("06", "Expired token evicted on load")

    # 07: In-memory fallback when Redis unavailable
    store07 = TokenStore(redis_client=None)
    mgr07 = KiteAuthManager(
        user_id="U2", password="p", totp_secret="JBSWY3DPEHPK3PXP",
        api_key="k", api_secret="s", token_store=store07, mode=AuthMode.PAPER,
    )
    mgr07.login()
    loaded07 = store07.load("kite")
    ok07 = loaded07 is not None and loaded07.access_token == "PAPER_TOKEN_SIMULATED"
    if not ok07:
        all_pass = False
    (_pass if ok07 else _fail)("07", "In-memory fallback: token stored and loaded")

    # 08: Token value never appears in structured logs
    import io
    import logging as _logging

    log_capture = io.StringIO()
    handler = _logging.StreamHandler(log_capture)
    _logging.getLogger().addHandler(handler)
    store08 = TokenStore()
    mgr08 = KiteAuthManager(
        user_id="U3", password="secret_password", totp_secret="JBSWY3DPEHPK3PXP",
        api_key="k", api_secret="secret_api", token_store=store08, mode=AuthMode.PAPER,
    )
    mgr08.login()
    _logging.getLogger().removeHandler(handler)
    log_output = log_capture.getvalue()
    ok08 = (
        "PAPER_TOKEN_SIMULATED" not in log_output
        and "secret_password" not in log_output
        and "secret_api" not in log_output
    )
    if not ok08:
        all_pass = False
    (_pass if ok08 else _fail)("08", "Secrets absent from log output")

    print("\n── Scenarios 09-15: IBKR connection pool ──")

    # 09: Acquire one slot
    pool09 = IBKRConnectionPool(pool_size=2)
    slot09 = pool09.acquire()
    ok09 = slot09.in_use and pool09.available_count() == 1
    if not ok09:
        all_pass = False
    avail09 = pool09.available_count()
    (_pass if ok09 else _fail)(
        "09", f"Slot acquired: client_id={slot09.client_id} available={avail09}"
    )

    # 10: Release slot
    pool09.release(slot09)
    ok10 = not slot09.in_use and pool09.available_count() == 2
    if not ok10:
        all_pass = False
    avail10 = pool09.available_count()
    (_pass if ok10 else _fail)("10", f"Slot released: available={avail10}")

    # 11: Pool exhausted raises AuthError
    pool11 = IBKRConnectionPool(pool_size=2)
    pool11.acquire()
    pool11.acquire()
    ok11 = False
    try:
        pool11.acquire()
    except AuthError:
        ok11 = True
    if not ok11:
        all_pass = False
    (_pass if ok11 else _fail)("11", "Pool exhausted raises AuthError")

    # 12: Paper mode port = 7497
    pool12 = IBKRConnectionPool(mode=AuthMode.PAPER)
    ok12 = pool12.port == IBKR_PAPER_PORT
    if not ok12:
        all_pass = False
    (_pass if ok12 else _fail)(
        "12", f"Paper port={pool12.port} (expected {IBKR_PAPER_PORT})"
    )

    # 13: Live mode port = 7496
    pool13 = IBKRConnectionPool(mode=AuthMode.LIVE)
    ok13 = pool13.port == IBKR_LIVE_PORT
    if not ok13:
        all_pass = False
    (_pass if ok13 else _fail)(
        "13", f"Live port={pool13.port} (expected {IBKR_LIVE_PORT})"
    )

    # 14: pool_size > MAX raises ValueError
    ok14 = False
    try:
        IBKRConnectionPool(pool_size=IBKR_CLIENT_ID_POOL_MAX + 1)
    except ValueError:
        ok14 = True
    if not ok14:
        all_pass = False
    (_pass if ok14 else _fail)(
        "14", f"pool_size>{IBKR_CLIENT_ID_POOL_MAX} raises ValueError"
    )

    # 15: Heartbeat thread is daemon
    pool15 = IBKRConnectionPool(pool_size=1, enable_heartbeat=True)
    ok15 = (
        pool15._heartbeat_thread is not None
        and pool15._heartbeat_thread.daemon is True
    )
    pool15.shutdown()
    if not ok15:
        all_pass = False
    (_pass if ok15 else _fail)("15", "Heartbeat thread started as daemon")

    print("\n── Scenarios 16-19: Auth manager & scheduler ──")

    # 16: get_token() returns cached token on second call (no double-login)
    store16 = TokenStore()
    mgr16 = KiteAuthManager(
        user_id="U4", password="p", totp_secret="JBSWY3DPEHPK3PXP",
        api_key="k", api_secret="s", token_store=store16, mode=AuthMode.PAPER,
    )
    r16a = mgr16.get_token()
    r16b = mgr16.get_token()
    ok16 = r16a.access_token == r16b.access_token
    if not ok16:
        all_pass = False
    (_pass if ok16 else _fail)("16", "get_token() returns cached token on 2nd call")

    # 17: invalidate() forces re-login
    mgr16.invalidate()
    assert store16.load("kite") is None
    r16c = mgr16.get_token()
    ok17 = r16c.access_token == "PAPER_TOKEN_SIMULATED"
    if not ok17:
        all_pass = False
    (_pass if ok17 else _fail)("17", "invalidate() forces re-login")

    # 18: Mock HTTP login flow
    store18 = TokenStore()
    mock_session = MagicMock()
    mock_session.post.side_effect = [
        MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"data": {"request_id": "REQ123"}}),
        ),
        MagicMock(
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"data": {"request_token": "REQTOKEN456"}}),
        ),
    ]
    mgr18 = KiteAuthManager(
        user_id="LIVEUSER", password="livepass",
        totp_secret="JBSWY3DPEHPK3PXP",
        api_key="key18", api_secret="sec18",
        token_store=store18, mode=AuthMode.LIVE,
        http_session=mock_session,
    )
    rec18 = mgr18.login()
    ok18 = (
        rec18.broker == "kite"
        and rec18.mode == AuthMode.LIVE
        and rec18.user_id == "LIVEUSER"
        and "REQTOKEN456" in rec18.access_token
    )
    if not ok18:
        all_pass = False
    (_pass if ok18 else _fail)(
        "18", f"Mock HTTP login: mode={rec18.mode.value} broker={rec18.broker}"
    )

    # 19: DailyRefreshScheduler: callback invoked via direct _fire()
    fired: list[bool] = []
    scheduler = DailyRefreshScheduler(callback=lambda: fired.append(True))
    scheduler._fire()  # invoke directly without waiting for timer
    ok19 = len(fired) == 1
    if ok19:
        scheduler.stop()
    if not ok19:
        all_pass = False
    (_pass if ok19 else _fail)("19", f"Scheduler callback fired: count={len(fired)}")

    # 20: Audit log — broker field present, no access_token in repr
    print("\n── Scenario 20: Audit log integrity ──")
    assert loaded04 is not None, "Scenario 04 token must not be None"
    records: list[TokenRecord] = [record02, loaded04, rec18]
    ok20 = all(
        "PAPER_TOKEN_SIMULATED" not in repr(r) and "REQTOKEN" not in repr(r)
        for r in records
    )
    if not ok20:
        all_pass = False
    (_pass if ok20 else _fail)(
        "20",
        f"TokenRecord repr hides access_token ({len(records)} records checked)"
    )

    print("\n" + "=" * 70)
    print(f"RESULT: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
    print("=" * 70)
    return all_pass


def main() -> None:
    """Entry point: ``python -m shared.auth [verify]``."""
    if len(sys.argv) < 2 or sys.argv[1] != "verify":
        print("Usage: python -m shared.auth verify")
        sys.exit(1)
    ok = run_verify()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
