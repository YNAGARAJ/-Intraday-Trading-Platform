# M20 — Alerting & Notification

Real-time Telegram alerts and daily email reports for all trading system events.

## Module layout

| File | Responsibility |
|------|---------------|
| `models.py` | `AlertLevel`, `AlertType`, `Alert` dataclass |
| `telegram.py` | `TelegramAlerter` — Telegram Bot API via raw requests |
| `email_sender.py` | `EmailAlerter` — SMTP STARTTLS + fpdf2 PDF attachment |
| `cost_alert.py` | `LLMCostAlerter` — daily LLM spend monitor |
| `dispatcher.py` | `AlertDispatcher` — rate-limited routing, daily report |
| `cli.py` | 20 VERIFY scenarios |

## Alert types

| AlertType | Level | Description |
|-----------|-------|-------------|
| `SIGNAL` | INFO | New trading signal generated |
| `FILL` | INFO | Order fill confirmed |
| `ERROR` | WARNING/CRITICAL | System error |
| `PNL` | INFO/WARNING | Daily P&L update |
| `CIRCUIT_BREAKER` | CRITICAL | -2% daily loss limit triggered |
| `KILL_SWITCH` | CRITICAL | System halt (any tier) |
| `RECONCILIATION_MISMATCH` | WARNING | Broker vs internal state mismatch |
| `LLM_COST` | WARNING | Daily LLM spend ≥ 80% of $1/day budget |
| `DEAD_LETTER` | WARNING | Order dead-lettered after max retries |
| `HEARTBEAT` | WARNING | Agent missed heartbeat threshold |

## Rate limiting (RULE 8)

The `AlertDispatcher` limits Telegram to `ALERT_TELEGRAM_RATE_LIMIT_PER_MINUTE = 20`
messages per 60-second window. **`KILL_SWITCH` and `CIRCUIT_BREAKER` alerts always
bypass this limit** — safety-critical events must never be suppressed.

## API reference

```python
from shared.alerts import (
    Alert, AlertLevel, AlertType,
    TelegramAlerter, EmailAlerter,
    AlertDispatcher, LLMCostAlerter,
)

# Telegram channel
tg = TelegramAlerter(bot_token="...", chat_id="...")

# Email channel (with fpdf2 PDF generation)
em = EmailAlerter(
    smtp_host="smtp.gmail.com", smtp_port=587,
    username="user@gmail.com", password="...",
    from_addr="trading@co.com", to_addrs=["ops@co.com"],
)

# Dispatcher: routes real-time alerts to Telegram, reports to email
dispatcher = AlertDispatcher(telegram=tg, email=em)

# Dispatch a real-time alert
dispatcher.dispatch(Alert(
    alert_type=AlertType.KILL_SWITCH,
    level=AlertLevel.CRITICAL,
    message="Daily P&L -2.1% — circuit breaker triggered",
))

# Send daily report
pdf = em.build_pdf("Daily Report 2026-07-02", ["P&L: +1200", "Trades: 8"])
dispatcher.dispatch_daily_report("Daily Report", "P&L summary", pdf_bytes=pdf)

# LLM cost monitoring (call once per monitor poll cycle)
cost_alerter = LLMCostAlerter(redis_client=redis, dispatcher=dispatcher)
total_usd = cost_alerter.check()   # fires WARNING if ≥ $0.80/day
```

## Settings (environment variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | `""` | Telegram Bot API token (never logged) |
| `TELEGRAM_CHAT_ID` | `""` | Target Telegram chat/channel ID |
| `SMTP_HOST` | `""` | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port (587 = STARTTLS) |
| `SMTP_USERNAME` | `""` | SMTP auth username |
| `SMTP_PASSWORD` | `""` | SMTP auth password (never logged) |
| `ALERT_EMAIL_FROM` | `""` | Sender address |
| `ALERT_EMAIL_TO` | `""` | Comma-separated recipient addresses |

All fields are optional — alerting degrades gracefully (logs a warning) when unconfigured.

## Redis keys read

| Key | Written by | Purpose |
|-----|-----------|---------|
| `sentiment:cost:daily:{YYYYMMDD}` | M10 CostTracker | Sentiment LLM spend |
| `orchestrator:llm:complex:{date}` | M18 Orchestrator | Orchestrator LLM spend |

## Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `ALERT_TELEGRAM_RATE_LIMIT_PER_MINUTE` | 20 | Max Telegram dispatches per minute |
| `LLM_COST_ALERT_THRESHOLD_USD` | 0.80 | Alert when daily LLM spend reaches this |
| `LLM_DAILY_COST_TARGET_USD` | 1.00 | Hard $1/day LLM budget ceiling |

## Standalone run

```bash
python -m shared.alerts
# Runs 20 VERIFY scenarios; prints VERIFY_SUMMARY passed=20 total=20
```
