"""Phase 1 daily pipeline orchestrator.

Wires the ADK reasoning pipeline (rank -> brief -> caption -> art direction) to
the deterministic I/O tools (image generation, Firestore, Telegram). A thin
Python orchestrator runs the agents once, then does the per-post I/O.

Phase 2 (multi_agent.py) swaps the per-post loop for concurrent per-item agent
teams; this module stays the simple, reliable baseline.
"""

from __future__ import annotations

import json

from google.adk.runners import InMemoryRunner
from google.genai import types

from . import config, sub_agents
from .schemas import Briefs, Captions, ImagePrompts
from .tools import firestore_store, imagen, telegram

APP_NAME = "marketing_agent"
USER_ID = "system"


async def _run_pipeline_agent(raw_sources: list[dict], rules: dict) -> dict:
    """Run the content SequentialAgent once and return the final session state."""
    pipeline = sub_agents.build_content_pipeline(rules)
    runner = InMemoryRunner(agent=pipeline, app_name=APP_NAME)

    session = await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state={"raw_sources": raw_sources},
    )

    message = types.Content(
        role="user",
        parts=[types.Part(text="Generate today's content from the provided sources.")],
    )
    async for _ in runner.run_async(
        user_id=USER_ID, session_id=session.id, new_message=message
    ):
        pass  # we only care about the final accumulated state

    final = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    return dict(final.state)


def _zip_posts(state: dict) -> list[dict]:
    """Align briefs + captions + image prompts (the agents emit them in order)."""
    briefs = Briefs.model_validate({"briefs": _unwrap(state.get("briefs"), "briefs")}).briefs
    captions = Captions.model_validate({"captions": _unwrap(state.get("captions"), "captions")}).captions
    prompts = ImagePrompts.model_validate({"prompts": _unwrap(state.get("image_prompts"), "prompts")}).prompts

    posts = []
    for i, brief in enumerate(briefs):
        cap = captions[i] if i < len(captions) else None
        img = prompts[i] if i < len(prompts) else None
        if not cap or not img:
            continue
        posts.append(
            {
                "platform": brief.platform,
                "headline": brief.headline,
                "eyebrow_label": brief.eyebrow_label,
                "cta": brief.cta,
                "topic_title": brief.topic_title,
                "visual_concept": brief.visual_concept,
                "caption_primary": cap.primary,
                "caption_secondary": cap.secondary,
                "hashtags": cap.hashtags,
                "image_prompt": img.prompt,
            }
        )
    return posts


def _unwrap(value, key):
    """State values may be a JSON string (from output_schema), a dict, or a list."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    if isinstance(value, dict):
        return value.get(key, [])
    if isinstance(value, list):
        return value
    return []


def _telegram_caption(post: dict) -> str:
    emoji = {"instagram": "📸", "pinterest": "📌", "x": "🐦"}.get(post["platform"], "📱")
    preview = (post.get("caption_primary") or "")[:200]
    return (
        f"{emoji} *New {post['platform'].upper()} post*\n\n"
        f"*{post['headline']}*\n\n"
        f"_{preview}_"
    )


def _process_post(post: dict) -> None:
    """Generate the branded image, persist, and send the approval card."""
    try:
        image_url = imagen.generate_card(
            prompt=post["image_prompt"],
            headline=post["headline"],
            eyebrow=post.get("eyebrow_label", ""),
            platform=post["platform"],
        )
    except Exception as exc:
        image_url = ""
        post["image_error"] = str(exc)

    post["composited_image_url"] = image_url
    post_id = firestore_store.save_post(post)

    if image_url:
        msg_id = telegram.send_approval_card(post_id, image_url, _telegram_caption(post))
        if msg_id:
            firestore_store.update_post(post_id, {"telegram_message_id": msg_id})


async def run_daily_pipeline() -> dict:
    """Entry point for the daily cron. Returns a small run summary."""
    from .sources import get_source_provider

    raw_sources = get_source_provider().fetch()
    if not raw_sources:
        return {"ok": False, "reason": "no sources fetched"}

    rules = firestore_store.all_active_rules()
    state = await _run_pipeline_agent(raw_sources, rules)

    posts = _zip_posts(state)
    for post in posts:
        _process_post(post)

    return {"ok": True, "posts_created": len(posts)}
