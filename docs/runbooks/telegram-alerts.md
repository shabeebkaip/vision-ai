# Telegram alerts: setup (SET-07, CLD-10)

How to connect the real Telegram bot. Until these steps are done, alerts are only logged
(`VISION_CLOUD_ALERT_DRY_RUN=true`).

## 1. Create the bot (once)

1. In Telegram, open **@BotFather** and send `/newbot`. Choose a name ("Code-Ox Vision") and a
   username ending in `bot` (for example `codeox_vision_bot`).
2. BotFather replies with a **token** like `123456789:AA...`. It is a password: keep it in the
   secrets vault (SET-13), never in chat, email or Git.
3. Optional: `/setdescription` and `/setuserpic` so people recognise the bot.

## 2. Configure the cloud

In the environment of the API **and** the worker (the dev stack's `.env`, or the server's secrets):

```bash
VISION_CLOUD_TELEGRAM_BOT_TOKEN=123456789:AA...          # from BotFather
VISION_CLOUD_TELEGRAM_BOT_USERNAME=codeox_vision_bot     # without @, for the link buttons
VISION_CLOUD_TELEGRAM_WEBHOOK_SECRET=<a long random string>
VISION_CLOUD_ALERT_DRY_RUN=false                         # actually send
```

Generate the webhook secret with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.

Check the token:

```bash
uv run vision-cloud telegram check
```

## 3. Tell Telegram where to send button taps

Telegram calls the API over the internet, on **https** only (staging: `https://staging.vision.code-ox.com`).

```bash
uv run vision-cloud telegram set-webhook https://staging.vision.code-ox.com
```

On a laptop, alerts still arrive without this step; only the buttons and linking need it. A tunnel
(for example `cloudflared tunnel --url http://localhost:8000`) gives a temporary https URL.

## 4. Add a person

1. Dashboard (or `POST /api/v1/recipients`): add a recipient with channel **telegram** and no
   address, in English or Arabic.
2. `POST /api/v1/recipients/{id}/telegram-link` returns a `t.me/...?start=...` link, valid 24 hours
   and usable once. Send it to the person.
3. They open it and tap **Start**. The bot confirms in their language; from then on their alerts
   arrive in that chat. Until they do, the delivery log shows `suppressed: not_linked`.

A group works too: add the bot to the group, then send `/start <code>` in the group.

## What people see

A photo of the camera (when the edge uploaded one within 20 seconds), the alert in their language,
and three buttons: **Correct**, **False alarm**, **I'm on it**. A tap records feedback on the event
and acknowledges the alert, which stops escalation; the buttons are replaced by the answer. Taps
are accepted only from the chat the alert was sent to.
