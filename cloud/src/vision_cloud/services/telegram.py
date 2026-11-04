"""Telegram Bot API client (CLD-10), on httpx.

Only what alerts need: send a photo or text with inline buttons, answer a button tap, replace the
buttons after an answer, and set up the webhook. Errors are sorted into "a retry may help"
(network, 429, 5xx) and "it will not" (unknown chat, bot blocked, bad request).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from vision_cloud.services.channels import ChannelError

log = structlog.get_logger(__name__)

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096


class TelegramClient:
    def __init__(
        self,
        token: str,
        *,
        api_base: str = "https://api.telegram.org",
        http: httpx.Client | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        self._base = f"{api_base.rstrip('/')}/bot{token}"
        self._http = http or httpx.Client(timeout=timeout_s)

    def call(
        self, method: str, data: dict[str, Any], files: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Call a Bot API method; returns `result`. Raises ChannelError."""
        form = {k: json.dumps(v) if isinstance(v, dict | list) else v for k, v in data.items()}
        try:
            if files:
                r = self._http.post(f"{self._base}/{method}", data=form, files=files)
            else:
                r = self._http.post(f"{self._base}/{method}", data=form)
        except httpx.HTTPError as exc:
            raise ChannelError(f"telegram unreachable: {type(exc).__name__}") from exc
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code == 200 and body.get("ok"):
            result = body.get("result")
            return result if isinstance(result, dict) else {"value": result}
        description = str(body.get("description") or r.text[:200])
        retry = r.status_code == 429 or r.status_code >= 500
        # The token never appears in the error: only the method and Telegram's description.
        raise ChannelError(f"telegram {method}: {r.status_code} {description}", retry=retry)

    def send_alert(
        self,
        chat_id: str,
        text: str,
        buttons: list[list[dict[str, str]]],
        photo: bytes | None = None,
    ) -> str:
        markup = {"inline_keyboard": buttons}
        if photo is not None and len(text) <= CAPTION_LIMIT:
            result = self.call(
                "sendPhoto",
                {"chat_id": chat_id, "caption": text, "reply_markup": markup},
                files={"photo": ("snapshot.jpg", photo, "image/jpeg")},
            )
        else:
            result = self.call(
                "sendMessage",
                {"chat_id": chat_id, "text": text[:TEXT_LIMIT], "reply_markup": markup},
            )
        return str(result.get("message_id", ""))

    def answer_callback(self, callback_id: str, text: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def replace_buttons(
        self, chat_id: str, message_id: str, buttons: list[list[dict[str, str]]]
    ) -> None:
        self.call(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": buttons},
            },
        )

    def send_text(self, chat_id: str, text: str) -> None:
        self.call("sendMessage", {"chat_id": chat_id, "text": text[:TEXT_LIMIT]})

    def get_me(self) -> dict[str, Any]:
        return self.call("getMe", {})

    def set_webhook(self, url: str, secret: str) -> None:
        self.call(
            "setWebhook",
            {"url": url, "secret_token": secret, "allowed_updates": ["message", "callback_query"]},
        )


# --------------------------------------------------------------------------- the alert channel


def alert_buttons(ref: str, language: str) -> list[list[dict[str, str]]]:
    """callback_data is at most 64 bytes: "fb:t:" + a 36-character id fits."""
    from vision_cloud.services.messages import t

    return [
        [
            {"text": t("correct", language), "callback_data": f"fb:t:{ref}"},
            {"text": t("false_alarm", language), "callback_data": f"fb:f:{ref}"},
        ],
        [{"text": t("on_it", language), "callback_data": f"ack:{ref}"}],
    ]


class TelegramChannel:
    name = "telegram"

    def __init__(self, client: TelegramClient) -> None:
        self.client = client

    def send(self, recipient: Any, message: Any) -> str:
        if not recipient.address:
            raise ChannelError("recipient has not linked a Telegram chat yet", retry=False)
        buttons = alert_buttons(message.ref, message.language) if message.ref else []
        return self.client.send_alert(recipient.address, message.text, buttons, message.snapshot)


_clients: dict[str, TelegramClient] = {}
CLIENT_OVERRIDE: TelegramClient | None = None
"""Tests point this at a fake Telegram."""


def client_from_settings(settings: Any) -> TelegramClient | None:
    if CLIENT_OVERRIDE is not None:
        return CLIENT_OVERRIDE
    if not settings.telegram_bot_token:
        return None
    token = settings.telegram_bot_token.get_secret_value()
    if token not in _clients:
        _clients[token] = TelegramClient(token, api_base=settings.telegram_api_base)
    return _clients[token]
