"""Telegram webhook and chat linking (CLD-10).

Linking: a manager calls `POST /api/v1/recipients/{id}/telegram-link` and gives the person the
t.me link (or the code). Opening it sends `/start <code>` to the bot; the webhook stores the chat id
as the recipient's address. The code is single-use, expires (24 h) and only its hash is stored.

Buttons: every alert carries "Correct", "False alarm" and "I'm on it" with the delivery-log row id.
A tap is accepted only from the chat the alert was sent to. "Correct"/"False alarm" store feedback
on the event (as the dashboard does) and acknowledge the alert; "I'm on it" acknowledges it. Either
stops escalation. The buttons are then replaced by the answer.

Telegram retries a webhook that does not answer 200, so the webhook always answers 200 once the
secret header matched; problems are logged.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import timedelta
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Header, Request
from sqlalchemy import select

from vision_cloud.api.deps import DbDep, PrincipalDep, StateDep, audit
from vision_cloud.api.manage import _audit
from vision_cloud.api.recipients import _may_edit, get_recipient
from vision_cloud.db import system_session, utcnow
from vision_cloud.errors import AppError
from vision_cloud.models import Alert, EventFeedback, EventRow, Notification, Recipient
from vision_cloud.schemas import TelegramLinkOut
from vision_cloud.security import token_hash
from vision_cloud.services.channels import ChannelError
from vision_cloud.services.dispatch import acknowledge
from vision_cloud.services.messages import t
from vision_cloud.services.telegram import TelegramClient, client_from_settings

log = structlog.get_logger(__name__)
router = APIRouter(tags=["telegram"])


# --------------------------------------------------------------------------- linking


@router.post("/api/v1/recipients/{recipient_id}/telegram-link", response_model=TelegramLinkOut)
def create_link(
    recipient_id: str, principal: PrincipalDep, db: DbDep, state: StateDep, request: Request
) -> TelegramLinkOut:
    r = get_recipient(db, principal, recipient_id)
    _may_edit(principal, r, r.site_id)
    if r.channel != "telegram":
        raise AppError(409, "this recipient does not use Telegram")
    code = secrets.token_urlsafe(18)  # 24 characters of [A-Za-z0-9_-], what /start accepts
    r.telegram_link_code_hash = token_hash(code)
    r.telegram_link_expires_at = utcnow() + timedelta(seconds=state.settings.telegram_link_ttl_s)
    _audit(db, request, principal, "recipient.telegram_link_created", "recipient", r.id)
    db.commit()
    username = state.settings.telegram_bot_username
    return TelegramLinkOut(
        code=code,
        url=f"https://t.me/{username}?start={code}" if username else None,
        expires_at=r.telegram_link_expires_at,
    )


# --------------------------------------------------------------------------- webhook


def _reply(client: TelegramClient | None, chat_id: str, text: str) -> None:
    if client is None:
        return
    try:
        client.send_text(chat_id, text)
    except ChannelError as exc:
        log.warning("telegram.reply_failed", error=str(exc))


def _handle_start(state: Any, request: Request, msg: dict[str, Any]) -> None:
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = str(msg.get("text", "")).strip()
    lang = "ar" if str(msg.get("from", {}).get("language_code", "")).startswith("ar") else "en"
    client = client_from_settings(state.settings)
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        _reply(client, chat_id, t("hello", lang))
        return
    with system_session(state.sessions) as db:
        r = db.scalar(
            select(Recipient).where(Recipient.telegram_link_code_hash == token_hash(parts[1]))
        )
        expires = r.telegram_link_expires_at if r else None
        if r is None or r.channel != "telegram" or expires is None or expires <= utcnow():
            _reply(client, chat_id, t("link_invalid", lang))
            return
        r.address = chat_id
        r.opted_in_at = utcnow()
        r.telegram_link_code_hash = None
        r.telegram_link_expires_at = None
        audit(
            db,
            request,
            organisation_id=r.organisation_id,
            action="recipient.telegram_linked",
            entity_type="recipient",
            entity_id=r.id,
            details={},
        )
        db.commit()
        name = (r.name_ar if r.language == "ar" and r.name_ar else r.name) or r.name
        language = r.language
    log.info("telegram.linked")
    _reply(client, chat_id, t("linked", language, name=name))


ACTIONS = {"fb:t": "correct", "fb:f": "false_alarm", "ack": "on_it"}
REPLIES = {  # action -> (text of the tap's answer, label that replaces the buttons)
    "correct": ("thanks_correct", "answered_correct"),
    "false_alarm": ("thanks_false", "answered_false"),
    "on_it": ("thanks_on_it", "answered_on_it"),
}


def _handle_callback(state: Any, cb: dict[str, Any]) -> None:
    client = client_from_settings(state.settings)
    data = str(cb.get("data", ""))
    action_key, _, ref = data.rpartition(":")
    action = ACTIONS.get(action_key)
    message = cb.get("message") or {}
    chat_id = str(message.get("chat", {}).get("id", ""))
    who_from = cb.get("from") or {}
    who = "telegram:" + str(
        who_from.get("username") or who_from.get("first_name") or who_from.get("id", "")
    )
    answer = None
    with system_session(state.sessions) as db:
        n = db.get(Notification, ref) if action else None
        r = db.get(Recipient, n.recipient_id) if n and n.recipient_id else None
        lang = r.language if r else "en"
        if n is None or r is None:
            pass  # e.g. the "answered" label tapped again: just stop the spinner below
        elif not chat_id or chat_id != r.address:
            answer = t("not_yours", lang)  # e.g. a forwarded alert tapped in another chat
        else:
            alert = db.get(Alert, n.alert_id) if n.alert_id else None
            if action in ("correct", "false_alarm"):
                is_true = action == "correct"
                event = db.get(EventRow, n.event_id)
                if event is not None:
                    db.add(
                        EventFeedback(
                            organisation_id=n.organisation_id,
                            event_id=event.id,
                            is_true=is_true,
                            channel="telegram",
                            comment=who,
                        )
                    )
                    event.verified = is_true
            if alert is not None:
                acknowledge(alert, who)
            db.commit()
            log.info("telegram.answered", action=action, alert_id=n.alert_id)
            thanks, done_label = REPLIES[action or "on_it"]
            answer = t(thanks, lang)
            if client is not None and message.get("message_id"):
                try:
                    client.replace_buttons(
                        chat_id,
                        str(message["message_id"]),
                        [[{"text": t(done_label, lang), "callback_data": "done"}]],
                    )
                except ChannelError as exc:
                    log.warning("telegram.edit_failed", error=str(exc))
    if client is not None and cb.get("id"):
        try:
            client.answer_callback(str(cb["id"]), answer or "")
        except ChannelError as exc:
            log.warning("telegram.answer_failed", error=str(exc))


@router.post("/integrations/telegram/webhook", include_in_schema=False)
async def webhook(
    request: Request,
    state: StateDep,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> dict[str, bool]:
    expected = state.settings.telegram_webhook_secret
    if expected is None:
        raise AppError(404, "not found")
    if secret is None or not hmac.compare_digest(secret, expected.get_secret_value()):
        raise AppError(401, "bad webhook secret")
    try:
        update = await request.json()
    except ValueError:
        return {"ok": True}
    if not isinstance(update, dict):
        return {"ok": True}
    try:
        if isinstance(update.get("callback_query"), dict):
            _handle_callback(state, update["callback_query"])
        elif isinstance(update.get("message"), dict):
            msg = update["message"]
            if str(msg.get("text", "")).startswith("/start"):
                _handle_start(state, request, msg)
    except Exception:  # never make Telegram retry an update we cannot handle
        log.exception("telegram.update_failed", update_id=update.get("update_id"))
    return {"ok": True}
