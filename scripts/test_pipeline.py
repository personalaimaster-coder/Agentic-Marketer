"""
Test script — progressive modes across Phase 1 and the Phase 2 department.

Usage:
  python scripts/test_pipeline.py --mode sources
  python scripts/test_pipeline.py --mode reasoning            # Phase 2 department
  python scripts/test_pipeline.py --mode reasoning --phase 1  # Phase 1 baseline
  python scripts/test_pipeline.py --mode full

Modes
-----
  sources   : Fetch RSS/Reddit feeds and print what the agents would see.
              No GCP credentials needed.

  reasoning : Run the ADK reasoning agents (needs Vertex AI / Gemini).
              Mocks Firestore + GCS + Telegram so no real side-effects.
              --phase selects which pipeline to exercise:
                1   = Phase 1 linear pipeline (topic->brief->caption->art)
                2a  = research + per-post critic loop + guardrail gate
                2b  = + campaign strategist + anti-spam (same code path as 2)
                2c  = + research dossier + regional (same code path as 2)
                2   = the full department (default)

  full      : Real end-to-end — actually generates images, saves to Firestore,
              sends Telegram approval cards. Use only when infra is set up.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

# Make the repo root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Mode 1 — Sources only
# ---------------------------------------------------------------------------
def test_sources():
    print("\n=== MODE: sources ===")
    from marketing_agent import config
    from marketing_agent.sources import get_source_provider

    print(f"Provider: {config.SOURCE_PROVIDER} (no GCP required for rss/none)...\n")
    items = get_source_provider().fetch(limit=40)
    if not items:
        print("⚠️  No items returned. Check your internet connection or feed URLs.")
        return

    print(f"Fetched {len(items)} items.\n")
    for i, item in enumerate(items[:10]):
        print(f"  {i+1:>2}. [{item['source']:>8}] {item['title'][:80]}")
    if len(items) > 10:
        print(f"  ... and {len(items) - 10} more")
    print("\n✅ Sources OK — agent has enough signal to work with.")


# ---------------------------------------------------------------------------
# Mode 2 — Reasoning only (mocks all I/O; live Gemini for the agents)
# ---------------------------------------------------------------------------
def test_reasoning(phase: str = "2"):
    print("\n=== MODE: reasoning ===")
    print(f"Phase: {phase}")
    print("Running ADK agents against live Gemini (Vertex AI).")
    print("Firestore / GCS / Telegram are MOCKED — no real side-effects.\n")

    from marketing_agent.sources import get_source_provider

    raw = get_source_provider().fetch(limit=40)
    if not raw:
        print("⚠️  No sources — run sources mode first to debug feeds.")
        sys.exit(1)

    # Patch I/O at the module level so the pipeline never touches real infra.
    with (
        patch("marketing_agent.tools.firestore_store.all_active_rules", return_value={}),
        patch("marketing_agent.tools.firestore_store.save_post", return_value="test-post-id"),
        patch("marketing_agent.tools.firestore_store.update_post"),
        patch("marketing_agent.tools.firestore_store.save_campaign", return_value="test-campaign-id"),
        patch("marketing_agent.tools.firestore_store.recent_caption_texts", return_value=[]),
        patch("marketing_agent.tools.imagen.generate_card", return_value="https://example.com/fake-image.png"),
        patch("marketing_agent.tools.telegram.send_approval_card", return_value="99999"),
    ):
        if phase == "1":
            from marketing_agent.pipeline import run_daily_pipeline
            result = asyncio.run(run_daily_pipeline())
        else:
            from marketing_agent.orchestrator import run_department_pipeline
            result = asyncio.run(run_department_pipeline())

    print(f"\nResult: {json.dumps(result, indent=2)}")
    if result.get("ok"):
        print(f"\n✅ Reasoning passed — {result.get('posts_created', 0)} posts would be created.")
        if result.get("guardrail_flagged") is not None:
            print(f"   Guardrail-flagged: {result['guardrail_flagged']}  ·  "
                  f"campaign_id: {result.get('campaign_id')}")
    else:
        print(f"\n❌ Reasoning failed: {result.get('reason', 'unknown')}")


# ---------------------------------------------------------------------------
# Mode 3 — Full end-to-end (real GCP)
# ---------------------------------------------------------------------------
def test_full(phase: str = "2"):
    print("\n=== MODE: full ===")
    print(f"Phase: {phase}")
    print("Full end-to-end: real Gemini + real Firestore + real GCS + real Telegram.\n")
    print("This WILL:")
    print("  • Generate images (~$0.04 each)")
    print("  • Write posts to Firestore")
    print("  • Send Telegram approval cards to your phone\n")
    answer = input("Continue? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        sys.exit(0)

    if phase == "1":
        from marketing_agent.pipeline import run_daily_pipeline
        result = asyncio.run(run_daily_pipeline())
    else:
        from marketing_agent.orchestrator import run_department_pipeline
        result = asyncio.run(run_department_pipeline())
    print(f"\nResult: {json.dumps(result, indent=2)}")
    if result.get("ok"):
        print(f"\n✅ Pipeline complete — check Telegram for approval cards.")
    else:
        print(f"\n❌ Pipeline failed: {result.get('reason', 'unknown error')}")


# ---------------------------------------------------------------------------
# Bonus — print the prompt that would go to each agent (no GCP needed)
# ---------------------------------------------------------------------------
def show_prompts():
    print("\n=== Effective agent instructions ===\n")
    from marketing_agent.prompts import build_instruction

    for role in ("research", "campaign", "topic", "brief", "caption", "image", "critic", "reflector"):
        print(f"--- {role.upper()} AGENT ---")
        print(build_instruction(role, []))
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Marketing Agent pipeline test runner")
    parser.add_argument(
        "--mode",
        choices=["sources", "reasoning", "full", "prompts"],
        default="sources",
        help="Test depth (default: sources)",
    )
    parser.add_argument(
        "--phase",
        choices=["1", "2", "2a", "2b", "2c"],
        default="2",
        help="Which pipeline to exercise in reasoning/full modes (default: 2)",
    )
    args = parser.parse_args()

    if args.mode == "sources":
        test_sources()
    elif args.mode == "reasoning":
        test_reasoning(args.phase)
    elif args.mode == "full":
        test_full(args.phase)
    elif args.mode == "prompts":
        show_prompts()
