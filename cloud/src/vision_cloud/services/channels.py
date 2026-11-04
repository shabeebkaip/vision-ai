"""Alert channels (CLD-08): one interface, one implementation per provider.

WhatsApp (CLD-09) and Telegram (CLD-10) register here. Until a provider is configured, and always
while `VISION_CLOUD_ALERT_DRY_RUN=true` (the default), messages go to `DryRunChannel`, which only
logs them, so no development or staging setup can message a real person by accident.
"""

from __future__ import annotations

from typing import Protocol

import structlog

from vision_cloud.models import Recipient
from vision_cloud.services.messages import AlertMessage
from vision_cloud.settings import CloudSettings

log = structlog.get_logger(__name__)


class ChannelError(Exception):
    """Sending failed. `retry=False` for errors a retry cannot fix (bad address, blocked bot)."""

    def __init__(self, message: str, *, retry: bool = True) -> None:
        super().__init__(message)
        self.retry = retry


class Channel(Protocol):
    name: str

    def send(self, recipient: Recipient, message: AlertMessage) -> str:
        """Send and return the provider's message id. Raise ChannelError on failure."""
        ...


class DryRunChannel:
    name = "dry_run"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, AlertMessage]] = []

    def send(self, recipient: Recipient, message: AlertMessage) -> str:
        self.sent.append((recipient.id, recipient.channel, message))
        log.info(
            "alert.dry_run",
            recipient_id=recipient.id,
            channel=recipient.channel,
            language=message.language,
            title=message.title,
        )
        return f"dry-run-{len(self.sent)}"


CHANNELS: dict[str, Channel] = {}
"""Providers by recipient channel, built from settings on first use (tests may set entries)."""

_dry_run = DryRunChannel()


def channel_for(recipient_channel: str, settings: CloudSettings) -> Channel:
    if settings.alert_dry_run:
        return _dry_run
    channel = CHANNELS.get(recipient_channel)
    if channel is None and recipient_channel == "telegram":
        from vision_cloud.services.telegram import TelegramChannel, client_from_settings

        client = client_from_settings(settings)
        if client is not None:
            channel = TelegramChannel(client)
    if channel is None:
        raise ChannelError(f"no provider configured for {recipient_channel}", retry=False)
    return channel
