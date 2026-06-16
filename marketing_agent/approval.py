"""Telegram approval handling (replaces n8n Workflow 2).

Parses incoming Telegram webhook updates and routes button taps:
  approve       -> schedule into next open publish slot
  reject        -> mark rejected, ask for a one-word reason
  regen_text    -> rewrite the caption with Gemini, refresh the card
  regen_visual  -> regenerate the branded image with Nano Banana
  (text reply)  -> log the rejection reason (Phase 3 training signal)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config, prompts
from .tools import firestore_store, imagen, llm, telegram


def next_publish_slot(now: datetime | None = None) -> datetime:
    tz = ZoneInfo(config.LOCAL_TZ)
    now = now or datetime.now(tz)
    for hour in config.PUBLISH_SLOTS:
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > now:
            return candidate
    # all slots used today -> first slot tomorrow
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=config.PUBLISH_SLOTS[0], minute=0, second=0, microsecond=0)


def handle_update(update: dict) -> dict:
    """Main webhook entry. Returns a small status dict (for logging)."""
    if "callback_query" in update:
        return _handle_button(update["callback_query"])
    msg = update.get("message") or {}
    if msg.get("text") and msg.get("reply_to_message"):
        return _handle_rejection_reason(msg)
    return {"action": "ignore"}


def _handle_button(cb: dict) -> dict:
    action, _, post_id = (cb.get("data") or "").partition(":")
    cb_id = cb.get("id")
    chat_id = cb.get("message", {}).get("chat", {}).get("id")
    message_id = cb.get("message", {}).get("message_id")

    if action == "approve":
        return _approve(post_id, cb_id, chat_id, message_id)
    if action == "reject":
        return _reject(post_id, cb_id, chat_id, message_id)
    if action == "regen_text":
        return _regen_text(post_id, cb_id, chat_id, message_id)
    if action == "regen_visual":
        return _regen_visual(post_id, cb_id, chat_id, message_id)
    return {"action": "unknown", "raw": action}


def _approve(post_id, cb_id, chat_id, message_id) -> dict:
    slot = next_publish_slot()
    firestore_store.update_post(
        post_id, {"status": "pending_publish", "publish_timestamp": slot.isoformat()}
    )
    telegram.answer_callback(cb_id, "✅ Approved! Scheduled for publishing.")
    telegram.edit_caption(
        chat_id, message_id,
        f"✅ *APPROVED* — scheduled for {slot.strftime('%d %b %H:%M')}",
    )
    return {"action": "approve", "post_id": post_id, "slot": slot.isoformat()}


def _reject(post_id, cb_id, chat_id, message_id) -> dict:
    firestore_store.update_post(post_id, {"status": "rejected"})
    telegram.answer_callback(cb_id, "❌ Rejected. Reply with a reason.")
    telegram.send_message(
        "Understood. What went wrong? Reply with one word:\n"
        "• `length` • `tone` • `styling` • `irrelevance`",
        reply_to_message_id=message_id,
    )
    # stash which post the next text reply belongs to
    firestore_store.update_post(post_id, {"awaiting_reason_msg_id": str(message_id)})
    return {"action": "reject", "post_id": post_id}


def _regen_text(post_id, cb_id, chat_id, message_id) -> dict:
    telegram.answer_callback(cb_id, "✍️ Regenerating caption…")
    post = firestore_store.get_post(post_id)
    if not post:
        return {"action": "regen_text", "error": "post not found"}

    rules = firestore_store.get_active_rules("caption")
    instruction = prompts.build_instruction("caption", rules)
    new_caption = llm.generate_text(
        f"{instruction}\n\nThis is a REGENERATION — use a fresh angle.\n"
        f"Platform: {post['platform']}\nHeadline: {post['headline']}\n"
        f"Topic: {post.get('topic_title', '')}\n"
        "Return only the new caption text."
    )
    firestore_store.update_post(
        post_id,
        {
            "caption_primary": new_caption,
            "status": "pending_approval",
            "regen_text_count": post.get("regen_text_count", 0) + 1,
        },
    )
    telegram.edit_caption(chat_id, message_id, f"✍️ *Updated caption:*\n\n_{new_caption[:300]}_")
    return {"action": "regen_text", "post_id": post_id}


def _regen_visual(post_id, cb_id, chat_id, message_id) -> dict:
    telegram.answer_callback(cb_id, "🖼 Regenerating visual…")
    post = firestore_store.get_post(post_id)
    if not post:
        return {"action": "regen_visual", "error": "post not found"}
    try:
        image_url = imagen.generate_card(
            prompt=post.get("image_prompt", ""),
            headline=post.get("headline", ""),
            eyebrow=post.get("eyebrow_label", ""),
            platform=post.get("platform", "instagram"),
        )
    except Exception as exc:
        return {"action": "regen_visual", "error": str(exc)}

    firestore_store.update_post(
        post_id,
        {
            "composited_image_url": image_url,
            "status": "pending_approval",
            "regen_visual_count": post.get("regen_visual_count", 0) + 1,
        },
    )
    telegram.send_message(f"🖼 New visual ready for `{post_id}`. Re-sending card…")
    telegram.send_approval_card(post_id, image_url, f"*{post.get('headline','')}* (regenerated visual)")
    return {"action": "regen_visual", "post_id": post_id}


def _handle_rejection_reason(msg: dict) -> dict:
    reason = msg["text"].strip().lower()
    reply_to = msg["reply_to_message"]["message_id"]
    # find the post awaiting a reason for this thread
    post = _find_post_awaiting(str(reply_to))
    post_id = post["id"] if post else "unknown"
    firestore_store.log_rejection(post_id, reason)
    if post:
        firestore_store.update_post(post_id, {"awaiting_reason_msg_id": None})
    telegram.send_message(f"📝 Logged: *{reason}*. This trains future content.")
    return {"action": "rejection_reason", "post_id": post_id, "reason": reason}


def _find_post_awaiting(message_id: str) -> dict | None:
    from google.cloud import firestore as _fs
    q = (
        firestore_store.client()
        .collection(config.COLLECTION_POSTS)
        .where(filter=_fs.FieldFilter("awaiting_reason_msg_id", "==", message_id))
        .limit(1)
    )
    for snap in q.stream():
        data = snap.to_dict()
        data["id"] = snap.id
        return data
    return None
