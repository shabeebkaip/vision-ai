"""CLD-10: the Telegram channel against a fake Telegram.

Done-when from the plan (same as CLD-09): "alert with snapshot reaches a phone; tapping 'False
alarm' updates the event within 5 s".
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

from vision_cloud.db import system_session
from vision_cloud.jobs import InMemoryQueue
from vision_cloud.models import Alert, EventFeedback, EventRow, Notification, Recipient
from vision_cloud.services import channels, telegram
from vision_cloud.services.telegram import TelegramClient
from vision_cloud.worker import HANDLERS, WorkerContext

from .alerting import log_rows, post_events, run_jobs
from .conftest import T0, World, auth

SECRET = "webhook-secret-for-tests"
HOOK = {"X-Telegram-Bot-Api-Secret-Token": SECRET}
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 100


class FakeTelegram:
    """Answers like the Bot API and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], bool]] = []
        self.next_error: tuple[int, str] | None = None
        self.message_id = 100

    def handle(self, req: httpx.Request) -> httpx.Response:
        method = req.url.path.rsplit("/", 1)[-1]
        ctype = req.headers.get("content-type", "")
        has_file = ctype.startswith("multipart/")
        if has_file:
            fields = _multipart_fields(req)
        else:
            fields = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        self.calls.append((method, fields, has_file))
        if self.next_error:
            code, desc = self.next_error
            return httpx.Response(code, json={"ok": False, "error_code": code, "description": desc})
        self.message_id += 1
        result: Any = {"message_id": self.message_id}
        if method == "getMe":
            result = {"id": 1, "username": "codeox_test_bot", "first_name": "Code-Ox"}
        return httpx.Response(200, json={"ok": True, "result": result})

    def of(self, method: str) -> list[dict[str, Any]]:
        return [f for m, f, _ in self.calls if m == method]


def _multipart_fields(req: httpx.Request) -> dict[str, Any]:
    body = req.content
    boundary = req.headers["content-type"].split("boundary=")[1].encode()
    out: dict[str, Any] = {}
    for part in body.split(b"--" + boundary):
        if b'name="' not in part:
            continue
        head, _, value = part.partition(b"\r\n\r\n")
        name = head.split(b'name="')[1].split(b'"')[0].decode()
        out[name] = value.rstrip(b"\r\n") if name == "photo" else value.rstrip(b"\r\n").decode()
    return out


@pytest.fixture
def fake_tg(app: FastAPI) -> Iterator[FakeTelegram]:
    fake = FakeTelegram()
    telegram.CLIENT_OVERRIDE = TelegramClient(
        "123:TEST", http=httpx.Client(transport=httpx.MockTransport(fake.handle))
    )
    st = app.state.vision
    original = st.settings
    st.settings = original.model_copy(
        update={
            "alert_dry_run": False,
            "telegram_webhook_secret": SecretStr(SECRET),
            "telegram_bot_username": "codeox_test_bot",
        }
    )
    channels.CHANNELS.clear()
    yield fake
    telegram.CLIENT_OVERRIDE = None
    channels.CHANNELS.clear()
    st.settings = original


@pytest.fixture
def tg_ctx(
    app: FastAPI, queue: InMemoryQueue, fake_tg: FakeTelegram, ctx: WorkerContext
) -> WorkerContext:
    return WorkerContext(app.state.vision.settings, ctx.sessions, ctx.storage, queue, ctx.cipher)


def linked_recipient(world: World, chat_id: str = "5550001", **kw: Any) -> dict[str, Any]:
    body = {"name": "Duty manager", "channel": "telegram", "address": chat_id, **kw}
    r = world.client.post("/api/v1/recipients", json=body, headers=auth(world.a.owner_token))
    assert r.status_code == 201, r.text
    return dict(r.json())


def start(world: World, chat_id: int, text: str, lang: str = "en") -> httpx.Response:
    update = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "first_name": "Sara", "language_code": lang},
            "text": text,
        },
    }
    return world.client.post("/integrations/telegram/webhook", json=update, headers=HOOK)


def tap(world: World, chat_id: str, data: str, message_id: int = 101) -> httpx.Response:
    update = {
        "update_id": 2,
        "callback_query": {
            "id": "cb-1",
            "from": {"id": int(chat_id), "username": "sara_k"},
            "message": {"message_id": message_id, "chat": {"id": int(chat_id)}},
            "data": data,
        },
    }
    return world.client.post("/integrations/telegram/webhook", json=update, headers=HOOK)


def alert_with_snapshot(
    world: World, app: FastAPI, ctx: WorkerContext, queue: InMemoryQueue, hours: int, **kw: Any
) -> str:
    """Post an event, attach a snapshot as the edge's upload would, dispatch it."""
    [event_id] = post_events(world, [T0 + timedelta(hours=hours)], **kw)
    key = f"test/{event_id}.jpg"
    ctx.storage.put_bytes(key, JPEG, "image/jpeg")
    with system_session(app.state.vision.sessions) as db:
        db.get(EventRow, event_id).snapshot_key = key  # type: ignore[union-attr]
        db.commit()
    run_jobs(ctx, queue)
    return event_id


# --------------------------------------------------------------------------- done-when


def test_alert_with_snapshot_and_false_alarm_tap(
    world: World,
    app: FastAPI,
    tg_ctx: WorkerContext,
    clean_queue: InMemoryQueue,
    fake_tg: FakeTelegram,
) -> None:
    rec = linked_recipient(world, escalation_rank=None)
    linked_recipient(world, chat_id="5550002", name="Store manager", escalation_rank=2)
    event_id = alert_with_snapshot(world, app, tg_ctx, clean_queue, 1, severity="critical")

    [photo] = fake_tg.of("sendPhoto")
    assert photo["chat_id"] == "5550001" and photo["photo"] == JPEG
    assert "Critical" in photo["caption"]
    buttons = json.loads(photo["reply_markup"])["inline_keyboard"]
    [row] = [n for n in log_rows(app) if n.recipient_id == rec["id"]]
    assert row.status == "sent" and row.provider_message_id == "101"
    assert [b["callback_data"] for b in buttons[0]] == [f"fb:t:{row.id}", f"fb:f:{row.id}"]
    assert buttons[1][0]["callback_data"] == f"ack:{row.id}"

    started = time.monotonic()
    assert tap(world, "5550001", f"fb:f:{row.id}").status_code == 200
    with system_session(app.state.vision.sessions) as db:
        event = db.get(EventRow, event_id)
        assert event is not None and event.verified is False  # the false alarm is recorded
        fb = db.scalars(select(EventFeedback).where(EventFeedback.event_id == event_id)).one()
        assert (fb.channel, fb.is_true, fb.comment) == ("telegram", False, "telegram:sara_k")
        alert = db.get(Alert, row.alert_id)
        assert alert is not None and alert.status == "acknowledged"
    assert time.monotonic() - started < 5
    [edit] = fake_tg.of("editMessageReplyMarkup")
    assert edit["message_id"] == "101"
    [[label]] = json.loads(edit["reply_markup"])["inline_keyboard"]
    assert label["text"] == "❌ Marked false alarm"  # the buttons are replaced by the answer
    [answer] = fake_tg.of("answerCallbackQuery")
    assert answer["text"] == "Thanks: marked as a false alarm"

    # Acknowledged, so the store manager is not woken up by an escalation.
    for _, job, payload in list(clean_queue.delayed):
        HANDLERS[job](tg_ctx, payload)
    run_jobs(tg_ctx, clean_queue)
    assert len(fake_tg.of("sendPhoto")) == 1


def test_correct_and_on_it_buttons_in_arabic(
    world: World,
    app: FastAPI,
    tg_ctx: WorkerContext,
    clean_queue: InMemoryQueue,
    fake_tg: FakeTelegram,
) -> None:
    linked_recipient(world, language="ar")
    event_id = alert_with_snapshot(world, app, tg_ctx, clean_queue, 2)
    [photo] = fake_tg.of("sendPhoto")
    assert "الكاميرا" in photo["caption"]
    buttons = json.loads(photo["reply_markup"])["inline_keyboard"]
    assert buttons[0][0]["text"] == "✅ صحيح"
    [row] = log_rows(app)
    tap(world, "5550001", f"ack:{row.id}")
    assert fake_tg.of("answerCallbackQuery")[-1]["text"] == "شكراً: أنت تتولى الأمر"
    tap(world, "5550001", f"fb:t:{row.id}")
    with system_session(app.state.vision.sessions) as db:
        assert db.get(EventRow, event_id).verified is True  # type: ignore[union-attr]
    tap(world, "5550001", "done")  # the "answered" label: only the spinner stops
    assert len(fake_tg.of("answerCallbackQuery")) == 3


def test_a_tap_from_another_chat_changes_nothing(
    world: World,
    app: FastAPI,
    tg_ctx: WorkerContext,
    clean_queue: InMemoryQueue,
    fake_tg: FakeTelegram,
) -> None:
    linked_recipient(world)
    event_id = alert_with_snapshot(world, app, tg_ctx, clean_queue, 3)
    [row] = log_rows(app)
    tap(world, "9990009", f"fb:f:{row.id}")  # e.g. the alert forwarded to someone else
    with system_session(app.state.vision.sessions) as db:
        assert db.get(EventRow, event_id).verified is None  # type: ignore[union-attr]
        assert db.get(Alert, row.alert_id).status == "open"  # type: ignore[union-attr]
    assert fake_tg.of("answerCallbackQuery")[-1]["text"] == "This alert was sent to another chat"
    assert fake_tg.of("editMessageReplyMarkup") == []


# --------------------------------------------------------------------------- linking


def test_linking_a_chat_with_a_one_time_code(
    world: World,
    app: FastAPI,
    tg_ctx: WorkerContext,
    clean_queue: InMemoryQueue,
    fake_tg: FakeTelegram,
) -> None:
    c, owner = world.client, auth(world.a.owner_token)
    rec = linked_recipient(world, chat_id="", name="Sara", name_ar="سارة", language="ar")
    post_events(world, [T0 + timedelta(hours=4)])
    run_jobs(tg_ctx, clean_queue)
    assert [(n.status, n.reason) for n in log_rows(app)] == [("suppressed", "not_linked")]

    r = c.post(f"/api/v1/recipients/{rec['id']}/telegram-link", headers=owner)
    assert r.status_code == 200, r.text
    link = r.json()
    assert link["url"] == f"https://t.me/codeox_test_bot?start={link['code']}"

    assert start(world, 4242, f"/start {link['code']}").status_code == 200
    got = c.get(f"/api/v1/recipients/{rec['id']}", headers=owner).json()
    assert got["address"] == "4242" and got["opted_in_at"]
    assert "سارة" in fake_tg.of("sendMessage")[-1]["text"]  # confirmed in the person's language

    start(world, 7777, f"/start {link['code']}")  # single use
    assert "invalid" in fake_tg.of("sendMessage")[-1]["text"]
    assert c.get(f"/api/v1/recipients/{rec['id']}", headers=owner).json()["address"] == "4242"

    post_events(world, [T0 + timedelta(hours=5)])
    run_jobs(tg_ctx, clean_queue)
    assert fake_tg.of("sendMessage")[-1]["chat_id"] == "4242"  # alerts now reach the chat


def test_link_codes_expire_and_need_rights(
    world: World, app: FastAPI, fake_tg: FakeTelegram
) -> None:
    c, a, owner = world.client, world.a, auth(world.a.owner_token)
    rec = linked_recipient(world, chat_id="", site_id=a.site_ids[0])
    code = c.post(f"/api/v1/recipients/{rec['id']}/telegram-link", headers=owner).json()["code"]
    with system_session(app.state.vision.sessions) as db:
        r = db.get(Recipient, rec["id"])
        assert r is not None and r.telegram_link_code_hash != code  # only the hash is stored
        r.telegram_link_expires_at = r.telegram_link_expires_at - timedelta(days=2)  # type: ignore[operator]
        db.commit()
    start(world, 4242, f"/start {code}")
    assert "invalid" in fake_tg.of("sendMessage")[-1]["text"]

    wa = c.post(
        "/api/v1/recipients",
        json={"name": "WA", "channel": "whatsapp", "address": "+966501234567"},
        headers=owner,
    ).json()
    assert c.post(f"/api/v1/recipients/{wa['id']}/telegram-link", headers=owner).status_code == 409
    viewer = auth(world.invite(a, "v9@alpha.test", "viewer", [a.site_ids[0]]))
    assert (
        c.post(f"/api/v1/recipients/{rec['id']}/telegram-link", headers=viewer).status_code == 403
    )
    other = auth(world.b.owner_token)
    assert c.post(f"/api/v1/recipients/{rec['id']}/telegram-link", headers=other).status_code == 404
    start(world, 4242, "/start")  # no code: a friendly hello
    assert "dashboard" in fake_tg.of("sendMessage")[-1]["text"]


def test_webhook_requires_the_secret(world: World, app: FastAPI, fake_tg: FakeTelegram) -> None:
    c = world.client
    update = {"update_id": 9, "message": {"chat": {"id": 1}, "text": "/start x"}}
    assert c.post("/integrations/telegram/webhook", json=update).status_code == 401
    bad = {"X-Telegram-Bot-Api-Secret-Token": "nope"}
    assert c.post("/integrations/telegram/webhook", json=update, headers=bad).status_code == 401
    assert (
        c.post("/integrations/telegram/webhook", content=b"not json", headers=HOOK).status_code
        == 200
    )
    st = app.state.vision
    st.settings = st.settings.model_copy(update={"telegram_webhook_secret": None})
    assert c.post("/integrations/telegram/webhook", json=update, headers=HOOK).status_code == 404


# --------------------------------------------------------------------------- sending


def test_waits_briefly_for_the_snapshot(
    world: World,
    app: FastAPI,
    tg_ctx: WorkerContext,
    clean_queue: InMemoryQueue,
    fake_tg: FakeTelegram,
) -> None:
    linked_recipient(world)
    st = app.state.vision
    st.settings = st.settings.model_copy(update={"alert_media_wait_s": 20})
    wait_ctx = WorkerContext(
        st.settings, tg_ctx.sessions, tg_ctx.storage, clean_queue, tg_ctx.cipher
    )
    [event_id] = post_events(world, [T0 + timedelta(hours=6)])
    run_jobs(wait_ctx, clean_queue)
    assert fake_tg.calls == []  # not sent yet: the snapshot is still on its way
    [(delay, job, payload)] = clean_queue.delayed
    assert job == "notification.send" and 1 <= delay <= 5

    key = f"test/{event_id}.jpg"  # the snapshot arrives
    tg_ctx.storage.put_bytes(key, JPEG, "image/jpeg")
    with system_session(st.sessions) as db:
        db.get(EventRow, event_id).snapshot_key = key  # type: ignore[union-attr]
        db.commit()
    clean_queue.delayed.clear()
    HANDLERS[job](wait_ctx, payload)
    assert len(fake_tg.of("sendPhoto")) == 1

    # A site whose snapshot never comes: after the wait the alert goes out as text.
    [late_id] = post_events(world, [T0 + timedelta(hours=7)])
    with system_session(st.sessions) as db:
        ev = db.get(EventRow, late_id)
        assert ev is not None
        ev.received_at = ev.received_at - timedelta(seconds=30)
        db.commit()
    run_jobs(wait_ctx, clean_queue)
    assert clean_queue.delayed == [] and len(fake_tg.of("sendMessage")) == 1


@pytest.mark.parametrize(
    ("code", "desc", "retry"),
    [
        (403, "Forbidden: bot was blocked by the user", False),
        (400, "Bad Request: chat not found", False),
        (429, "Too Many Requests: retry after 3", True),
        (502, "Bad Gateway", True),
    ],
)
def test_send_errors(
    world: World,
    app: FastAPI,
    tg_ctx: WorkerContext,
    clean_queue: InMemoryQueue,
    fake_tg: FakeTelegram,
    code: int,
    desc: str,
    retry: bool,
) -> None:
    linked_recipient(world)
    fake_tg.next_error = (code, desc)
    post_events(world, [T0 + timedelta(hours=8)])
    HANDLERS["event.created"](tg_ctx, clean_queue.jobs.pop(0)[1])
    [(job, payload)] = clean_queue.jobs
    if retry:
        with pytest.raises(channels.ChannelError):
            HANDLERS[job](tg_ctx, payload)  # the job queue will retry it
        [row] = log_rows(app)
        assert row.status == "queued" and row.attempts == 1
    else:
        HANDLERS[job](tg_ctx, payload)
        [row] = log_rows(app)
        assert row.status == "failed" and desc in (row.last_error or "")
    assert "123:TEST" not in (row.last_error or "")  # the token never reaches the log


def test_cli_check(
    fake_tg: FakeTelegram, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from vision_cloud.cli import main
    from vision_cloud.security import generate_field_key

    # The CLI reads settings from the environment; CI has no .env.
    monkeypatch.setenv("VISION_CLOUD_JWT_SECRET", "x" * 48)
    monkeypatch.setenv("VISION_CLOUD_FIELD_ENCRYPTION_KEY", generate_field_key())

    assert main(["telegram", "check"]) == 0
    assert "OK: bot @codeox_test_bot" in capsys.readouterr().out


def test_notifications_without_a_chat_are_never_sent(
    world: World,
    app: FastAPI,
    tg_ctx: WorkerContext,
    clean_queue: InMemoryQueue,
    fake_tg: FakeTelegram,
) -> None:
    linked_recipient(world, chat_id="", escalation_rank=2)
    linked_recipient(world)
    post_events(world, [T0 + timedelta(hours=9)], severity="critical")
    run_jobs(tg_ctx, clean_queue)
    for _, job, payload in list(clean_queue.delayed):
        HANDLERS[job](tg_ctx, payload)
    run_jobs(tg_ctx, clean_queue)
    with system_session(app.state.vision.sessions) as db:
        rows = db.scalars(select(Notification).where(Notification.kind == "escalation")).all()
    assert [(n.status, n.reason) for n in rows] == [("suppressed", "not_linked")]
