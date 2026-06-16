"""Performance Monitor (Phase 2a, publish-first).

Two jobs, both driven by Cloud Scheduler:

  run_due_retries()  — the durable retry mechanism. Cloud Run scales to zero, so
                       we never sleep in-process. A failed publish persists a
                       `retry_at` timestamp (see publish_runner); a ~5-min poll
                       calls this, which re-attempts ONCE. If it still fails, it
                       marks the post failed and reports to you on Telegram.

  run_monitor()      — a periodic outcome digest. For now it summarizes publish
                       success/failure (the data the reflector learns from). Real
                       engagement metrics (likes/saves/reach) slot in here later.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .. import config
from ..publish_runner import _final_caption
from ..schemas import MonitorReport
from ..tools import firestore_store, publisher, telegram

log = logging.getLogger("monitor")


def _image_url(post: dict) -> str:
    return post.get("composited_image_url") or post.get("raw_image_url", "")


def run_due_retries() -> dict:
    """Re-attempt publishes whose 15-min retry window has arrived (once)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    due = firestore_store.due_retries(now_iso)
    report = MonitorReport()
    if not due:
        return report.model_dump()

    for post in due:
        report.checked += 1
        report.retried += 1
        result = publisher.publish(
            platform=post["platform"],
            caption=_final_caption(post),
            image_url=_image_url(post),
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
            firestore_store.log_outcome(post["id"], post["platform"], "retry_published")
            telegram.send_message(
                f"✅ *Retry succeeded* — {post['platform']} post `{post['id']}` is live."
            )
            report.published += 1
        else:
            firestore_store.update_post(
                post["id"], {"status": "failed", "last_error": result["error"]}
            )
            firestore_store.log_outcome(
                post["id"], post["platform"], "failed", result["error"]
            )
            telegram.send_message(
                f"🚨 *Publish failed twice* — {post['platform']} post `{post['id']}` "
                f"could not be published.\nReason: {result['error']}\n"
                "No more automatic retries; please check manually."
            )
            report.failed += 1
            report.reported += 1

    return report.model_dump()


def run_monitor() -> dict:
    """Summarize recent publish outcomes and send a short digest to Telegram."""
    outcomes = firestore_store.recent_outcomes(limit=100)
    report = MonitorReport(checked=len(outcomes))
    for o in outcomes:
        status = o.get("status", "")
        if status in ("published", "retry_published"):
            report.published += 1
        elif status == "failed":
            report.failed += 1
        elif status == "failed_will_retry":
            report.retried += 1

    if outcomes:
        telegram.send_message(
            "📊 *Performance digest*\n"
            f"Published: {report.published}  ·  Retried: {report.retried}  ·  "
            f"Failed: {report.failed}\n"
            f"(last {report.checked} publish events)"
        )
    return report.model_dump()
