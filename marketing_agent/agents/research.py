"""Research Agent — trends & values (Phase 2c upgrade of the topic strategist).

Reads the raw RSS/Reddit signals and emits a structured ResearchDossier the whole
department relies on: trends + the audience values behind them, do/avoid signals,
and the ranked topics to actually produce. This is richer than Phase 1's bare
topic list, so the campaign strategist and content team reason from real context.
"""

from __future__ import annotations

from google.adk.agents import Agent

from .. import config, prompts, schemas

Rules = dict[str, list[str]]


def make_research_agent(rules: Rules | None = None) -> Agent:
    rules = rules or {}
    return Agent(
        name="research_lead",
        model=config.MODEL_SMART,
        description="Synthesizes raw trend signals into a research dossier for the team.",
        instruction=(
            prompts.build_instruction("research", rules.get("topic"))
            + f"\n\nReturn exactly {config.TOPICS_PER_DAY} ranked topics inside the dossier.\n\n"
            "RAW SOURCES:\n{raw_sources?}"
        ),
        output_schema=schemas.ResearchDossier,
        output_key="research_dossier",
    )
