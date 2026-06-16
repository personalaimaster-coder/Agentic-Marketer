"""Pydantic schemas for structured agent output.

Using `output_schema` on the reasoning agents removes the brittle
"strip markdown fences + regex the JSON" parsing the n8n build needed.
Gemini returns validated JSON directly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RankedTopic(BaseModel):
    rank: int = Field(description="1 = strongest topic")
    title: str
    why: str = Field(description="one sentence on why this resonates with our audience")
    angle: str = Field(description="one-sentence content angle for the brand")
    source_title: str = ""


class RankedTopics(BaseModel):
    topics: list[RankedTopic]


class Brief(BaseModel):
    topic_title: str
    platform: str = Field(description="instagram | pinterest | x")
    brief_type: str = Field(description="educational | inspirational | utility")
    hook: str
    angle: str
    key_points: list[str]
    visual_concept: str
    eyebrow_label: str = Field(description="short 2-word label, e.g. 'Style Tip'")
    headline: str = Field(description="bold 4-8 word headline to render on the image")
    cta: str


class Briefs(BaseModel):
    briefs: list[Brief]


class Caption(BaseModel):
    platform: str
    headline: str
    primary: str = Field(description="the main caption / tweet / pin description")
    secondary: str = Field(default="", description="optional alternate variant")
    hashtags: str = Field(default="", description="space-separated hashtags if applicable")


class Captions(BaseModel):
    captions: list[Caption]


class ImagePrompt(BaseModel):
    headline: str
    prompt: str = Field(description="full text-to-image prompt incl. how to render the headline")


class ImagePrompts(BaseModel):
    prompts: list[ImagePrompt]


# ------------------------------------------------------------
# Phase 2 — Research dossier (the Research Agent's output)
# ------------------------------------------------------------
class TrendSignal(BaseModel):
    trend: str = Field(description="the trend / theme observed in the sources")
    why_now: str = Field(description="one sentence on why this is timely")
    audience_value: str = Field(
        description="the underlying audience value this taps (e.g. 'intentional living')"
    )


class ResearchDossier(BaseModel):
    """Structured research the whole department reads, not just a topic list."""

    summary: str = Field(description="2-3 sentence read on what the audience cares about right now")
    trends: list[TrendSignal] = Field(default_factory=list)
    audience_values: list[str] = Field(
        default_factory=list, description="durable values to lean into"
    )
    do_signals: list[str] = Field(
        default_factory=list, description="content angles that will resonate"
    )
    avoid_signals: list[str] = Field(
        default_factory=list, description="angles to avoid (off-brand / fatigued / risky)"
    )
    topics: list[RankedTopic] = Field(
        default_factory=list, description="the ranked topics to actually produce content for"
    )


# ------------------------------------------------------------
# Phase 2 — Campaign plan (the Campaign Strategist's output)
# ------------------------------------------------------------
class Campaign(BaseModel):
    theme: str = Field(description="short campaign theme name")
    big_idea: str = Field(description="the single unifying idea for today's posts")
    narrative: str = Field(description="how the posts connect into one arc")
    platforms: list[str] = Field(default_factory=list)
    hashtag_strategy: str = Field(
        default="", description="rotation guidance so we don't repeat the same tags daily"
    )
    cadence_notes: str = Field(default="", description="spacing/timing guidance to avoid spam flags")
    anti_spam_notes: str = Field(
        default="", description="what to vary so the batch doesn't look automated/spammy"
    )


# ------------------------------------------------------------
# Phase 2 — Critic + guardrail + monitor contracts
# ------------------------------------------------------------
class CritiqueResult(BaseModel):
    """The quality_critic's judgment. The critic emits this as text and calls
    exit_loop when it passes (an output_schema cannot co-exist with tools)."""

    score: int = Field(description="1-5, where 5 is publish-ready")
    passes: bool = Field(description="true when score >= the pass threshold")
    feedback: str = Field(description="specific, actionable fixes for the next iteration")


class GuardrailResult(BaseModel):
    ok: bool = Field(description="true if the post is safe to surface for approval as-is")
    severity: str = Field(description="ok | warn | block")
    violations: list[str] = Field(default_factory=list)


class MonitorReport(BaseModel):
    checked: int = 0
    published: int = 0
    failed: int = 0
    retried: int = 0
    reported: int = 0
    details: list[str] = Field(default_factory=list)


class LearnedRule(BaseModel):
    role: str = Field(description="topic | brief | caption | image")
    rule: str = Field(description="short, specific, imperative guideline")
    evidence: str = Field(description="what feedback pattern justifies this rule")


class ReflectionResult(BaseModel):
    summary: str = Field(description="1-2 sentence summary of the feedback patterns found")
    new_rules: list[LearnedRule] = Field(default_factory=list)
    retire_rules: list[str] = Field(
        default_factory=list,
        description="ids of existing rules that are now obsolete or contradicted",
    )
