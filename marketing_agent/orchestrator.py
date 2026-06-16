"""Department-head orchestrator (Phase 2).

Coordinates the marketing department end to end:

    Stage 1 (sequential, one session):
        research_lead -> campaign_strategist -> content_strategist
        => a ResearchDossier, a Campaign, and a list of platform-native Briefs.

    Stage 2 (parallel fan-out, one isolated session per post):
        content_team LoopAgent (copywriter -> art_director -> quality_critic)
        => each post refined until the critic says it is publish-ready.

    Stage 2.5 (anti-spam guardrail gate):
        deterministic + LLM checks; one regeneration attempt; otherwise flagged.

    Stage 3 (deterministic I/O, reused from Phase 1):
        branded image -> Firestore (with campaign_id) -> Telegram approval card.

This replaces the linear Phase 1 pipeline (pipeline.py), which remains as the
simple baseline selectable via config.PIPELINE_MODE.
"""

from __future__ import annotations

import json
import logging

from google.adk.agents import SequentialAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from . import config, guardrails, prompts
from .agents import campaign as campaign_agents
from .agents import content_team, research
from .schemas import Briefs
from .tools import firestore_store, imagen, llm, telegram

log = logging.getLogger("orchestrator")

APP_NAME = "marketing_dept"
USER_ID = "system"


# ------------------------------------------------------------
# Stage 1 — research -> campaign -> briefs (one sequential session)
# ------------------------------------------------------------
async def _run_stage1(raw_sources: list[dict], rules: dict) -> dict:
    stage1 = SequentialAgent(
        name="strategy_pipeline",
        description="Research the trends, design the campaign, write the briefs.",
        sub_agents=[
            research.make_research_agent(rules),
            campaign_agents.make_campaign_strategist(rules),
            campaign_agents.make_brief_agent(rules),
        ],
    )
    runner = InMemoryRunner(agent=stage1, app_name=APP_NAME)
    session = await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, state={"raw_sources": raw_sources}
    )
    message = types.Content(
        role="user",
        parts=[types.Part(text="Plan today's campaign and write the briefs.")],
    )
    async for _ in runner.run_async(
        user_id=USER_ID, session_id=session.id, new_message=message
    ):
        pass
    final = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    return dict(final.state)


def _coerce(value, key=None):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {} if key is None else []
    if key is not None:
        if isinstance(value, dict):
            return value.get(key, [])
        if isinstance(value, list):
            return value
        return []
    return value or {}


def _extract_briefs(state: dict) -> list[dict]:
    raw = _coerce(state.get("briefs"), "briefs")
    try:
        return [b.model_dump() for b in Briefs.model_validate({"briefs": raw}).briefs]
    except Exception:
        log.exception("brief validation failed")
        return []


# ------------------------------------------------------------
# Stage 2.5 — anti-spam guardrail gate
# ------------------------------------------------------------
def _regen_caption(post: dict, rules: dict) -> str:
    instruction = prompts.build_instruction("caption", rules.get("caption"))
    prompt = (
        f"{instruction}\n\n{prompts.anti_spam_block()}\n\n"
        "Your previous caption was flagged by anti-spam checks. Rewrite it to be "
        "genuinely useful, varied, and free of spammy phrasing.\n"
        f"Platform: {post.get('platform')}\nHeadline: {post.get('headline')}\n"
        "Return only the new caption text."
    )
    try:
        return llm.generate_text(prompt, model=config.MODEL_SMART).strip()
    except Exception:
        log.exception("guardrail regeneration failed")
        return post.get("caption_primary", "")


def _apply_guardrails(posts: list[dict], rules: dict) -> list[dict]:
    recent = firestore_store.recent_caption_texts()
    for post in posts:
        verdict = guardrails.evaluate(post, recent)
        if not verdict.ok and verdict.severity == "block":
            # one regeneration attempt, then re-check
            post["caption_primary"] = _regen_caption(post, rules)
            verdict = guardrails.evaluate(post, recent)
        post["guardrail_ok"] = verdict.ok
        post["guardrail_severity"] = verdict.severity
        post["guardrail_violations"] = verdict.violations
    return posts


# ------------------------------------------------------------
# Stage 3 — per-post I/O (image -> Firestore -> Telegram)
# ------------------------------------------------------------
def _telegram_caption(post: dict) -> str:
    emoji = {"instagram": "📸", "pinterest": "📌", "x": "🐦"}.get(post["platform"], "📱")
    preview = (post.get("caption_primary") or "")[:200]
    warn = ""
    if not post.get("guardrail_ok", True):
        issues = "; ".join(post.get("guardrail_violations", [])) or "review tone"
        warn = f"\n\n⚠️ *Guardrail flag:* {issues}"
    return (
        f"{emoji} *New {post['platform'].upper()} post*\n\n"
        f"*{post['headline']}*\n\n"
        f"_{preview}_{warn}"
    )


def _process_post(post: dict, campaign_id: str | None) -> None:
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
    if campaign_id:
        post["campaign_id"] = campaign_id

    post_id = firestore_store.save_post(post)
    if image_url:
        msg_id = telegram.send_approval_card(post_id, image_url, _telegram_caption(post))
        if msg_id:
            firestore_store.update_post(post_id, {"telegram_message_id": msg_id})


# ------------------------------------------------------------
# Entry point
# ------------------------------------------------------------
async def run_department_pipeline() -> dict:
    """Daily department run. Returns a small summary for the scheduler."""
    from .sources import get_source_provider

    raw_sources = get_source_provider().fetch()
    if not raw_sources:
        return {"ok": False, "reason": "no sources fetched"}

    rules = firestore_store.all_active_rules()

    state = await _run_stage1(raw_sources, rules)
    briefs = _extract_briefs(state)
    if not briefs:
        return {"ok": False, "reason": "no briefs produced"}

    campaign = _coerce(state.get("campaign"))
    campaign_id = firestore_store.save_campaign(campaign) if campaign else None

    posts = await content_team.refine_all(briefs, rules)
    if not posts:
        return {"ok": False, "reason": "no posts refined"}

    posts = _apply_guardrails(posts, rules)

    for post in posts:
        _process_post(post, campaign_id)

    flagged = sum(1 for p in posts if not p.get("guardrail_ok", True))
    return {
        "ok": True,
        "posts_created": len(posts),
        "briefs": len(briefs),
        "campaign_id": campaign_id,
        "guardrail_flagged": flagged,
    }
