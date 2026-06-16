"""Branded image generation via Gemini 2.5 Flash Image ("Nano Banana").

This single call replaces TWO old vendors: Replicate (background generation)
AND HCTI (HTML->image text compositing). Nano Banana generates the scene and
renders the legible headline text directly onto a 1:1 branded card.
"""

from __future__ import annotations

from google import genai
from google.genai import types

from .. import config
from . import gcs

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
            _client = genai.Client()  # uses GOOGLE_API_KEY
    return _client


def _brand_wrap(prompt: str, headline: str, eyebrow: str, platform: str) -> str:
    return (
        f"{prompt}\n\n"
        f"Square 1:1 social card for {config.BRAND_NAME}. "
        f"Aesthetic: {config.BRAND_COLORS}. Clean, professional, well-composed.\n"
        f"Render this text cleanly onto the image, well-composed and highly legible:\n"
        f"  - small uppercase eyebrow label: \"{eyebrow}\"\n"
        f"  - bold headline: \"{headline}\"\n"
        f"No competitor logos and no spelling errors in the rendered text. "
        f"Leave breathing room around the text."
    )


def generate_card(prompt: str, headline: str, eyebrow: str, platform: str) -> str:
    """Generate the branded card and return its public Cloud Storage URL."""
    full_prompt = _brand_wrap(prompt, headline, eyebrow, platform)

    response = client().models.generate_content(
        model=config.MODEL_IMAGE,
        contents=full_prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    image_bytes = _extract_image_bytes(response)
    if not image_bytes:
        raise RuntimeError("Image model returned no image data")
    return gcs.upload_image(image_bytes)


def _extract_image_bytes(response) -> bytes | None:
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                return inline.data
    return None
