"""I/O tools — the pure-Python side of the pipeline.

The LLM agents do reasoning; these functions do the deterministic work
(fetching feeds, persisting to Firestore, generating/uploading images,
sending Telegram cards, publishing via Buffer).
"""
