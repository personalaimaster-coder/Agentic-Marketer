"""Quality critic — the evaluator half of the evaluator-optimizer loop.

It reviews a single drafted post (caption + image prompt) against the brief and
brand voice, scores it 1-5, and gives actionable feedback for the next pass. When
the post is good enough it calls the built-in `exit_loop` tool to stop the loop
early.

NOTE: an ADK agent that uses tools cannot also declare an `output_schema`, so the
critic emits plain-text feedback (read by the copywriter on the next iteration via
{critique_feedback?}) rather than structured JSON.
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import exit_loop

from .. import config, prompts

Rules = dict[str, list[str]]


def make_quality_critic(rules: Rules | None = None) -> Agent:
    rules = rules or {}
    return Agent(
        name="quality_critic",
        model=config.MODEL_SMART,
        description="Scores a drafted post and calls exit_loop when it is publish-ready.",
        instruction=(
            prompts.build_instruction("critic", rules.get("caption"))
            + "\n\n"
            + prompts.anti_spam_block()
            + "\n\nReview the draft below.\n\n"
            "BRIEF:\n{brief?}\n\n"
            "DRAFT CAPTION:\n{draft_caption?}\n\n"
            "IMAGE PROMPT:\n{image_prompt?}"
        ),
        tools=[exit_loop],
        output_key="critique_feedback",
    )
