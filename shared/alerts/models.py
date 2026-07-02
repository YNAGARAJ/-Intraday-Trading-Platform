"""M20 Alerting & Notification — alert data models."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class AlertLevel(str, Enum):
    """Severity level for an alert."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertType(str, Enum):
    """Discriminator for the kind of event that generated an alert."""

    SIGNAL = "SIGNAL"
    FILL = "FILL"
    ERROR = "ERROR"
    PNL = "PNL"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    KILL_SWITCH = "KILL_SWITCH"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    LLM_COST = "LLM_COST"
    DEAD_LETTER = "DEAD_LETTER"
    HEARTBEAT = "HEARTBEAT"


@dataclass
class Alert:
    """A single alert event dispatched to one or more channels.

    Attributes:
        alert_type: Category of the event.
        level: Severity (INFO / WARNING / CRITICAL).
        message: Human-readable alert text.
        timestamp_ms: Unix epoch milliseconds (defaults to now).
        metadata: Optional key-value pairs for structured context.
    """

    alert_type: AlertType
    level: AlertLevel
    message: str
    timestamp_ms: float = field(default_factory=lambda: time.time() * 1000)
    metadata: dict[str, str] = field(default_factory=dict)
