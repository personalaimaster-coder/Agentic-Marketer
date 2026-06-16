"""Lightweight one-shot Gemini text calls.

Used for cheap single-turn regenerations (e.g. "rewrite this caption") where
spinning up a full ADK Runner session would be overkill. Shares the same Vertex
AI routing as the image client.
"""

from __future__ import annotations

from google import genai

from .. import config

_client: genai.Client | None = None


def client() -> genai.Client:
    global _client
    if _client is None:
        if config.USE_VERTEX:
            _client = genai.Client(
                vertexai=True,
                project=config.GOOGLE_CLOUD_PROJECT,
                location=config.GOOGLE_CLOUD_LOCATION,
            )
        else:
            _client = genai.Client()
    return _client


def generate_text(prompt: str, model: str | None = None) -> str:
    resp = client().models.generate_content(
        model=model or config.MODEL_SMART,
        contents=prompt,
    )
    return (getattr(resp, "text", None) or "").strip()
