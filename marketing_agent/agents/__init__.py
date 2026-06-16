"""Phase 2 marketing department — specialized agent factories.

Each module builds one "role" in the department:
  research.py     — trends & values dossier (upgrades the Phase 1 topic agent)
  campaign.py     — campaign strategist + brief writer (platform fit + anti-spam)
  content_team.py — per-post evaluator-optimizer loop (copywriter -> art -> critic)
  critic.py       — the quality critic used inside the content loop
  monitor.py      — performance monitor (durable publish retry + report)

The department is wired together in marketing_agent/orchestrator.py.
"""
