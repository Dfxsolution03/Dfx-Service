"""
JROS Service Tests — Email Provider Abstraction (Module 18)
==============================================================

Pure unit tests, no DB, no real network I/O. `ConsoleEmailProvider` is
exercised directly (it's fully functional, not a stub); `SMTPEmailProvider`
is exercised only for construction/selection logic, never against a real
SMTP server.
"""

import pytest

from app.services.email_service import (
    ConsoleEmailProvider,
    SMTPEmailProvider,
    EmailProvider,
    get_email_provider,
)
from app.core.config import settings


class TestConsoleEmailProvider:
    async def test_send_email_does_not_raise(self, caplog):
        provider = ConsoleEmailProvider()
        await provider.send_email(to="test@example.com", subject="Hello", body_text="Body text")

    async def test_logs_recipient_and_subject(self, caplog):
        import logging
        caplog.set_level(logging.INFO, logger="jros_backend")
        provider = ConsoleEmailProvider()
        await provider.send_email(to="test@example.com", subject="A Test Subject", body_text="Body text")
        assert "test@example.com" in caplog.text
        assert "A Test Subject" in caplog.text


class TestGetEmailProvider:
    def test_defaults_to_console_when_smtp_host_unset(self):
        original = settings.SMTP_HOST
        settings.SMTP_HOST = ""
        try:
            provider = get_email_provider()
            assert isinstance(provider, ConsoleEmailProvider)
        finally:
            settings.SMTP_HOST = original

    def test_returns_smtp_provider_when_configured(self):
        original = settings.SMTP_HOST
        settings.SMTP_HOST = "smtp.example.com"
        try:
            provider = get_email_provider()
            assert isinstance(provider, SMTPEmailProvider)
        finally:
            settings.SMTP_HOST = original


class TestEmailProviderIsAbstract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            EmailProvider()
