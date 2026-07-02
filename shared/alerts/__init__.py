"""M20 Alerting & Notification — public API.

Channels:
- ``TelegramAlerter`` — Telegram Bot API (raw requests, no SDK).
- ``EmailAlerter`` — SMTP STARTTLS with optional fpdf2 PDF attachment.

Routing:
- ``AlertDispatcher`` — rate-limited Telegram dispatch + daily email report.

Cost monitoring:
- ``LLMCostAlerter`` — reads Redis daily LLM spend; fires at 80% of $1/day budget.

Models:
- ``Alert``, ``AlertLevel``, ``AlertType``.
"""

from shared.alerts.cost_alert import LLMCostAlerter
from shared.alerts.dispatcher import AlertDispatcher
from shared.alerts.email_sender import EmailAlerter
from shared.alerts.models import Alert, AlertLevel, AlertType
from shared.alerts.telegram import TelegramAlerter

__all__ = [
    "Alert",
    "AlertDispatcher",
    "AlertLevel",
    "AlertType",
    "EmailAlerter",
    "LLMCostAlerter",
    "TelegramAlerter",
]
