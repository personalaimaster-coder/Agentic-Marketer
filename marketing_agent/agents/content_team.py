"""Per-post Content Team — the evaluator-optimizer loop, fanned out concurrently.

Each post gets its own LoopAgent that runs, in order, every iteration:
    1. copywriter   — writes/rewrites the caption (applying the critic's feedback)
    2. art_director — writes the image prompt
    3. quality_critic — scores both; calls exit_loop when publish-ready

The critic runs LAST so that when it exits the loop, a finished caption AND image
prompt already exist in state. The loop is bounded by CRITIC_MAX_ITERATIONS.

Fan-out: instead of one ADK ParallelAgent sharing a single session (which forces
careful unique-key juggling to avoid races), we run one isolated ADK session per
post concurrently via asyncio.gather. Each session is its own state namespace, so
branches are fully isolated and a single post failing never kills the others.
"""

from __future__ import annotations

import asyncio
import json
import logging

from google.adk.agents import Agent, LoopAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from .. import config, prompts, schemas

log = logging.getLogger("content_team")

Rules = dict[str, list[str]]

APP_NAME = "marketing_content"
USER_ID = "system"


# ------------------------------------------------------------
# The three loop members (single-post variants of the Phase 1 agents)
# ------------------------------------------------------------
def _make_copywriter(rules: Rules) -> Agent:
    return Agent(
        name="copywriter",
        model=config.MODEL_SMART,
        description="Writes one platform-specific caption for a single brief.",
        instruction=(
            prompts.build_instruction("caption", rules.get("caption"))
            + "\n\n"
            + prompts.anti_spam_block()
            + "\n\n"
            + prompts.regional_block()
            + "\n\nWrite ONE caption for the brief below. Echo the brief's platform and "
            "headline. If critique feedback is present, APPLY it to improve the caption.\n\n"
            "BRIEF:\n{brief?}\n\n"
            "CRITIQUE FEEDBACK (from the last pass, if any):\n{critique_feedback?}"
        ),
        output_schema=schemas.Caption,
        output_key="draft_caption",
    )


def _make_art_director(rules: Rules) -> Agent:
    return Agent(
        name="art_director",
        model=config.MODEL_FAST,
        description="Writes one image-generation prompt for a single brief.",
        instruction=(
            prompts.build_instruction("image", rules.get("image"))
            + "\n\n"
            + prompts.regional_block()
            + "\n\nWrite ONE image prompt for the brief below, echoing its headline.\n\n"
            "BRIEF:\n{brief?}"
        ),
        output_schema=schemas.ImagePrompt,
        output_key="image_prompt",
    )


def build_content_team(rules: Rules | None = None) -> LoopAgent:
    """Build a fresh per-post content-team LoopAgent (copywriter -> art -> critic)."""
    rules = rules or {}
    from .critic import make_quality_critic  # local import avoids a cycle

    return LoopAgent(
        name="content_team",
        description="Refines a single post until the critic deems it publish-ready.",
        sub_agents=[
            _make_copywriter(rules),
            _make_art_director(rules),
            make_quality_critic(rules),
        ],
        max_iterations=config.CRITIC_MAX_ITERATIONS,
    )


# ------------------------------------------------------------
# Running the loop for one post (isolated session)
# ------------------------------------------------------------
def _coerce(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value or {}


async def _refine_one(brief: dict, rules: Rules) -> dict | None:
    """Run the content-team loop for a single brief; return a merged post dict."""
    # A fresh agent tree per post avoids ADK's single-parent constraint on reuse.
    team = build_content_team(rules)
    runner = InMemoryRunner(agent=team, app_name=APP_NAME)

    session = await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state={"brief": brief},
    )
    message = types.Content(
        role="user",
        parts=[types.Part(text="Refine this post until it is publish-ready.")],
    )
    try:
        async for _ in runner.run_async(
            user_id=USER_ID, session_id=session.id, new_message=message
        ):
            pass
    except Exception:
        log.exception("content team failed for brief: %s", brief.get("headline"))
        return None

    final = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    state = dict(final.state)

    cap = _coerce(state.get("draft_caption"))
    img = _coerce(state.get("image_prompt"))
    if not cap or not img:
        return None

    return {
        "platform": brief.get("platform"),
        "headline": brief.get("headline"),
        "eyebrow_label": brief.get("eyebrow_label", ""),
        "cta": brief.get("cta", ""),
        "topic_title": brief.get("topic_title", ""),
        "visual_concept": brief.get("visual_concept", ""),
        "caption_primary": cap.get("primary", ""),
        "caption_secondary": cap.get("secondary", ""),
        "hashtags": cap.get("hashtags", ""),
        "image_prompt": img.get("prompt", ""),
        "critique_feedback": (state.get("critique_feedback") or "")[:500],
    }


async def refine_all(briefs: list[dict], rules: Rules | None = None) -> list[dict]:
    """Fan out: refine every brief concurrently, gather the finished posts."""
    rules = rules or {}
    results = await asyncio.gather(
        *(_refine_one(brief, rules) for brief in briefs)
    )
    return [post for post in results if post]
