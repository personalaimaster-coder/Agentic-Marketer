"""Anti-spam guardrail layer (Phase 2b).

A two-stage gate that runs on each refined post BEFORE it reaches you for approval:

  1. Deterministic checks (fast, free): spam-trigger phrases, hashtag count vs
     platform limits, link/CTA frequency, and near-duplicate detection against
     recent posts.
  2. LLM judgment (cheap Flash-Lite): catches "salesy"/spammy tone the rules miss.

A post that fails is never silently published — the orchestrator attempts one
regeneration and otherwise flags the card so the human decides.
"""

from __future__ import annotations

import difflib
import logging
import re

from . import config
from .schemas import GuardrailResult
from .tools import llm

log = logging.getLogger("guardrails")

# crude but effective URL / bare-domain detector
_URL_RE = re.compile(r"(https?://|www\.|\b[\w-]+\.(?:com|in|co|io|app|shop|store)\b)", re.I)


def deterministic_check(post: dict, recent_texts: list[str]) -> GuardrailResult:
    caption = (post.get("caption_primary") or "")
    low = caption.lower()
    platform = post.get("platform", "instagram")
    violations: list[str] = []

    for word in config.SPAM_TRIGGER_WORDS:
        if word in low:
            violations.append(f"spam-trigger phrase: '{word}'")

    fit = config.PLATFORM_FIT.get(platform, {})
    max_tags = fit.get("max_hashtags", 30)
    tags = (post.get("hashtags") or "")
    n_tags = len([t for t in tags.split() if t.startswith("#")])
    if n_tags > max_tags:
        violations.append(f"{n_tags} hashtags exceeds {platform} limit of {max_tags}")

    n_links = len(_URL_RE.findall(caption))
    if n_links > config.MAX_LINKS_PER_CAPTION:
        violations.append(f"{n_links} links/CTAs exceeds limit of {config.MAX_LINKS_PER_CAPTION}")

    for prev in recent_texts:
        if not prev:
            continue
        ratio = difflib.SequenceMatcher(None, low, prev.lower()).ratio()
        if ratio >= config.DUPLICATE_SIMILARITY_THRESHOLD:
            violations.append(f"near-duplicate of a recent post (similarity {ratio:.2f})")
            break

    if violations:
        return GuardrailResult(ok=False, severity="block", violations=violations)
    return GuardrailResult(ok=True, severity="ok", violations=[])


def llm_review(post: dict) -> GuardrailResult:
    """A cheap tone check. Fails open (ok=True) if the model errors."""
    prompt = (
        "You are a brand safety reviewer. Decide if this social caption reads as "
        "spammy, pushy, or salesy for a premium minimalist brand.\n"
        "Reply with exactly 'OK' if it is fine, or 'FLAG: <one short reason>'.\n\n"
        f"Platform: {post.get('platform')}\n"
        f"Caption: {post.get('caption_primary', '')}"
    )
    try:
        verdict = llm.generate_text(prompt, model=config.MODEL_FAST).strip()
    except Exception:
        log.exception("llm guardrail review failed; failing open")
        return GuardrailResult(ok=True, severity="ok", violations=[])

    if verdict.upper().startswith("FLAG"):
        reason = verdict.split(":", 1)[-1].strip() if ":" in verdict else "tone risk"
        return GuardrailResult(ok=False, severity="warn", violations=[f"tone: {reason}"])
    return GuardrailResult(ok=True, severity="ok", violations=[])


def evaluate(post: dict, recent_texts: list[str], use_llm: bool = True) -> GuardrailResult:
    """Run the full gate. Deterministic 'block' short-circuits the LLM call."""
    det = deterministic_check(post, recent_texts)
    if not det.ok:
        return det
    if use_llm:
        return llm_review(post)
    return det
