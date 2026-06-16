"""Cloud Storage upload — hosts the final post image and returns a public URL
that Telegram (preview) and Buffer (publish) can both fetch.
"""

from __future__ import annotations

import uuid

from google.cloud import storage

from .. import config

_client: storage.Client | None = None


def client() -> storage.Client:
    global _client
    if _client is None:
        _client = storage.Client(project=config.GOOGLE_CLOUD_PROJECT or None)
    return _client


def upload_image(image_bytes: bytes, content_type: str = "image/png") -> str:
    """Upload bytes to the post-images bucket and return the public URL.

    The bucket is expected to grant public read (see infra/setup.sh). This mirrors
    the old Supabase public bucket so Buffer can pull the media by URL.
    """
    bucket = client().bucket(config.GCS_BUCKET)
    blob = bucket.blob(f"posts/{uuid.uuid4().hex}.png")
    blob.upload_from_string(image_bytes, content_type=content_type)
    return blob.public_url
