"""M20 Alerting & Notification — SMTP email channel with fpdf2 PDF generation.

SMTP credentials are never logged.
"""

from __future__ import annotations

import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from shared.alerts.models import Alert

logger = structlog.get_logger(__name__)


class EmailAlerter:
    """Sends alert emails (including daily PDF reports) via SMTP STARTTLS.

    Args:
        smtp_host: SMTP server hostname.
        smtp_port: SMTP port (587 for STARTTLS).
        username: SMTP auth username (never logged).
        password: SMTP auth password (never logged).
        from_addr: Sender address.
        to_addrs: List of recipient addresses.
    """

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: list[str],
    ) -> None:
        self._host = smtp_host
        self._port = smtp_port
        self._username = username
        self._password = password
        self._from = from_addr
        self._to = to_addrs

    def build_pdf(self, title: str, lines: list[str]) -> bytes:
        """Generate a minimal PDF report using fpdf2.

        Args:
            title: Report title displayed at the top.
            lines: Body lines, one per row.

        Returns:
            Raw PDF bytes ready for email attachment.
        """
        from fpdf import FPDF  # lazy import; fpdf2 optional at module load

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("helvetica", "B", 16)
        pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", size=11)
        for line in lines:
            pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())

    def send(self, message: str) -> bool:
        """Send a plain-text alert email with the message as subject and body.

        Args:
            message: Alert text used as both subject prefix and body.

        Returns:
            True on success, False on any SMTP or network error.
        """
        return self.send_daily_report(
            subject=f"[Trading Alert] {message[:80]}",
            body=message,
        )

    def send_daily_report(
        self,
        subject: str,
        body: str,
        pdf_bytes: bytes | None = None,
    ) -> bool:
        """Send an email with an optional PDF attachment.

        Args:
            subject: Email subject line.
            body: Plain-text body.
            pdf_bytes: Optional PDF to attach as ``daily_report.pdf``.

        Returns:
            True on success, False if unconfigured or SMTP fails.
        """
        if not self._host or not self._to:
            logger.warning("email_not_configured")
            return False
        try:
            msg = MIMEMultipart()
            msg["From"] = self._from
            msg["To"] = ", ".join(self._to)
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))
            if pdf_bytes is not None:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(pdf_bytes)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename="daily_report.pdf",
                )
                msg.attach(part)
            with smtplib.SMTP(self._host, self._port, timeout=10) as server:
                server.starttls()
                if self._username:
                    server.login(self._username, self._password)
                server.sendmail(self._from, self._to, msg.as_string())
            logger.info("email_sent", subject=subject, recipient_count=len(self._to))
            return True
        except Exception as exc:
            logger.warning("email_send_error", error=str(exc))
            return False

    @classmethod
    def from_alert(cls, alert: Alert) -> str:
        """Format an Alert as a plain-text email body string."""
        lines = [
            f"Type:    {alert.alert_type.value}",
            f"Level:   {alert.level.value}",
            f"Message: {alert.message}",
        ]
        if alert.metadata:
            lines.append("Context:")
            for k, v in alert.metadata.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)
