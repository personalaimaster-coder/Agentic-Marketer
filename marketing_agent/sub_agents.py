"""Agent factories for the content pipeline.

Each reasoning step is an `LlmAgent` that:
  - gets its instruction from base prompt + Phase 3 learned rules,
  - reads upstream results from session state via {key?} templating,
  - writes validated structured output to a state key via output_key.

Factories take `rules` (role -> list[str]) so the same code produces a
"smarter" pipeline as the reflector accumulates guidelines. This is the seam
where self-learning meets execution.
"""

from __future__ import annotations

from google.adk.agents import Agent, SequentialAgent

from . import config, prompts, schemas

Rules = dict[str, list[str]]


def make_topic_agent(rules: Rules) -> Agent:
    return Agent(
        name="topic_strategist",
        model=config.MODEL_FAST,
        description="Ranks the strongest content topics from raw Reddit/RSS signals.",
        instruction=(
            prompts.build_instruction("topic", rules.get("topic"))
            + f"\n\nReturn exactly {config.TOPICS_PER_DAY} topics.\n\n"
            "RAW SOURCES:\n{raw_sources?}"
        ),
        output_schema=schemas.RankedTopics,
        output_key="ranked_topics",
    )


def make_brief_agent(rules: Rules) -> Agent:
    platforms = ", ".join(config.PLATFORMS)
    return Agent(
        name="content_strategist",
        model=config.MODEL_SMART,
        description="Turns ranked topics into platform-native briefs.",
        instruction=(
            prompts.build_instruction("brief", rules.get("brief"))
            + f"\n\nFor every topic, produce one brief per platform ({platforms}). "
            "So total briefs = topics x platforms.\n\n"
            "RANKED TOPICS:\n{ranked_topics?}"
        ),
        output_schema=schemas.Briefs,
        output_key="briefs",
    )


def make_caption_agent(rules: Rules) -> Agent:
    return Agent(
        name="copywriter",
        model=config.MODEL_SMART,
        description="Writes platform-specific captions from briefs.",
        instruction=(
            prompts.build_instruction("caption", rules.get("caption"))
            + "\n\nReturn one caption object per brief, in the same order. "
            "Echo each brief's platform and headline.\n\n"
            "BRIEFS:\n{briefs?}"
        ),
        output_schema=schemas.Captions,
        output_key="captions",
    )


def make_image_prompt_agent(rules: Rules) -> Agent:
    return Agent(
        name="art_director",
        model=config.MODEL_FAST,
        description="Writes image-generation prompts (with the headline to render) per brief.",
        instruction=(
            prompts.build_instruction("image", rules.get("image"))
            + "\n\nReturn one prompt object per brief, in the same order, "
            "echoing each brief's headline.\n\n"
            "BRIEFS:\n{briefs?}"
        ),
        output_schema=schemas.ImagePrompts,
        output_key="image_prompts",
    )


def build_content_pipeline(rules: Rules | None = None) -> SequentialAgent:
    """The Phase 1 deterministic content pipeline: rank -> brief -> caption + art direction."""
    rules = rules or {}
    return SequentialAgent(
        name="content_pipeline",
        description="Daily content pipeline: rank topics, write briefs, captions and image prompts.",
        sub_agents=[
            make_topic_agent(rules),
            make_brief_agent(rules),
            make_caption_agent(rules),
            make_image_prompt_agent(rules),
        ],
    )
