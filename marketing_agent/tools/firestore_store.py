"""Firestore persistence — the single datastore for the whole system.

Replaces Supabase. Collections:
  posts            — the approval/publish queue
  rejections       — logged rejection reasons (fuel for Phase 3 learning)
  learned_rules    — Phase 3 output, injected back into agent prompts
  prompt_versions  — history of effective prompts/context per role
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from .. import config

_client: firestore.Client | None = None


def client() -> firestore.Client:
    global _client
    if _client is None:
        _client = firestore.Client(project=config.GOOGLE_CLOUD_PROJECT or None)
    return _client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------
# Posts
# ------------------------------------------------------------
def save_post(post: dict) -> str:
    """Create a post draft. Returns the generated document id."""
    doc = client().collection(config.COLLECTION_POSTS).document()
    payload = {
        **post,
        "status": post.get("status", "pending_approval"),
        "regen_text_count": 0,
        "regen_visual_count": 0,
        "created_at": _now(),
        "updated_at": _now(),
    }
    doc.set(payload)
    return doc.id


def get_post(post_id: str) -> dict | None:
    snap = client().collection(config.COLLECTION_POSTS).document(post_id).get()
    if not snap.exists:
        return None
    data = snap.to_dict()
    data["id"] = snap.id
    return data


def update_post(post_id: str, fields: dict[str, Any]) -> None:
    fields = {**fields, "updated_at": _now()}
    client().collection(config.COLLECTION_POSTS).document(post_id).update(fields)


def due_posts(now_iso: str, limit: int = 5) -> list[dict]:
    """Posts that are approved and whose publish_timestamp has arrived."""
    q = (
        client()
        .collection(config.COLLECTION_POSTS)
        .where(filter=firestore.FieldFilter("status", "==", "pending_publish"))
        .where(filter=firestore.FieldFilter("publish_timestamp", "<=", now_iso))
        .order_by("publish_timestamp")
        .limit(limit)
    )
    out = []
    for snap in q.stream():
        data = snap.to_dict()
        data["id"] = snap.id
        out.append(data)
    return out


def recent_caption_texts(limit: int | None = None) -> list[str]:
    """Recent caption_primary strings, for near-duplicate (anti-spam) detection."""
    limit = limit or config.DEDUP_LOOKBACK
    q = (
        client()
        .collection(config.COLLECTION_POSTS)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [
        (snap.to_dict().get("caption_primary") or "").strip()
        for snap in q.stream()
        if snap.to_dict().get("caption_primary")
    ]


# ------------------------------------------------------------
# Durable publish retry (Phase 2 Performance Monitor)
# ------------------------------------------------------------
def schedule_retry(post_id: str, retry_at_iso: str, attempt: int) -> None:
    """Mark a failed publish for a single durable retry (no in-process sleep)."""
    client().collection(config.COLLECTION_POSTS).document(post_id).update(
        {
            "status": "retry_scheduled",
            "retry_at": retry_at_iso,
            "retry_count": attempt,
            "updated_at": _now(),
        }
    )


def due_retries(now_iso: str, limit: int = 10) -> list[dict]:
    """Posts whose scheduled retry time has arrived."""
    q = (
        client()
        .collection(config.COLLECTION_POSTS)
        .where(filter=firestore.FieldFilter("status", "==", "retry_scheduled"))
        .where(filter=firestore.FieldFilter("retry_at", "<=", now_iso))
        .order_by("retry_at")
        .limit(limit)
    )
    out = []
    for snap in q.stream():
        data = snap.to_dict()
        data["id"] = snap.id
        out.append(data)
    return out


# ------------------------------------------------------------
# Publish outcomes (Phase 2 monitor signal -> Phase 3 reflector)
# ------------------------------------------------------------
def log_outcome(post_id: str, platform: str, status: str, detail: str = "") -> None:
    client().collection(config.COLLECTION_OUTCOMES).add(
        {
            "post_id": post_id,
            "platform": platform,
            "status": status,  # published | failed_will_retry | failed | retry_published
            "detail": detail,
            "created_at": _now(),
        }
    )


def recent_outcomes(limit: int = 100) -> list[dict]:
    q = (
        client()
        .collection(config.COLLECTION_OUTCOMES)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [snap.to_dict() for snap in q.stream()]


# ------------------------------------------------------------
# Campaigns (Phase 2b)
# ------------------------------------------------------------
def save_campaign(campaign: dict) -> str:
    doc = client().collection(config.COLLECTION_CAMPAIGNS).document()
    doc.set({**campaign, "created_at": _now()})
    return doc.id


# ------------------------------------------------------------
# Rejections (Phase 3 training signal)
# ------------------------------------------------------------
def log_rejection(post_id: str, reason: str) -> None:
    client().collection(config.COLLECTION_REJECTIONS).add(
        {"post_id": post_id, "reason": reason, "created_at": _now()}
    )


def recent_feedback(limit: int = 100) -> dict:
    """Aggregate recent rejections + regen counts for the reflector to analyze."""
    rejections = []
    rq = (
        client()
        .collection(config.COLLECTION_REJECTIONS)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    for snap in rq.stream():
        rejections.append(snap.to_dict())

    # Pull recently reviewed posts to compute regen/approval signal.
    posts = []
    pq = (
        client()
        .collection(config.COLLECTION_POSTS)
        .order_by("updated_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    for snap in pq.stream():
        d = snap.to_dict()
        posts.append(
            {
                "platform": d.get("platform"),
                "status": d.get("status"),
                "headline": d.get("headline"),
                "regen_text_count": d.get("regen_text_count", 0),
                "regen_visual_count": d.get("regen_visual_count", 0),
            }
        )
    return {"rejections": rejections, "posts": posts}


# ------------------------------------------------------------
# Learned rules (Phase 3 <-> prompt assembly)
# ------------------------------------------------------------
def get_active_rules(role: str) -> list[str]:
    """Return active rule strings for a given agent role."""
    q = (
        client()
        .collection(config.COLLECTION_RULES)
        .where(filter=firestore.FieldFilter("role", "==", role))
        .where(filter=firestore.FieldFilter("active", "==", True))
    )
    return [snap.to_dict().get("rule", "") for snap in q.stream()]


def all_active_rules() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    q = client().collection(config.COLLECTION_RULES).where(
        filter=firestore.FieldFilter("active", "==", True)
    )
    for snap in q.stream():
        d = snap.to_dict()
        out.setdefault(d.get("role", "misc"), []).append(d.get("rule", ""))
    return out


def add_rule(role: str, rule: str, evidence: str) -> str:
    doc = client().collection(config.COLLECTION_RULES).document()
    doc.set(
        {
            "role": role,
            "rule": rule,
            "evidence": evidence,
            "active": True,
            "created_at": _now(),
        }
    )
    return doc.id


def retire_rule(rule_id: str) -> None:
    client().collection(config.COLLECTION_RULES).document(rule_id).update(
        {"active": False, "retired_at": _now()}
    )


# ------------------------------------------------------------
# Prompt versions (audit trail of self-evolving context)
# ------------------------------------------------------------
def log_prompt_version(role: str, prompt_text: str, notes: str = "") -> None:
    client().collection(config.COLLECTION_PROMPTS).add(
        {"role": role, "prompt_text": prompt_text, "notes": notes, "created_at": _now()}
    )
