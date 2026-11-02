"""Outgoing email (invitations, password resets). SMTP in staging/production."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

import structlog

from vision_cloud.settings import CloudSettings

log = structlog.get_logger(__name__)


@dataclass
class Mail:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    def send(self, mail: Mail) -> None: ...


@dataclass
class MemoryMailer:
    outbox: list[Mail] = field(default_factory=list)

    def send(self, mail: Mail) -> None:
        self.outbox.append(mail)


class ConsoleMailer:
    """Development only: prints the mail (it contains one-time links) to the log."""

    def send(self, mail: Mail) -> None:
        log.info("mail.console", to=mail.to, subject=mail.subject, body=mail.body)


class SmtpMailer:
    def __init__(self, settings: CloudSettings) -> None:
        if not settings.smtp_host:
            raise SystemExit("VISION_SMTP_HOST is required when VISION_MAIL_BACKEND=smtp")
        self._s = settings

    def send(self, mail: Mail) -> None:
        msg = EmailMessage()
        msg["From"] = self._s.mail_from
        msg["To"] = mail.to
        msg["Subject"] = mail.subject
        msg.set_content(mail.body)
        with smtplib.SMTP(self._s.smtp_host or "", self._s.smtp_port, timeout=15) as smtp:
            if self._s.smtp_starttls:
                smtp.starttls()
            if self._s.smtp_username and self._s.smtp_password:
                smtp.login(self._s.smtp_username, self._s.smtp_password.get_secret_value())
            smtp.send_message(msg)
        log.info("mail.sent", subject=mail.subject)


def make_mailer(settings: CloudSettings) -> Mailer:
    if settings.mail_backend == "memory":
        return MemoryMailer()
    if settings.mail_backend == "smtp":
        return SmtpMailer(settings)
    if settings.environment in {"staging", "production"}:
        raise SystemExit("VISION_MAIL_BACKEND=console would log one-time links; use smtp")
    return ConsoleMailer()
