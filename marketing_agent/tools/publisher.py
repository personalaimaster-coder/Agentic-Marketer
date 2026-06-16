"""Buffer publishing via the current GraphQL API (createPost + shareNow).

Buffer is a thin passthrough to Instagram/Pinterest/X so we don't manage three
separate OAuth flows. We never use Buffer's scheduler — Firestore holds the
queue and we fire `shareNow` at the right moment (JIT publishing).
"""

from __future__ import annotations

import httpx

from .. import config

_GRAPHQL_URL = "https://api.buffer.com"

_CREATE_POST = """
mutation CreatePost($input: PostCreateInput!) {
  postCreate(input: $input) { id status }
}
"""


def publish(platform: str, caption: str, image_url: str) -> dict:
    """Publish immediately to one channel. Returns {success, buffer_post_id, error}."""
    channel_id = config.BUFFER_CHANNEL_IDS.get(platform, "")
    if not channel_id:
        return {"success": False, "buffer_post_id": None, "error": f"no channel id for {platform}"}

    variables = {
        "input": {
            "channelIds": [channel_id],
            "text": caption,
            "media": [{"photo": image_url, "thumbnail": image_url}],
            "mode": "shareNow",
        }
    }

    try:
        resp = httpx.post(
            _GRAPHQL_URL,
            headers={
                "Authorization": f"Bearer {config.BUFFER_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"query": _CREATE_POST, "variables": variables},
            timeout=45,
        )
        data = resp.json()
    except Exception as exc:  # network / parse failure
        return {"success": False, "buffer_post_id": None, "error": str(exc)}

    if data.get("errors"):
        return {"success": False, "buffer_post_id": None, "error": str(data["errors"])}

    post = (data.get("data") or {}).get("postCreate") or {}
    return {"success": bool(post.get("id")), "buffer_post_id": post.get("id"), "error": None}
