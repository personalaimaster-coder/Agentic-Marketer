"""JIT publisher (replaces n8n Workflow 3).

Runs hourly via Cloud Scheduler. Pulls posts whose scheduled slot has arrived
and pushes them to Buffer with shareNow, then notifies via Telegram.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import config
from .tools import firestore_store, publisher, telegram


def _final_caption(post: dict) -> str:
    caption = post.get("caption_primary", "") or ""
    hashtags = post.get("hashtags", "") or ""
    if post.get("platform") == "instagram" and hashtags:
        return f"{caption}\n\n{hashtags}"
    return caption


def _handle_failure(post: dict, error: str, now: datetime) -> str:
    """On a failed publish, schedule one durable retry; else mark failed + report.

    Returns the resulting status ("retry_scheduled" or "failed").
    """
    attempt = int(post.get("retry_count", 0))
    if attempt < config.MAX_PUBLISH_RETRIES:
        retry_at = (now + timedelta(minutes=config.RETRY_DELAY_MINUTES)).isoformat()
        firestore_store.schedule_retry(post["id"], retry_at, attempt + 1)
        firestore_store.log_outcome(
            post["id"], post["platform"], "failed_will_retry", error
        )
        telegram.send_message(
            f"⚠️ *Publish failed* for `{post['id']}` on {post['platform']}: {error}\n"
            f"Retrying once in {config.RETRY_DELAY_MINUTES} min."
        )
        return "retry_scheduled"

    firestore_store.update_post(post["id"], {"status": "failed", "last_error": error})
    firestore_store.log_outcome(post["id"], post["platform"], "failed", error)
    telegram.send_message(
        f"🚨 *Publish failed* for `{post['id']}` on {post['platform']} "
        f"(no retries left): {error}"
    )
    return "failed"


def run_due_publishes() -> dict:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    due = firestore_store.due_posts(now_iso, limit=5)
    if not due:
        return {"ok": True, "published": 0}

    published = 0
    retried = 0
    for post in due:
        result = publisher.publish(
            platform=post["platform"],
            caption=_final_caption(post),
            image_url=post.get("composited_image_url") or post.get("raw_image_url", ""),
        )
        if result["success"]:
            firestore_store.update_post(
                post["id"],
                {
                    "status": "published",
                    "published_at": now_iso,
                    "buffer_post_id": result["buffer_post_id"],
                },
            )
            firestore_store.log_outcome(post["id"], post["platform"], "published")
            telegram.send_message(
                f"🚀 *Published* to {post['platform']} — Buffer id `{result['buffer_post_id']}`"
            )
            published += 1
        else:
            status = _handle_failure(post, result["error"], now)
            if status == "retry_scheduled":
                retried += 1

    return {"ok": True, "published": published, "retry_scheduled": retried}
