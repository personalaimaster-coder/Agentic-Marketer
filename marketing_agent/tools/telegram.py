"""Telegram — the mobile approval interface.

Kept from the old build: it's the best "tap-to-approve from your phone" primitive
and is just a few HTTPS calls, not a heavyweight system. Approve / Reject /
Regen Text / Regen Visual buttons map to callback_data of the form "action:post_id".
"""

from __future__ import annotations

import httpx

from .. import config


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def send_approval_card(post_id: str, image_url: str, caption: str) -> str | None:
    """Send the post image with inline approval buttons. Returns the message_id."""
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve:{post_id}"},
                {"text": "✍️ Regen Text", "callback_data": f"regen_text:{post_id}"},
            ],
            [
                {"text": "🖼 Regen Visual", "callback_data": f"regen_visual:{post_id}"},
                {"text": "❌ Reject", "callback_data": f"reject:{post_id}"},
            ],
        ]
    }
    resp = httpx.post(
        _api("sendPhoto"),
        json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "photo": image_url,
            "caption": caption,
            "parse_mode": "Markdown",
            "reply_markup": keyboard,
        },
        timeout=30,
    )
    data = resp.json()
    return str(data.get("result", {}).get("message_id")) if data.get("ok") else None


def answer_callback(callback_query_id: str, text: str) -> None:
    httpx.post(
        _api("answerCallbackQuery"),
        json={"callback_query_id": callback_query_id, "text": text},
        timeout=15,
    )


def edit_caption(chat_id, message_id, caption: str) -> None:
    httpx.post(
        _api("editMessageCaption"),
        json={
            "chat_id": chat_id,
            "message_id": message_id,
            "caption": caption,
            "parse_mode": "Markdown",
        },
        timeout=15,
    )


def send_message(text: str, reply_to_message_id=None) -> None:
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    httpx.post(_api("sendMessage"), json=payload, timeout=15)
