import asyncio
import smtplib
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.core.config import settings
from app.core.logging import logger


class EmailProvider(ABC):
    """
    Abstraction so a real email service (SMTP, SendGrid, SES, etc.) can be
    plugged in later without any caller (AuthService, or any future module)
    needing to change — the same "extension point" pattern already
    established by app/services/payment_gateway.py.

    Unlike that stub, at least one concrete provider below
    (ConsoleEmailProvider) is fully wired and functional rather than raising
    NotImplementedError, so password reset / email verification actually
    work end-to-end today even with zero real email infrastructure
    configured.
    """

    @abstractmethod
    async def send_email(
        self, *, to: str, subject: str, body_text: str, body_html: Optional[str] = None
    ) -> None:
        raise NotImplementedError


class ConsoleEmailProvider(EmailProvider):
    """
    Default provider when no SMTP is configured (SMTP_HOST is empty). Logs
    the email instead of sending it. This is a deliberate dev/local fallback,
    not a stub — it's what makes the reset/verification flows testable
    end-to-end (the raw token is visible in the log) without any real mail
    server, matching the existing test methodology described in
    SESSION_HANDOFF.md §5 (no browser automation, curl/log-based
    verification).
    """

    async def send_email(
        self, *, to: str, subject: str, body_text: str, body_html: Optional[str] = None
    ) -> None:
        logger.info("[EMAIL:console] To=%s | Subject=%s\n%s", to, subject, body_text)


class SMTPEmailProvider(EmailProvider):
    """
    Real SMTP sender using the stdlib `smtplib` — no new dependency. Only
    selected when SMTP_HOST is configured (see get_email_provider() below).
    This is a genuinely working implementation once real credentials are
    supplied, not a NotImplementedError placeholder — "plug in SMTP" means
    setting env vars, not writing more code.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool,
        from_email: str,
        from_name: str,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._from_email = from_email
        self._from_name = from_name

    async def send_email(
        self, *, to: str, subject: str, body_text: str, body_html: Optional[str] = None
    ) -> None:
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"{self._from_name} <{self._from_email}>"
        message["To"] = to
        message.attach(MIMEText(body_text, "plain"))
        if body_html:
            message.attach(MIMEText(body_html, "html"))

        def _send_sync() -> None:
            with smtplib.SMTP(self._host, self._port, timeout=10) as server:
                if self._use_tls:
                    server.starttls()
                if self._username:
                    server.login(self._username, self._password)
                server.sendmail(self._from_email, [to], message.as_string())

        # smtplib is synchronous/blocking — run it off the event loop so a
        # slow or unreachable SMTP server can't stall the request handler.
        await asyncio.to_thread(_send_sync)


def get_email_provider() -> EmailProvider:
    """Factory: real SMTP once configured, console logging otherwise."""
    if settings.SMTP_HOST:
        return SMTPEmailProvider(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            use_tls=settings.SMTP_USE_TLS,
            from_email=settings.SMTP_FROM_EMAIL,
            from_name=settings.SMTP_FROM_NAME,
        )
    return ConsoleEmailProvider()
