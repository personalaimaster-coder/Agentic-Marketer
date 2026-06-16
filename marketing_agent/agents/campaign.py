"""Campaign Strategist + Brief writer (Phase 2b).

The strategist reads the research dossier and designs ONE coherent campaign for
the day (a big idea + narrative + platform-aware, anti-spam-aware guidance). The
brief writer then turns that campaign into one platform-native brief per topic per
platform, factoring in regional context and platform fit.
"""

from __future__ import annotations

from google.adk.agents import Agent

from .. import config, prompts, schemas

Rules = dict[str, list[str]]


def make_campaign_strategist(rules: Rules | None = None) -> Agent:
    rules = rules or {}
    platforms = ", ".join(config.PLATFORMS)
    return Agent(
        name="campaign_strategist",
        model=config.MODEL_SMART,
        description="Designs the day's campaign: big idea, narrative, platform + anti-spam strategy.",
        instruction=(
            prompts.build_instruction("campaign", rules.get("brief"))
            + f"\n\nDesign one campaign covering these platforms: {platforms}.\n\n"
            + prompts.platform_fit_block()
            + "\n\n"
            + prompts.anti_spam_block()
            + "\n\n"
            + prompts.regional_block()
            + "\n\nRESEARCH DOSSIER:\n{research_dossier?}"
        ),
        output_schema=schemas.Campaign,
        output_key="campaign",
    )


def make_brief_agent(rules: Rules | None = None) -> Agent:
    rules = rules or {}
    platforms = ", ".join(config.PLATFORMS)
    return Agent(
        name="content_strategist",
        model=config.MODEL_SMART,
        description="Turns the campaign + dossier into platform-native briefs.",
        instruction=(
            prompts.build_instruction("brief", rules.get("brief"))
            + f"\n\nFor every topic in the dossier, produce one brief per platform "
            f"({platforms}). So total briefs = topics x platforms. Each brief must "
            "advance the campaign's big idea while staying platform-native.\n\n"
            + prompts.platform_fit_block()
            + "\n\n"
            + prompts.regional_block()
            + "\n\nCAMPAIGN:\n{campaign?}\n\nRESEARCH DOSSIER:\n{research_dossier?}"
        ),
        output_schema=schemas.Briefs,
        output_key="briefs",
    )
